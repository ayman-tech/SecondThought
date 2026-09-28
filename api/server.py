"""Local HTTP API exposing the existing rewriter to the Chrome extension.

The rewriter, config, and prompt all come from the core package; this module
only adds HTTP plumbing. The API key stays in the server's environment.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from secondthought.cli import build_rewriter
from secondthought.config import load_settings

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "default.toml"
MAX_MESSAGE_CHARS = 4000

logger = logging.getLogger("secondthought.api")


class RewriteRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class RewriteResponse(BaseModel):
    original_text: str
    rewritten_text: str
    model_info: str
    latency_ms: float


def load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from a local .env without overriding the shell."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip().strip("'\"")
        if key and value:
            os.environ.setdefault(key, value)


def create_app(rewriter: Any | None = None, config_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="SecondThought API")
    # Only Chrome extension pages may call this from a browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    setup_error: str | None = None
    if rewriter is None:
        try:
            load_dotenv(REPO_ROOT / ".env")
            config = config_path or os.getenv("SECONDTHOUGHT_CONFIG", DEFAULT_CONFIG)
            rewriter = build_rewriter(load_settings(config))
        except Exception as exc:  # reported via /health and /rewrite
            setup_error = f"{type(exc).__name__}: {exc}"
            logger.error("Rewriter could not be created: %s", setup_error)

    @app.get("/health")
    def health() -> dict[str, Any]:
        if rewriter is None:
            return {"status": "error", "detail": setup_error}
        return {"status": "ok", "model": getattr(rewriter, "model", "")}

    @app.post("/rewrite", response_model=RewriteResponse)
    def rewrite(request: RewriteRequest) -> RewriteResponse:
        if rewriter is None:
            raise HTTPException(503, f"Rewriter is not configured. {setup_error}")
        try:
            result = rewriter.rewrite(request.message)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc
        except Exception as exc:
            logger.exception("Rewrite failed")
            if getattr(exc, "status_code", None) == 401:
                detail = "The model provider rejected the API key. Check OPENAI_API_KEY on the server."
            else:
                detail = f"The model provider returned an error ({type(exc).__name__}). See server logs."
            raise HTTPException(502, detail) from exc
        return RewriteResponse(
            original_text=result.original_text,
            rewritten_text=result.rewritten_text,
            model_info=result.model_info,
            latency_ms=result.latency_ms,
        )

    return app


app = create_app()


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
