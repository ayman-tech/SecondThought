"""Minimal Gradio interface for real-user baseline testing."""

from __future__ import annotations

import gradio as gr

from .cli import build_rewriter
from .config import load_settings


def create_app(config_path: str = "config/default.toml") -> gr.Interface:
    rewriter = build_rewriter(load_settings(config_path))

    def rewrite_message(message: str) -> str:
        return rewriter.rewrite(message).rewritten_text

    return gr.Interface(
        fn=rewrite_message,
        inputs=gr.Textbox(lines=5, label="Original message"),
        outputs=gr.Textbox(lines=5, label="Suggested rewrite"),
        title="SecondThought",
        description=(
            "Rewrite a difficult workplace message professionally while preserving "
            "its criticism, urgency, facts, and requested actions."
        ),
        flagging_mode="manual",
        flagging_options=["Good rewrite", "Meaning changed", "Still unprofessional"],
    )


def main() -> None:
    create_app().launch()


if __name__ == "__main__":
    main()
