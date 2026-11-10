"""Run the local website and model API: python -m website.api.server."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from secondthought.steering_rewriter import SteeredQwenRewriter
from .generation import AdmissionError, GenerationManager, VERSION
from .schemas import CancelRequest, RewriteRequest

logger = logging.getLogger(__name__)
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
TERMINAL = {"completed", "cancelled", "error"}


def create_app(service=None, *, service_factory=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        app.state.status = "loading"
        app.state.manager = None

        async def initialize():
            try:
                loaded = service
                if loaded is None:
                    factory = service_factory or (lambda: SteeredQwenRewriter(
                        device=os.getenv("SECONDTHOUGHT_WEBSITE_DEVICE") or None,
                    ))
                    loaded = await asyncio.to_thread(factory)
                manager = GenerationManager(loaded)
                manager.start()
                app.state.manager = manager
                app.state.status = "ready"
            except Exception:
                logger.exception("Website model initialization failed")
                app.state.status = "unavailable"

        boot = asyncio.create_task(initialize())
        try:
            yield
        finally:
            await boot
            if app.state.manager:
                await app.state.manager.close()

    app = FastAPI(title="SecondThought steering API", lifespan=lifespan)
    app.state.status = "loading"
    app.state.manager = None

    def manager():
        if app.state.manager is None:
            raise HTTPException(503, "The model is loading or unavailable. Please try again shortly.")
        return app.state.manager

    def submit(body):
        try:
            return manager().submit(body)
        except AdmissionError as exc:
            raise HTTPException(exc.status_code, exc.detail,
                                headers={"Retry-After": "2"} if exc.status_code == 429 else None) from exc

    async def events(job, request):
        owner = manager()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(job.events.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                yield event
                if event["event"] in TERMINAL:
                    break
        finally:
            owner.cancel(job)

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready():
        if app.state.status != "ready":
            raise HTTPException(503, app.state.status)
        return {"status": "ready"}

    @app.get("/api/v1/steering/config")
    async def config():
        return dict(
            status=app.state.status, model_id="Qwen/Qwen2.5-0.5B-Instruct",
            steering_version=VERSION, objective="formality", layer=11,
            alpha=dict(min=-2, max=2, step=0.1, default=0.5), beta=0,
            max_characters=2000, max_prompt_tokens=384, max_new_tokens=64,
        )

    @app.post("/api/v1/steering/rewrite")
    async def rewrite(body: RewriteRequest, request: Request):
        job = submit(body)
        async for event in events(job, request):
            if event["event"] == "completed":
                return event
            if event["event"] == "error":
                status = 422 if event.get("code") == "invalid_input" else 504 if event.get("code") == "timeout" else 500
                raise HTTPException(status, event["detail"])
            if event["event"] == "cancelled":
                raise HTTPException(409, "This request was superseded.")
        raise HTTPException(409, "The request was disconnected.")

    @app.post("/api/v1/steering/stream")
    async def stream(body: RewriteRequest, request: Request):
        job = submit(body)
        async def lines():
            async for event in events(job, request):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        return StreamingResponse(lines(), media_type="application/x-ndjson", headers={
            "Cache-Control": "no-store", "X-Accel-Buffering": "no",
        })

    @app.post("/api/v1/steering/cancel")
    async def cancel(body: CancelRequest):
        if app.state.manager:
            app.state.manager.cancel_revision(str(body.session_id), body.revision)
        return {"status": "ok"}

    @app.get("/")
    async def index():
        return FileResponse(FRONTEND / "index.html")

    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets", check_dir=False), name="assets")
    return app


app = create_app()


def main():
    # One process per model instance. The extension retains port 8000.
    uvicorn.run("website.api.server:app", host="127.0.0.1", port=8001, workers=1)


if __name__ == "__main__":
    main()
