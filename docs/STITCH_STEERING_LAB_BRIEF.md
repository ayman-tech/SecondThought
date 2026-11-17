# Stitch prompt: SecondThought Steering Lab

Design a dedicated **Steering Lab page for SecondThought**, an experimental
platform for exploring activation steering in language models.

This is one page in a multi-page website. Navigation links go to **Home** (`/`),
**Steering Lab** (`/steering`), **Extension** (`/extension`), **Evaluation**
(`/evaluation`), and **About** (`/about`). Do not place those other pages as
sections beneath the lab.

Preserve the current design's strongest feature: a large, expressive generated-text
display that makes changes in wording easy to inspect. Use a light background,
restrained amber and cyan accents, readable typography, and a polished research-tool
aesthetic. Explore the layout creatively; avoid making the central output feel like
a small dashboard widget.

## Experiment controls

- A model selector populated by backend-supported models. Selecting a model updates
  the layer diagram and available vector combinations. The currently working model
  is Qwen2.5-0.5B-Instruct, with 24 decoder blocks numbered 0–23. The design must
  accommodate additional models without inventing availability.
- A visual, clickable stack of decoder blocks. Selecting an available layer chooses
  the intervention point. Show the selected block, vector, and residual-stream
  injection clearly. The diagram is a schematic, not a measurement of neurons,
  attention, or internal reasoning.
- A separate vector-extraction pooling control: **mean pooling** versus
  **last-token pooling**. Last-token pooling is not the last model layer. Layer,
  pooling, and alpha are distinct experiment parameters.
- Pre-extracted vectors determine availability. Disable unsupported
  model/layer/pooling combinations and explain why. Selecting a layer must not imply
  that the website can instantly create a vector for it.
- A prominent alpha slider with an immediate readout and automatic generation after
  a short pause. There is no Generate button for individual rewrites. Respect
  model-specific ranges rather than hardcoding a universal strength scale.
- System-prompt presets and a custom system-prompt editor. Show the actual prompt
  used for a result. Keep instructions separate from the source text.
- A clearly labeled source-text field with sample inputs and Clear.

## Output and comparisons

Make the large generated-text display the centerpiece. Highlight text that differs
from the **original source input**, never the previous generated output. Results
restored from cache and identical responses at different alpha values must keep
that original-input comparison.

Show the exact model, layer, pooling, prompt preset, and alpha used to produce the
displayed result. The controls may have moved ahead while generation is pending;
do not relabel an old result with the new requested settings.

Design clear states for empty input, loading the model, waiting, streaming partial
text, completed output, cancellation, busy server, and failure/retry. Previous text
may remain visible while updating, explicitly labeled as the previous result. Copy
should become available for a completed current result. Respect reduced motion.

Offer a comparison with **alpha-zero generation using the same source, model, and
system prompt**. That baseline is a model-generated rewrite, not the original input.
Secondary affordances may let users pin a configuration and compare recorded runs.

## Quantitative panel

Place a compact measurement panel beside the output. It should accommodate:

- Independent formality estimate.
- Semantic-similarity estimate.
- Entailment/preservation checks.
- Changes to protected values such as names, numbers, and dates.
- Measured generation latency.
- Optionally the measured magnitude of the intervention.

Metrics may arrive after the text. Include pending, unavailable, and error states,
and make it clear which response each measurement describes. Do not invent live
scores, reliability percentages, optimal alpha values, or guarantees of meaning
preservation. Do not collapse all measurements into a single safety/quality score.
Illustrative values in a design preview must be labeled as illustrative.

## Responsive behavior

On desktop, explore a configuration panel, central model/output workspace, and
right-side metrics. On mobile, prioritize source, output, and a reachable alpha
control; use accessible panels or tabs for advanced settings. A user adjusting
alpha should be able to see the generated response without repeatedly scrolling
between the control and output.

## Content and implementation constraints

Keep the brand open: this is a lab for experiments, without claims of enterprise
reliability or a finished B2B product. Explain that steering may change meaning and
that adjacent strengths may produce identical text. Avoid unsupported empathy or
candor objectives, fabricated benchmarks, decorative activation percentages, or
claims that stronger steering always gives better formalization.

Return an HTML/CSS design suitable for integrating with an existing Python/FastAPI
backend. Do not implement canned rewrites, regex paraphrasing, or fake model logic.
If practical retain existing control IDs `draft`, `alpha`, and `output` to simplify
integration, but prioritize a clear and usable design.

This brief describes the next lab iteration. Model/layer/pooling selectors,
editable prompts, baselines, and live learned metrics are not yet implemented in
the current website.
