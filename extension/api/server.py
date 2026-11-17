"""Local HTTP API exposing the existing rewriter to the Chrome extension.

The rewriter, config, and prompt all come from the core package; this module
only adds HTTP plumbing. By default it runs our local T5 models
(extension/api/config.toml, next to this file); set
SECONDTHOUGHT_CONFIG=config/default.toml to use OpenAI, in which case the API
key stays in the server's environment.

Run it from the repo root with `python -m extension.api.server` (or `make`).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from secondthought.cli import build_rewriter
from secondthought.config import load_settings
from evaluation.evaluation import critical_value_metrics, extract_critical_values
from secondthought.tone_check import ToneChecker

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.toml"
MAX_MESSAGE_CHARS = 4000
MAX_CHECK_LINES = 50

logger = logging.getLogger("secondthought.api")


class RewriteRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class RewriteResponse(BaseModel):
    original_text: str
    rewritten_text: str
    model_info: str
    latency_ms: float
    # Numbers, dates, amounts and the like from the message that the rewrite kept.
    kept_values: list[str] = []


class CheckRequest(BaseModel):
    lines: list[str] = Field(min_length=1, max_length=MAX_CHECK_LINES)


class LineResult(BaseModel):
    text: str
    toxicity: float
    informality: float
    toxic: bool
    informal: bool


class CheckResponse(BaseModel):
    flagged: bool
    lines: list[LineResult]
    model_info: str


def tone_check_options(config: str | Path) -> dict[str, Any]:
    """The [tone_check] section of the config; missing keys use ToneChecker's defaults."""
    try:
        with Path(config).open("rb") as handle:
            return dict(tomllib.load(handle).get("tone_check", {}))
    except OSError:
        return {"enabled": False}  # no config, no heavy models (e.g. in tests)


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


def kept_values(original: str, rewritten: str) -> list[str]:
    missing = Counter(
        value["raw"]
        for value in json.loads(critical_value_metrics(original, rewritten)["critical_value_missing"])
    )
    kept = []
    for value in extract_critical_values(original):
        if missing[value.raw]:
            missing[value.raw] -= 1
        else:
            kept.append(value.raw)
    return list(dict.fromkeys(kept))


def create_app(
    rewriter: Any | None = None,
    config_path: str | Path | None = None,
    checker: Any | None = None,
) -> FastAPI:
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

    # The tone-check classifiers take a while to load, so they load in the
    # background and /check answers 503 until they're ready.
    tone = {"checker": checker, "status": "ready" if checker else "off", "error": None}
    if checker is None:
        options = tone_check_options(config_path or os.getenv("SECONDTHOUGHT_CONFIG", DEFAULT_CONFIG))
        if options.pop("enabled", True):
            tone["status"] = "loading"

            def load_checker() -> None:
                try:
                    loaded = ToneChecker(**options)
                    loaded.check(["warm up"])  # the first call is slow; don't make the user wait for it
                    tone["checker"] = loaded
                    tone["status"] = "ready"
                except Exception as exc:
                    tone["status"] = "error"
                    tone["error"] = f"{type(exc).__name__}: {exc}"
                    logger.error("Tone checker could not be created: %s", tone["error"])

            threading.Thread(target=load_checker, daemon=True).start()

    @app.get("/health")
    def health() -> dict[str, Any]:
        if rewriter is None:
            return {"status": "error", "detail": setup_error}
        return {"status": "ok", "model": getattr(rewriter, "model", ""), "tone_check": tone["status"]}

    @app.post("/check", response_model=CheckResponse)
    def check(request: CheckRequest) -> CheckResponse:
        if tone["status"] != "ready":
            detail = {
                "loading": "The tone check is still starting up. Try again in a moment.",
                "off": "The tone check is turned off in the server config.",
                "error": f"The tone check couldn't start. {tone['error']}",
            }[tone["status"]]
            raise HTTPException(503, detail)
        lines = [line for line in request.lines if line.strip()]
        if not lines:
            raise HTTPException(400, "Nothing to check")
        if any(len(line) > MAX_MESSAGE_CHARS for line in lines):
            raise HTTPException(400, f"Lines must be at most {MAX_MESSAGE_CHARS} characters")
        results = tone["checker"].check(lines)
        return CheckResponse(
            flagged=any(result.toxic or result.informal for result in results),
            lines=[LineResult(**vars(result)) for result in results],
            model_info=tone["checker"].model,
        )

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
            kept_values=kept_values(result.original_text, result.rewritten_text),
        )

    return app


app = create_app()


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
