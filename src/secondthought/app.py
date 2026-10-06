"""Compact Gradio workbench for comparing activation-steered rewrites."""

from __future__ import annotations

from typing import Protocol

import gradio as gr

from .steering_rewriter import STEERING_VARIANTS, SteeredQwenRewriter


class Rewriter(Protocol):
    def rewrite_all(self, message: str, alpha: float) -> dict[str, str]: ...


APP_CSS = """
:root {
  --st-page: #fafafa;
  --st-panel: #ffffff;
  --st-recessed: #f8fafc;
  --st-border: #e2e8f0;
  --st-border-active: #cbd5e1;
  --st-ink: #0f172a;
  --st-text: #334155;
  --st-muted: #64748b;
  --st-faint: #94a3b8;
  --st-orange: #ea580c;
  --st-orange-hover: #c2410c;
  --st-orange-soft: #fff7ed;
  --st-green: #10b981;
}

html, body { height: 100%; overflow: hidden; background: var(--st-page); }
body { margin: 0; }
.gradio-container {
  width: 100% !important;
  max-width: none !important;
  height: 100vh !important;
  min-height: 700px !important;
  overflow: hidden !important;
  padding: 0 !important;
  background: var(--st-page) !important;
  color: var(--st-ink) !important;
  font-family: Geist, Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
}
.gradio-container .main,
.gradio-container main {
  width: 100% !important;
  max-width: none !important;
  height: 100% !important;
  margin: 0 !important;
  padding: 0 !important;
  gap: 0 !important;
}
.gradio-container .contain > .column { gap: 0 !important; }
.gradio-container .wrap { max-width: none !important; }
footer { display: none !important; }

#topbar {
  height: 48px;
  border-bottom: 1px solid var(--st-border);
  background: rgba(255, 255, 255, 0.92);
}
.topbar-inner {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
}
.brand-line, .header-right { display: flex; align-items: center; }
.brand-line { gap: 10px; }
.brand-dot { width: 8px; height: 8px; border-radius: 999px; background: var(--st-orange); }
.brand-name { color: var(--st-ink); font-size: 14px; font-weight: 600; letter-spacing: -0.01em; }
.header-divider { color: #d4d4d8; font-weight: 300; }
.product-area { color: #a1a1aa; font-size: 12px; }
.model-name { color: #a1a1aa; font: 10px ui-monospace, SFMono-Regular, Menlo, monospace; }
.header-right { gap: 22px; }
.active-view { color: #18181b; font-size: 12px; font-weight: 500; }
.ready-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  background: #f4f4f5;
  color: #71717a;
  font: 10px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.ready-dot { width: 6px; height: 6px; border-radius: 999px; background: var(--st-green); }

#workbench {
  box-sizing: border-box;
  width: min(100%, 1440px);
  height: calc(100vh - 48px);
  margin: 0 auto;
  padding: 20px 28px;
  gap: 24px;
  flex-wrap: nowrap;
  overflow: hidden;
}
#controls-column {
  display: grid !important;
  grid-template-rows: minmax(0, 1fr) 198px;
  width: 36%;
  min-width: 320px;
  height: 100%;
  gap: 16px;
}
#outputs-column {
  display: grid !important;
  grid-template-rows: 28px minmax(0, 1fr) minmax(0, 1fr);
  width: 64%;
  min-width: 0;
  height: 100%;
  gap: 12px;
}

.st-panel {
  min-height: 0;
  border: 1px solid var(--st-border) !important;
  border-radius: 8px !important;
  background: var(--st-panel) !important;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04) !important;
  overflow: hidden;
}
#source-panel, #control-panel, .response-card {
  display: flex !important;
  flex-direction: column !important;
}
.panel-heading, .card-heading, .output-toolbar, .control-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.panel-heading {
  flex: 0 0 40px;
  min-height: 40px;
  margin: 0 16px;
  border-bottom: 1px solid #f1f5f9;
}
.panel-kicker, .output-kicker {
  color: #52525b;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.panel-note { color: #a1a1aa; font-size: 11px; }

#source-input {
  flex: 1 1 auto;
  min-height: 0;
  padding: 0 16px 10px !important;
  border: 0 !important;
  background: var(--st-panel) !important;
}
#source-input > div, #source-input > label, #source-input label, #source-input .wrap {
  height: 100% !important;
  min-height: 0 !important;
}
#source-input textarea {
  height: 100% !important;
  min-height: 0 !important;
  resize: none !important;
  border: 0 !important;
  border-radius: 0 !important;
  background: var(--st-panel) !important;
  color: #27272a !important;
  padding: 13px 0 !important;
  font: 13.5px/1.6 Geist, Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
  box-shadow: none !important;
}
#source-input textarea:focus { box-shadow: none !important; }
#source-input textarea::placeholder { color: #d4d4d8; }

#control-panel { padding: 14px 16px !important; gap: 10px; }
.control-heading { min-height: 22px; }
.control-title { color: #3f3f46; font-size: 12px; font-weight: 500; }
.alpha-readout { margin-left: 7px; color: #a1a1aa; font: 10px ui-monospace, SFMono-Regular, Menlo, monospace; }
.layer-note { color: #a1a1aa; font: 9px ui-monospace, SFMono-Regular, Menlo, monospace; }
#alpha-slider { padding: 0 !important; border: 0 !important; background: transparent !important; }
#alpha-slider input[type="range"] { accent-color: var(--st-orange); }
#alpha-guide {
  min-height: 25px;
  padding: 6px 0;
  border-top: 1px solid #f1f5f9;
  border-bottom: 1px solid #f1f5f9;
}
#alpha-guide p { margin: 0; color: #71717a; font-size: 10px; line-height: 1.3; }
.warning { color: #b45309; font-weight: 600; }
#action-row { gap: 8px; }
#reset-button, #generate-button { min-height: 34px; border-radius: 5px !important; font-size: 11px; font-weight: 600; }
#reset-button { max-width: 72px; border-color: var(--st-border) !important; background: white !important; color: #52525b !important; }
#generate-button { border: 0 !important; background: var(--st-orange) !important; color: white !important; }
#generate-button:hover { background: var(--st-orange-hover) !important; }

#output-toolbar { padding: 0 !important; border: 0 !important; background: transparent !important; box-shadow: none !important; }
.output-toolbar { width: 100%; height: 100%; }
.output-context { display: flex; align-items: center; gap: 9px; }
.toolbar-divider { color: #d4d4d8; }
.output-description { color: #a1a1aa; font-size: 11px; }
.alpha-chip {
  padding: 3px 7px;
  border: 1px solid #fed7aa;
  border-radius: 5px;
  background: var(--st-orange-soft);
  color: var(--st-orange-hover);
  font: 10px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.response-card { height: 100%; padding: 0 16px !important; }
.card-heading {
  flex: 0 0 40px;
  min-height: 40px;
  border-bottom: 1px solid #f1f5f9;
}
.card-identity { display: flex; align-items: center; gap: 8px; }
.response-label { color: var(--st-ink); font: 600 10px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: 0.05em; }
.card-divider { color: #d4d4d8; }
.method-name { color: #71717a; font-size: 11px; }
.direction-label { color: #a1a1aa; font: 9px ui-monospace, SFMono-Regular, Menlo, monospace; }
.response-output {
  flex: 1 1 auto;
  min-height: 0;
  padding: 0 !important;
  border: 0 !important;
  background: white !important;
  opacity: 1 !important;
}
.response-output > div, .response-output > label,
.response-output label, .response-output .wrap {
  height: 100% !important;
  min-height: 0 !important;
}
.response-output textarea,
.response-output textarea:disabled {
  height: 100% !important;
  min-height: 0 !important;
  resize: none !important;
  border: 0 !important;
  border-radius: 0 !important;
  background: white !important;
  color: #27272a !important;
  -webkit-text-fill-color: #27272a !important;
  opacity: 1 !important;
  padding: 14px 0 !important;
  font: 14px/1.6 Geist, Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
  box-shadow: none !important;
}
.response-output textarea::placeholder { color: #d4d4d8; -webkit-text-fill-color: #d4d4d8; }

@media (max-width: 850px) {
  html, body { overflow: auto; }
  .gradio-container { height: auto !important; min-height: 100vh !important; overflow: auto !important; }
  #workbench { height: auto; min-height: 0; padding: 16px; flex-wrap: wrap; overflow: visible; }
  #controls-column, #outputs-column { display: flex !important; width: 100%; min-width: 0; height: auto; }
  #source-panel { min-height: 360px; }
  #control-panel { min-height: 198px; }
  .response-card { min-height: 280px; }
  .header-right .active-view, .model-name, .panel-note, .direction-label { display: none; }
}
"""


APP_THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.orange,
    neutral_hue=gr.themes.colors.zinc,
).set(
    body_background_fill="#fafafa",
    body_text_color="#0f172a",
    body_text_color_subdued="#64748b",
    block_background_fill="#ffffff",
    block_border_color="#e2e8f0",
    input_background_fill="#ffffff",
    input_border_color="#e2e8f0",
    slider_color="#ea580c",
    button_primary_background_fill="#ea580c",
    button_primary_background_fill_hover="#c2410c",
)


def alpha_guidance(alpha: float) -> str:
    alpha = float(alpha)
    if alpha < 0:
        return "**Conversational region** · stays closer to the source wording."
    if alpha == 0:
        return "**Unsteered rewrite baseline** · no activation vector is applied."
    if alpha <= 0.5:
        return "**Light steering** · conservative formalization."
    if alpha <= 1.0:
        return "**Strong steering** · clearer style shift; verify the meaning."
    return (
        '<span class="warning">⚠ Experimental region · strong steering can alter '
        "or invent context.</span>"
    )


def output_toolbar(alpha: float) -> str:
    return (
        '<div class="output-toolbar">'
        '<div class="output-context">'
        '<span class="output-kicker">Steering outputs</span>'
        '<span class="toolbar-divider">·</span>'
        '<span class="output-description">Dual layer comparison</span>'
        "</div>"
        f'<span class="alpha-chip">α {float(alpha):+.1f}</span>'
        "</div>"
    )


def create_app(rewriter: Rewriter | None = None) -> gr.Blocks:
    """Build the functional subset of the Stitch comparison workbench."""

    service = rewriter or SteeredQwenRewriter()

    def generate(message: str, alpha: float):
        try:
            responses = service.rewrite_all(message, alpha)
        except ValueError as error:
            raise gr.Error(str(error)) from error
        return tuple(responses[variant.key] for variant in STEERING_VARIANTS)

    def update_alpha(alpha: float):
        return alpha_guidance(alpha), output_toolbar(alpha)

    with gr.Blocks(
        theme=APP_THEME,
        title="SecondThought Steering Lab",
        css=APP_CSS,
        fill_height=True,
        fill_width=True,
    ) as demo:
        gr.HTML(
            """
            <div class="topbar-inner">
              <div class="brand-line">
                <span class="brand-dot"></span>
                <span class="brand-name">SecondThought</span>
                <span class="header-divider">/</span>
                <span class="product-area">Steering Lab</span>
                <span class="header-divider">·</span>
                <span class="model-name">Qwen 2.5 0.5B</span>
              </div>
              <div class="header-right">
                <span class="active-view">Activation Steering</span>
                <span class="ready-pill"><span class="ready-dot"></span>Ready</span>
              </div>
            </div>
            """,
            elem_id="topbar",
            padding=False,
        )

        with gr.Row(elem_id="workbench"):
            with gr.Column(scale=36, elem_id="controls-column"):
                with gr.Column(elem_id="source-panel", elem_classes=["st-panel"]):
                    gr.HTML(
                        """
                        <div class="panel-heading">
                          <span class="panel-kicker">Source prompt</span>
                          <span class="panel-note">Same input · two directions</span>
                        </div>
                        """,
                        padding=False,
                    )
                    message = gr.Textbox(
                        placeholder="Type a sentence to rewrite…",
                        lines=12,
                        max_lines=16,
                        show_label=False,
                        container=False,
                        elem_id="source-input",
                    )

                with gr.Column(elem_id="control-panel", elem_classes=["st-panel"]):
                    gr.HTML(
                        """
                        <div class="control-heading">
                          <span class="control-title">Formality strength <span class="alpha-readout">−2.0 TO +2.0</span></span>
                          <span class="layer-note">LAYER 4 / 11</span>
                        </div>
                        """,
                        padding=False,
                    )
                    alpha = gr.Slider(
                        minimum=-2.0,
                        maximum=2.0,
                        value=0.5,
                        step=0.5,
                        show_label=False,
                        container=False,
                        elem_id="alpha-slider",
                    )
                    guide = gr.Markdown(
                        alpha_guidance(0.5),
                        elem_id="alpha-guide",
                        container=False,
                    )
                    with gr.Row(elem_id="action-row"):
                        clear = gr.Button("Reset", elem_id="reset-button")
                        generate_button = gr.Button(
                            "Generate rewrites",
                            variant="primary",
                            elem_id="generate-button",
                        )

            with gr.Column(scale=64, elem_id="outputs-column"):
                toolbar = gr.HTML(
                    output_toolbar(0.5),
                    elem_id="output-toolbar",
                    padding=False,
                )

                response_outputs = []
                for index, variant in enumerate(STEERING_VARIANTS):
                    response_letter = chr(ord("A") + index)
                    extraction = (
                        "FINAL-TOKEN DIRECTION"
                        if "final" in variant.key
                        else "MEAN-POOLED DIRECTION"
                    )
                    layer_name = "Layer 4 steering" if index == 0 else "Layer 11 steering"
                    with gr.Column(elem_classes=["st-panel", "response-card"]):
                        gr.HTML(
                            f"""
                            <div class="card-heading">
                              <div class="card-identity">
                                <span class="response-label">RESPONSE {response_letter}</span>
                                <span class="card-divider">·</span>
                                <span class="method-name">{layer_name}</span>
                              </div>
                              <span class="direction-label">{extraction}</span>
                            </div>
                            """,
                            padding=False,
                        )
                        response_outputs.append(
                            gr.Textbox(
                                placeholder="Generated response will appear here.",
                                lines=6,
                                max_lines=9,
                                show_label=False,
                                container=False,
                                interactive=False,
                                show_copy_button=True,
                                elem_classes=["response-output"],
                            )
                        )

        alpha.change(
            update_alpha,
            inputs=alpha,
            outputs=[guide, toolbar],
            queue=False,
        )
        generate_button.click(
            generate,
            inputs=[message, alpha],
            outputs=response_outputs,
            concurrency_limit=1,
            concurrency_id="steering-generation",
        )
        message.submit(
            generate,
            inputs=[message, alpha],
            outputs=response_outputs,
            concurrency_limit=1,
            concurrency_id="steering-generation",
        )
        clear.click(
            lambda: (
                "",
                0.5,
                alpha_guidance(0.5),
                output_toolbar(0.5),
                "",
                "",
            ),
            outputs=[
                message,
                alpha,
                guide,
                toolbar,
                *response_outputs,
            ],
            queue=False,
        )

    return demo.queue(default_concurrency_limit=1)


def main() -> None:
    create_app().launch()


if __name__ == "__main__":
    main()
