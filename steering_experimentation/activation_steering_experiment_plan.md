# Activation Steering Experiment — Initial Research Plan

## Purpose

This experiment has **two equally important objectives**.

### Research objective

Test whether **formality is represented as a sufficiently coherent direction in a language model's activation space** that we can identify that direction from GYAFC and use it to steer generation toward more formal language at inference time.

The initial hypothesis is:

> Paired informal/formal sentences in GYAFC induce a repeatable difference in hidden-state representations. If that difference is sufficiently coherent across examples, a steering direction can be estimated and added to model activations to increase output formality without destroying semantic content.

This hypothesis must be tested rather than assumed.

### Learning objective

Use the experiment to become comfortable working directly with open-source language models instead of treating the model as a black box.

The experiment should deliberately provide hands-on experience with:

- loading and running open-source models
- understanding tokenization and generation
- examining model architecture
- using datasets from raw files through preprocessing
- inspecting hidden states
- working with PyTorch tensors and model hooks
- understanding layers and residual representations
- extracting and analyzing activation vectors
- modifying activations during inference
- designing controlled experiments
- diagnosing failures rather than immediately replacing the approach

Codex should support this process, but should **not hide the important mechanics behind a large automated pipeline**.

---

# Central Research Question

> Does a meaningful and controllable formality direction exist in the hidden activation space of an open-source language model?

If it does:

> Can moving model activations along that direction produce increasingly formal text while preserving the original meaning?

The experiment should remain useful even if the answer to the first question is "not as a single linear direction."

That would itself tell us something about how formality is represented.

---

# Experimental Philosophy

Do not begin by implementing activation steering.

The experiment should move through the following sequence:

```text
Understand the dataset
        ↓
Understand the model
        ↓
Observe its hidden representations
        ↓
Form a precise representation hypothesis
        ↓
Extract candidate formality directions
        ↓
Test whether those directions are real
        ↓
Only then intervene on generation
        ↓
Evaluate controllability and trade-offs
```

Each stage should leave behind interpretable artifacts such as plots, examples, vectors, notebooks, or measurements.

---

# Step 1 — Understand GYAFC Before Using It

GYAFC is the primary dataset for this experiment because it contains paired informal and formal rewrites.

Before extracting any activations:

- inspect the dataset structure
- understand the two GYAFC domains
- inspect paired informal/formal examples manually
- examine sentence length and token-length differences
- identify transformations commonly associated with formality
- look for noisy or semantically mismatched pairs
- understand train / validation / test organization
- decide what subset is appropriate for vector extraction and what must remain held out

The important question is not only:

> How much data do we have?

but:

> What linguistic changes does this dataset actually call "formality"?

Examples may involve changes in:

- contractions
- slang
- politeness
- punctuation
- spelling
- vocabulary
- sentence structure
- explicitness
- verbosity

This matters because a vector learned from GYAFC may represent some mixture of these properties rather than an abstract universal notion of formality.

**Deliverable:** a short exploratory notebook and a written description of what "formalization" looks like in GYAFC.

---

# Step 2 — Choose the Model Deliberately

Do not automatically use the existing T5 model.

T5 remains useful as the **fine-tuning baseline**, but the steering experiment should use a model that makes hidden-state inspection and intervention straightforward.

Prefer initially:

- a small open-weight Transformer
- a decoder-only architecture
- a model that runs comfortably on available hardware
- standard Hugging Face support
- easy access to hidden states
- an architecture that can be inspected without specialized infrastructure

The choice should be made only after understanding:

- residual stream shape
- number of layers
- hidden dimension
- tokenizer behavior
- generation API
- where an intervention can be inserted

The first model does not need to be powerful. It needs to be **understandable and experimentally manageable**.

**Decision point:** select one model and document why it was chosen.

---

# Step 3 — Learn the Model Before Steering It

Before extracting a formality vector, manually trace a small batch through the model.

Be able to answer:

- What does the tokenizer produce?
- What is the tensor shape entering the model?
- How many Transformer layers are there?
- What is the hidden-state dimension?
- What hidden states are returned?
- What does one layer output look like?
- Which tensor would we actually modify during steering?
- During generation, when and where would that modification occur?

Use simple experiments and visual inspection.

Avoid introducing abstraction libraries until the underlying Hugging Face / PyTorch mechanism is understood.

**Deliverable:** a small notebook that loads the model, generates text, captures hidden states, and explains their shapes.

---

# Step 4 — Define the Representation Hypothesis

For a GYAFC pair:

```text
informal_i
formal_i
```

extract representations from the same model layer:

```text
h_informal_i
h_formal_i
```

The initial candidate difference is:

```text
delta_i = h_formal_i - h_informal_i
```

The simplest candidate formality direction at layer `l` is:

```text
v_formal_l = mean(delta_i)
```

Do not assume this average is meaningful.

The next stage exists specifically to test that assumption.

Important choices to make consciously:

- which token representation to use
- whether to mean-pool tokens or examine specific token positions
- which layer(s) to study
- how variable-length paired sentences should be represented
- whether vectors should be normalized

Codex may help implement these alternatives, but the choices should remain visible and interpretable.

---

# Step 5 — Ask Whether a Formality Direction Actually Exists

Before using the vector for generation, analyze its geometry.

For each layer, investigate whether formal and informal examples separate along the candidate direction.

Questions to test:

### Pairwise direction consistency

Do individual vectors

```text
delta_i = h_formal_i - h_informal_i
```

roughly point in a common direction?

Measure similarity between individual `delta_i` vectors and the aggregate direction.

If the vectors point in unrelated directions, averaging them may not represent anything useful.

### Held-out separation

For unseen GYAFC pairs, project the formal and informal activations onto the candidate direction.

A useful direction should tend to satisfy:

```text
projection(formal) > projection(informal)
```

on held-out data.

### Layer dependence

Repeat the analysis across layers.

The goal is to discover where, if anywhere, formality becomes geometrically separable.

### Visualization

Use simple PCA / dimensionality-reduction plots only as supporting evidence.

Do not mistake a visually pleasing 2-D projection for proof of a meaningful representation.

**Decision point:** determine whether there is enough evidence for a coherent linear formality direction to justify intervention.

---

# Step 6 — Compare Ways of Extracting the Direction

Only after establishing the basic difference-of-means baseline should we consider alternatives.

Candidate methods:

1. **Mean paired activation difference**
2. **Principal direction of paired difference vectors**
3. **Linear probe separating formal and informal representations**

The purpose is not to accumulate methods.

The purpose is to answer:

> Is the discovered direction robust to how we estimate it?

If all approaches identify similar directions, that is stronger evidence.

If they disagree strongly, investigate why before moving on.

---

# Step 7 — Perform Activation Steering

Once a credible layer and direction have been identified, intervene during inference.

Conceptually:

```text
h_steered = h + alpha * v_formal
```

where `alpha` controls steering strength.

Start with a small sweep around zero, including:

```text
negative alpha
zero
positive alpha
```

The experiment should examine whether formality changes **continuously** with steering strength.

The key observation is not merely:

> Did steering work?

but:

> What changes as we move along the direction?

Inspect:

- style
- vocabulary
- syntax
- semantic preservation
- fluency
- repetition
- verbosity
- degeneration at large steering strengths

---

# Step 8 — Compare Against Baselines

The steering result should not be evaluated in isolation.

At minimum compare:

### No intervention

Normal generation from the selected model.

### Prompt-based control

Ask the model explicitly to rewrite formally.

### Fine-tuned approach

Use the existing supervised style-transfer approach as the conventional baseline.

### Activation steering

Use the extracted formality vector.

If useful later:

### Fine-tuning + steering

Test whether steering can provide adjustable formality on top of a model already trained for rewriting.

This comparison distinguishes:

```text
learning the transformation in the weights
```

from:

```text
controlling an existing representation at inference time
```

---

# Step 9 — Evaluate the Steering Trade-off

Reuse the evaluation philosophy already established for the project.

For formality steering, focus on:

- **formality/style score**
- **semantic similarity**
- **fluency**
- **reference similarity against GYAFC rewrites**
- **exact-copy rate**
- qualitative inspection

The most important experiment is the relationship between steering strength and these metrics.

Conceptually:

```text
alpha ↑
    formality may ↑
    semantic preservation may ↓
    fluency may eventually ↓
```

The objective is therefore not necessarily to find the maximum possible formality score.

It is to understand the **control frontier** between style change and content preservation.

---

# Step 10 — Interpret the Result Before Extending the Project

Possible outcomes:

### Outcome A — A strong linear direction exists

Formality reliably separates along one or more layers and steering produces controlled changes.

Next questions could include:

- how transferable is the vector?
- can it be combined with detoxification?
- can multiple style directions be composed?

### Outcome B — A weak but useful direction exists

Steering works only for certain layers, examples, or alpha ranges.

Investigate what linguistic properties the vector is actually encoding.

### Outcome C — No stable single direction exists

Do not treat this as failure.

Investigate whether formality is:

- multidimensional
- represented non-linearly
- distributed across layers
- entangled with politeness, verbosity, syntax, or lexical choice

This may motivate multi-vector or subspace approaches rather than one "north pole."

---

# Working Agreement With Codex

Codex should help with implementation while preserving the learning objective.

Prefer:

```text
small notebooks
small functions
explicit tensor shapes
visible intermediate values
plots that answer one question
short experimental scripts
```

Avoid initially:

```text
one-click end-to-end pipelines
large opaque frameworks
automatic experiment generation
premature abstractions
large-scale hyperparameter searches
code that modifies activations without showing where the hook is placed
```

When introducing an unfamiliar mechanism, the code should make it possible to inspect:

```text
input
→ activation before intervention
→ steering vector
→ activation after intervention
→ generated output
```

The aim is for the experimenter to understand and control every important transformation.

---

# Papers and References

## Essential: Dataset and Text Style Transfer

### Rao & Tetreault (2018) — GYAFC

**Dear Sir or Madam, May I Introduce the GYAFC Dataset: Corpus, Benchmarks and Metrics for Formality Style Transfer**

Introduces GYAFC and discusses the formality-transfer task, benchmarks, and evaluation issues.

https://aclanthology.org/N18-1012/

Read this before making assumptions about what the dataset represents.

---

## Essential: Basic Activation Steering

### Turner et al. — Activation Addition

**Activation Addition: Steering Language Models Without Optimization**

Introduces Activation Addition (ActAdd): derive activation differences from contrasting prompts and add the resulting vector during inference.

https://arxiv.org/abs/2308.10248

Useful for understanding the fundamental `h + alpha*v` intervention idea.

---

### Rimsky et al. (ACL 2024) — Contrastive Activation Addition

**Steering Llama 2 via Contrastive Activation Addition**

CAA estimates a steering vector by averaging activation differences between paired positive and negative behavioral examples and applies the direction during generation.

https://aclanthology.org/2024.acl-long.828/

This is one of the most directly relevant papers for the proposed paired-GYAFC experiment.

---

## Essential: Style Steering

### Konen et al. (EACL 2024 Findings)

**Style Vectors for Steering Generative Large Language Models**

Directly studies style vectors derived from hidden-layer activations and uses them for parameterizable control of generated style.

https://aclanthology.org/2024.findings-eacl.52/

This is likely the closest conceptual reference to the experiment.

---

### Lai, Hangya & Fraser (EMNLP 2024)

**Style-Specific Neurons for Steering LLMs in Text Style Transfer**

Studies activation/neuron-level control for text style transfer and evaluates dimensions including formality, toxicity, politeness, authorship, sentiment, and politics.

https://aclanthology.org/2024.emnlp-main.745/

Particularly useful for understanding that style intervention can also damage fluency.

---

## Background: Latent Steering Spaces

### Subramani, Suresh & Peters (ACL Findings 2022)

**Extracting Latent Steering Vectors from Pretrained Language Models**

Investigates latent steering vectors inside pretrained language models and demonstrates vector arithmetic and sentiment transfer.

https://aclanthology.org/2022.findings-acl.48/

Useful for the broader idea that useful control directions may already exist inside a frozen model.

---

## Background: Representation Engineering

### Zou et al. (2023)

**Representation Engineering: A Top-Down Approach to AI Transparency**

Presents representation engineering as the study and manipulation of high-level concepts represented in model activations.

https://arxiv.org/abs/2310.01405

Useful for thinking beyond individual neurons and treating concepts as population-level representations.

---

## Related Intervention Method

### Li et al. (NeurIPS 2023)

**Inference-Time Intervention: Eliciting Truthful Answers from a Language Model**

Identifies activation directions associated with truthfulness and intervenes on selected attention-head activations at inference time.

https://papers.nips.cc/paper_files/paper/2023/hash/81b8390039b7302c909cb769f8b6cd93-Abstract-Conference.html

Useful as another example of discovering a latent property first and intervening only after establishing that it is represented.

---

## Model Background

If T5 remains part of the comparison:

### Raffel et al. (2020)

**Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer**

https://jmlr.org/papers/v21/20-074.html

Use this mainly to understand the architecture and why activation intervention in an encoder-decoder model differs from steering a decoder-only residual stream.

---

# Initial Definition of Success

This experiment is successful if, by the end, we can answer these questions with evidence:

1. What does GYAFC actually encode as "formality"?
2. Where in the chosen model can formal and informal representations be distinguished?
3. Are paired formalization differences geometrically coherent?
4. Can a candidate direction causally influence generated style?
5. How does steering strength trade off against semantic preservation and fluency?
6. How does steering compare with prompting and fine-tuning?
7. What did we learn about manipulating an open-source model that would let us independently investigate the next idea?

The objective is not merely to produce a formal sentence.

The objective is to understand enough of the model and its representation space that the result—successful or unsuccessful—is explainable.
