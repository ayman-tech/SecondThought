"""Run the local website and model API: python -m website.api.server."""

from __future__ import annotations

import asyncio
import hashlib
import io
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import zipfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, Response, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from secondthought.steering_rewriter import BASE_REWRITE_PROMPT
from .generation import AdmissionError, GenerationManager, VERSION
from .schemas import CancelRequest, RewriteRequest, RunRequest
from secondthought.lab.plans import MAX_INTERVENTIONS
from .runs import resolve_run
from .prompts import (TASKS, LIMITS, MAX_CHARACTERS, DEFAULT_INPUT_TOKENS, MAX_INPUT_TOKENS,
                      DEFAULT_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS)
from .layers import ExploreRewriter, layer_manifest, DEFAULT_MODEL
from secondthought.lab.catalog import get_catalog
from secondthought.lab.evidence import layer_evidence_profiles

logger = logging.getLogger(__name__)
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
_asset_digest = hashlib.sha256()
for _asset in sorted((FRONTEND / 'assets').rglob('*')):
    if _asset.is_file() and _asset.suffix in {'.js', '.css'}:
        _asset_digest.update(str(_asset.relative_to(FRONTEND)).encode())
        _asset_digest.update(_asset.read_bytes())
FRONTEND_ASSETS = f'/assets/build-{_asset_digest.hexdigest()[:16]}'


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        # Local development also permits edits without restarting the process.
        response.headers['Cache-Control'] = 'no-cache'
        return response


EXTENSION_FRONTEND = Path(__file__).resolve().parents[2] / "extension" / "frontend"
LOCAL_DOWNLOAD = "/downloads/secondthought-extension.zip"
# Where the setup page sends people. Both point at this machine until we deploy;
# set these to the hosted package and API to switch, no code changes needed.
EXTENSION_DOWNLOAD_URL = os.getenv("SECONDTHOUGHT_EXTENSION_DOWNLOAD_URL", LOCAL_DOWNLOAD)
EXTENSION_API_URL = os.getenv("SECONDTHOUGHT_EXTENSION_API_URL", "http://127.0.0.1:8000")
TERMINAL = {"completed", "cancelled", "error"}
PAGES = {
    "home": ("/", "Home", "Rewrite privately in Chrome or tune model behavior in the SecondThought Steering Lab."),
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

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Do not echo raw inputs: nonfinite JSON numbers cannot be serialized
        # in a validation response, and prompts can be large.
        return JSONResponse(status_code=422,content={'detail':[
            {key:error[key] for key in ('type','loc','msg')} for error in exc.errors()]})

    def manager():
        if app.state.manager is None:
            raise HTTPException(503, "The model is loading or unavailable. Please try again shortly.")
        return app.state.manager

    def active_catalog():
        owner = app.state.manager
        if owner is None:
            return get_catalog()
        return getattr(owner.service,'catalog',None) or get_catalog()

    def runtime_models():
        owner = app.state.manager
        if app.state.status != 'ready' or owner is None or not callable(getattr(owner.service,'stream_run',None)):
            return []
        return [owner.service.catalog_model_id]

    def submit(body):
        try:
            return manager().submit(body)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
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
            steering_version=(app.state.manager.version if app.state.manager else f'{VERSION}:{get_catalog().version}'),
            catalog_version=get_catalog().version, objective="formality", layer=11,
            catalog_model_id=DEFAULT_MODEL,
            alpha=dict(min=-2, max=2, step=0.1, default=0.5), beta=0,
            max_characters=MAX_CHARACTERS, max_prompt_tokens=MAX_INPUT_TOKENS,
            max_new_tokens=MAX_OUTPUT_TOKENS,
            default_input_tokens=DEFAULT_INPUT_TOKENS, default_output_tokens=DEFAULT_OUTPUT_TOKENS,
            task_presets=TASKS, request_timeout_ms=110000,
            runtime=app.state.manager.runtime_info() if app.state.manager else None,
            layers=layer_manifest(),
            features=[f.model_dump() for f in get_catalog().spec.features],
        )

    @app.get('/api/v2/lab/catalog')
    async def catalog():
        return dict(**active_catalog().public(), runtime_status=app.state.status,
            execution=dict(protocol='v2',composition='weighted_sum',token_scope='all_tokens',
                max_interventions=MAX_INTERVENTIONS,
                runtime_model_ids=runtime_models()))

    @app.post('/api/v2/lab/runs/resolve')
    async def resolve(body: RunRequest):
        if body.catalog_version and body.catalog_version != active_catalog().version:
            raise HTTPException(409,'Catalog version changed; reload the catalog before retrying')
        try:
            _,configuration = resolve_run(body,active_catalog())
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
        return dict(schema_version=2,resolved=configuration,
            runtime_ready=body.model_id in runtime_models())

    async def completed_response(body, request):
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

    @app.post('/api/v2/lab/runs')
    async def run(body: RunRequest,request: Request):
        if body.catalog_version and body.catalog_version != active_catalog().version:
            raise HTTPException(409,'Catalog version changed; reload the catalog before retrying')
        return await completed_response(body,request)

    @app.post("/api/v1/steering/rewrite")
    async def rewrite(body: RewriteRequest,request: Request):
        return await completed_response(body,request)

    def stream_response(body,request):
        job = submit(body)
        async def lines():
            async for event in events(job, request):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        return StreamingResponse(lines(), media_type="application/x-ndjson", headers={
            "Cache-Control": "no-store", "X-Accel-Buffering": "no",
        })

    @app.post('/api/v2/lab/runs/stream')
    async def run_stream(body: RunRequest,request: Request):
        if body.catalog_version and body.catalog_version != active_catalog().version:
            raise HTTPException(409,'Catalog version changed; reload the catalog before retrying')
        return stream_response(body,request)

    @app.post("/api/v1/steering/stream")
    async def stream(body: RewriteRequest,request: Request):
        return stream_response(body,request)

    @app.post('/api/v2/lab/runs/cancel')
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
                    frontend_assets=FRONTEND_ASSETS,
                    rewrite_prompt=BASE_REWRITE_PROMPT, layers=layer_manifest(),
                    task_presets=TASKS,
                    prompt_limits=LIMITS,
                    layer_evidence=layer_evidence_profiles(get_catalog(),DEFAULT_MODEL) if page == 'steering' else [],
                    feature_sources={a['id']:{key:a.get('provenance',{}).get(key) for key in
                        ('dataset','pair_construction','limitations','extraction_pairs','heldout_pairs','attribution')}
                        for a in get_catalog().public()['artifacts']} if page == 'steering' else {},
                    layer_vectors=[dict(v, feature_label=get_catalog().features[v['feature_id']].label,
                        selectable=get_catalog().artifacts[v['artifact_id']].format == 'all_layers_v1')
                        for v in get_catalog().public()['vectors'] if v['model_id'] == DEFAULT_MODEL]
                        if page == 'steering' else [],
                    steering_features=[f.label for f in get_catalog().spec.features] if page == "home" else [],
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

    for old_path, target in (("/steering", "/explore"),
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

    # A versioned prefix also versions every relative ES-module import.
    app.mount(FRONTEND_ASSETS, FrontendFiles(directory=FRONTEND / 'assets'), name='versioned_assets')
    app.mount("/assets", FrontendFiles(directory=FRONTEND / "assets", check_dir=False), name="assets")
    return app


app = create_app()


def main():
    # One process per model instance. The extension retains port 8000.
    uvicorn.run("website.api.server:app", host="127.0.0.1", port=8001, workers=1)


if __name__ == "__main__":
    main()
