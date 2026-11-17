"""Run the local website and model API: python -m website.api.server."""

from __future__ import annotations

import asyncio
import io
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import zipfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from secondthought.steering_rewriter import BASE_REWRITE_PROMPT
from .generation import AdmissionError, GenerationManager, VERSION
from .schemas import CancelRequest, RewriteRequest
from .layers import ExploreRewriter, layer_manifest

logger = logging.getLogger(__name__)
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
EXTENSION_FRONTEND = Path(__file__).resolve().parents[2] / "extension" / "frontend"
LOCAL_DOWNLOAD = "/downloads/secondthought-extension.zip"
# Where the setup page sends people. Both point at this machine until we deploy;
# set these to the hosted package and API to switch, no code changes needed.
EXTENSION_DOWNLOAD_URL = os.getenv("SECONDTHOUGHT_EXTENSION_DOWNLOAD_URL", LOCAL_DOWNLOAD)
EXTENSION_API_URL = os.getenv("SECONDTHOUGHT_EXTENSION_API_URL", "http://127.0.0.1:8000")
TERMINAL = {"completed", "cancelled", "error"}
PAGES = {
    "steering": ("/explore", "Explore", "Explore activation steering, one layer at a time."),
    "community": ("/community", "Community", "Bring a second thought to your everyday writing."),
    "evaluation": ("/evaluation", "Evaluation", "SecondThought evaluation."),
}


INSTALL_NOTE = """SecondThought for Chrome
=======================

1. Keep this folder somewhere it can stay, like Documents/SecondThought.
   Chrome runs the extension from here, so don't move or delete it.

2. Open chrome://extensions, switch on "Developer mode" (top right),
   click "Load unpacked" and choose this SecondThought folder.

3. Start the rewriting service. From the project folder, run:

       uv run python -m extension.api.server

   Leave that window open. First time on this computer? Run
   "uv sync --extra evaluation" first, and put the both-t5 model
   folder in models/.

4. Pin SecondThought from the puzzle-piece icon, then type something
   heated in Gmail or Slack. A small "SecondThought?" pill appears.

The full guide, with a live check of the service, is on the website's
Community page.
"""


def extension_zip() -> bytes:
    """The Chrome extension as a zip, built from extension/frontend so it's never stale."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(EXTENSION_FRONTEND.rglob("*")):
            if path.is_file():
                archive.write(path, Path("SecondThought") / path.relative_to(EXTENSION_FRONTEND))
        archive.writestr("SecondThought/HOW TO INSTALL.txt", INSTALL_NOTE)
    return buffer.getvalue()


def create_app(service=None, *, service_factory=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        app.state.status = "loading"
        app.state.manager = None

        async def initialize():
            try:
                loaded = service
                if loaded is None:
                    factory = service_factory or (lambda: ExploreRewriter(
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
            layers=layer_manifest(),
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

    templates = Jinja2Templates(directory=str(FRONTEND))

    def page_handler(page: str):
        async def render(request: Request):
            _, title, description = PAGES[page]
            return templates.TemplateResponse(
                request=request,
                name="index.html" if page == "home" else f"{page}.html",
                context=dict(
                    page=page, title=title, description=description,
                    rewrite_prompt=BASE_REWRITE_PROMPT, layers=layer_manifest(),
                    extension_download_url=EXTENSION_DOWNLOAD_URL,
                    extension_api_url=EXTENSION_API_URL,
                    navigation=[(key, path, label) for key, (path, label, _) in PAGES.items()],
                ),
            )
        return render

    for page, (path, _, _) in PAGES.items():
        app.add_api_route(path, page_handler(page), response_class=HTMLResponse,
                          include_in_schema=False, name=f"{page}_page")

    def redirect_handler(destination):
        async def redirect():
            return RedirectResponse(destination, status_code=307)
        return redirect

    for old_path, target in (("/", "/explore"), ("/steering", "/explore"),
                             ("/extension", "/community"), ("/about", "/community")):
        app.add_api_route(old_path, redirect_handler(target), include_in_schema=False)

    @app.get(LOCAL_DOWNLOAD, include_in_schema=False)
    async def download_extension():
        if not (EXTENSION_FRONTEND / "manifest.json").is_file():
            raise HTTPException(404, "The extension folder isn't in this checkout.")
        return Response(
            extension_zip(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="secondthought-extension.zip"'},
        )

    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets", check_dir=False), name="assets")
    return app


app = create_app()


def main():
    # One process per model instance. The extension retains port 8000.
    uvicorn.run("website.api.server:app", host="127.0.0.1", port=8001, workers=1)


if __name__ == "__main__":
    main()
