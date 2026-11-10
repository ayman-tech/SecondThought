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

from .schemas import RewriteRequest

logger = logging.getLogger(__name__)
VERSION = "qwen-formality-v1"


class AdmissionError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code, self.detail = status_code, detail


@dataclass
class Job:
    request: RewriteRequest
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
        self.events.put_nowait(dict(
            event=kind, request_id=self.request_id,
            revision=self.request.revision, alpha=self.request.alpha, beta=0,
            **data,
        ))


class GenerationManager:
    def __init__(self, service, *, max_pending=8, max_sessions=128, timeout_seconds=25):
        self.service = service
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

    def submit(self, request: RewriteRequest) -> Job:
        if self.closing:
            raise AdmissionError(503, "The model is shutting down.")
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
        job = Job(request)
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
                result = await asyncio.to_thread(
                    self.service.stream_rewrite, job.request.message, job.request.alpha, 0,
                    on_text=on_text, cancelled=job.cancelled,
                    max_input_tokens=384, timeout_seconds=self.timeout_seconds,
                )
                if job.cancelled.is_set():
                    job.emit("cancelled")
                else:
                    job.emit("completed", rewritten_text=result.text,
                             generated_tokens=result.generated_tokens,
                             finish_reason=result.finish_reason,
                             latency_ms=round((monotonic() - started) * 1000, 1),
                             model_id=self.service.model_id, steering_version=VERSION)
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
