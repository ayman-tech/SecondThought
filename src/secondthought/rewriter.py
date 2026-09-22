"""OpenAI-backed rewrite service."""

from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from openai import OpenAI


@dataclass(frozen=True)
class RewriteResult:
    original_text: str
    rewritten_text: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    response_id: str | None = None
    model_info: str = ""
    timestamp_utc: str = ""


class OpenAIRewriter:
    def __init__(
        self,
        *,
        model: str,
        prompt_path: str | Path,
        max_output_tokens: int = 300,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.instructions = Path(prompt_path).read_text(encoding="utf-8").strip()
        self.max_output_tokens = max_output_tokens
        self.client = client or OpenAI()

    def rewrite(self, message: str) -> RewriteResult:
        message = message.strip()
        if not message:
            raise ValueError("Message cannot be empty")

        started_at = perf_counter()
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=self.instructions,
                input=message,
                max_output_tokens=self.max_output_tokens,
                store=False,
            )
        finally:
            latency_ms = round((perf_counter() - started_at) * 1000, 2)
        rewritten = response.output_text.strip()
        if not rewritten:
            raise RuntimeError("The model returned an empty rewrite")

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        return RewriteResult(
            original_text=message,
            rewritten_text=rewritten,
            latency_ms=latency_ms,
            response_id=getattr(response, "id", None),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_info=self.model,
            timestamp_utc=datetime.now(UTC).isoformat(),
        )
