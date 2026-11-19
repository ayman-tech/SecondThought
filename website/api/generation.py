"""Single model worker with bounded, per-session latest-request scheduling."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
import logging
from threading import Event
from time import monotonic
from uuid import uuid4

from secondthought.steering_rewriter import GenerationCancelled
from secondthought.lab.plans import InterventionPlan

from .schemas import RewriteRequest, RunRequest
from .runs import canonical_request, resolve_run, DEFAULT_MODEL

logger = logging.getLogger(__name__)
VERSION = "lab-interventions-v6"


class AdmissionError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code, self.detail = status_code, detail


@dataclass
class Job:
    request: RewriteRequest | RunRequest
    run: RunRequest | None = None
    plan: InterventionPlan | None = None
    configuration: dict = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid4()))
    cancelled: Event = field(default_factory=Event)
    events: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=128))
    submitted: float = field(default_factory=monotonic)

    def emit(self, kind: str, **data):
        # All calls run on the event loop, including callbacks from the worker.
        if self.events.full():
            self.cancelled.set()
            while not self.events.empty():
                self.events.get_nowait()
            kind, data = "error", {"detail": "The response consumer is too slow. Retry."}
        envelope = dict(
            event=kind, request_id=self.request_id,
            revision=self.request.revision, plan_id=self.plan.plan_id if self.plan else None,
            experiment_id=self.configuration.get('experiment_id'))
        if isinstance(self.request, RewriteRequest):
            envelope.update(alpha=self.request.alpha,beta=0,
                layer_strengths=self.request.layer_strengths,layer_vector_ids=self.request.layer_vector_ids,
                task=self.request.task,system_prompt=self.request.system_prompt,
                max_input_tokens=self.request.max_input_tokens,max_new_tokens=self.request.max_new_tokens)
        else:
            envelope.update(schema_version=2,model_id=self.run.model_id,
                            catalog_version=self.plan.catalog_version)
        if kind == 'completed':
            envelope['applied'] = self.configuration
        envelope.update(data)
        self.events.put_nowait(envelope)


class GenerationManager:
    def __init__(self, service, *, max_pending=8, max_sessions=128, timeout_seconds=90):
        self.service = service
        catalog_version = getattr(service, 'catalog_version', None)
        self.version = f'{VERSION}:{catalog_version}' if catalog_version else VERSION
        self.max_pending = max_pending
        self.max_sessions = max_sessions
        self.timeout_seconds = timeout_seconds
        self.pending: OrderedDict[str, Job] = OrderedDict()
        self.sessions: OrderedDict[str, tuple[int, float]] = OrderedDict()
        self.active: Job | None = None
        self.wake = asyncio.Event()
        self.closing = False
        self.worker: asyncio.Task | None = None

    def start(self):
        self.worker = asyncio.create_task(self._run())

    def runtime_info(self):
        model=getattr(self.service,'model',None)
        device=getattr(self.service,'device',None)
        dtype=getattr(model,'dtype',None)
        return dict(device=str(device) if device is not None else None,
                    dtype=str(dtype) if dtype is not None else None,
                    model_revision=getattr(self.service,'model_revision',None))

    def resolve(self, request):
        catalog = getattr(self.service,'catalog',None)
        run = canonical_request(request,catalog)
        plan, configuration = resolve_run(run,catalog)
        return run,plan,configuration

    def submit(self, request: RewriteRequest | RunRequest) -> Job:
        if self.closing:
            raise AdmissionError(503, "The model is shutting down.")
        run,plan,configuration = self.resolve(request)
        if isinstance(request, RunRequest) and not callable(getattr(self.service,'stream_run',None)):
            raise AdmissionError(503,'This worker does not support the v2 run protocol')
        if run.model_id != getattr(self.service,'catalog_model_id',DEFAULT_MODEL):
            raise AdmissionError(503,'The requested catalog model is not loaded in this worker')
        sid = str(request.session_id)
        active_sid = str(self.active.request.session_id) if self.active else None
        for key, (_, seen) in list(self.sessions.items()):
            if monotonic() - seen > 600 and key not in self.pending and key != active_sid:
                self.sessions.pop(key)
        if sid in self.sessions and request.revision <= self.sessions[sid][0]:
            raise AdmissionError(409, "This input revision has already been superseded.")
        if sid not in self.sessions and len(self.sessions) >= self.max_sessions:
            raise AdmissionError(429, "Too many sessions. Please try again later.")
        if sid not in self.pending and len(self.pending) >= self.max_pending:
            raise AdmissionError(429, "The model is busy. Please retry shortly.")
        if sid in self.pending:
            old = self.pending[sid]
            old.cancelled.set()
            old.emit("cancelled")
        if self.active and active_sid == sid:
            self.active.cancelled.set()
        job = Job(request,run=run,plan=plan,configuration=configuration)
        # Replacing the value retains its queue position: other tabs get a turn.
        self.pending[sid] = job
        self.sessions[sid] = (request.revision, monotonic())
        job.emit("queued")
        self.wake.set()
        return job

    def cancel(self, job: Job):
        job.cancelled.set()
        sid = str(job.request.session_id)
        if self.pending.get(sid) is job:
            self.pending.pop(sid)
            job.emit("cancelled")

    def cancel_revision(self, sid: str, revision: int):
        jobs = [self.pending.get(sid), self.active]
        for job in jobs:
            if job and str(job.request.session_id) == sid and job.request.revision == revision:
                self.cancel(job)

    async def _run(self):
        loop = asyncio.get_running_loop()
        while True:
            await self.wake.wait()
            if self.closing:
                return
            if not self.pending:
                self.wake.clear()
                continue
            _, job = self.pending.popitem(last=False)
            self.active = job
            started = monotonic()
            job.emit("started", queue_ms=round((started - job.submitted) * 1000, 1))

            def on_text(text, current=job):
                if not current.cancelled.is_set():
                    loop.call_soon_threadsafe(lambda: current.emit("delta", text=text)
                                              if not current.cancelled.is_set() else None)
            try:
                options = dict(on_text=on_text,cancelled=job.cancelled,
                    system_prompt=job.run.system_prompt,**job.run.generation.model_dump(),
                    timeout_seconds=self.timeout_seconds)
                if callable(getattr(self.service,'stream_run',None)):
                    result = await asyncio.to_thread(self.service.stream_run,job.plan,job.run.input,**options)
                else:
                    # Compatibility for injected v1-only services. Production
                    # ExploreRewriter executes v1 and v2 through stream_run.
                    result = await asyncio.to_thread(
                        self.service.stream_rewrite,job.request.message,job.request.alpha,0,**options,
                        **({'layer_strengths':dict(job.request.layer_strengths)} if job.request.layer_strengths is not None else {}),
                        **({'layer_vector_ids':dict(job.request.layer_vector_ids)} if job.request.layer_vector_ids else {}))
                if job.cancelled.is_set():
                    job.emit("cancelled")
                else:
                    job.emit("completed", **({'text':result.text} if isinstance(job.request,RunRequest) else {'rewritten_text':result.text}),
                             generated_tokens=result.generated_tokens,
                             finish_reason=result.finish_reason,
                             latency_ms=round((monotonic() - started) * 1000, 1),
                             model_id=job.run.model_id if isinstance(job.request,RunRequest) else self.service.model_id,
                             model_repository=self.service.model_id, steering_version=self.version,
                             runtime=self.runtime_info())
            except GenerationCancelled:
                job.emit("cancelled")
            except ValueError as exc:
                job.emit("error", detail=str(exc), code="invalid_input")
            except TimeoutError as exc:
                job.emit("error", detail=str(exc), code="timeout")
            except Exception:
                logger.exception("Steering request %s failed", job.request_id)
                job.emit("error", detail="Generation failed. Please retry.", code="generation_failed")
            finally:
                self.active = None

    async def close(self):
        self.closing = True
        if self.active:
            self.cancel(self.active)
        for job in list(self.pending.values()):
            self.cancel(job)
        self.wake.set()
        if self.worker:
            await self.worker
