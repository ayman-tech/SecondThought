# Runtime artifacts

Files the **product code loads at runtime**. Nothing here is an experiment output;
those live in `research/`.

| File | Loaded by | Made by |
| --- | --- | --- |
| `qwen2_5_0_5b_gyafc_formality_directions.pt` | `src/secondthought/steering_rewriter.py` | `research/steering_experimentation/activation_steering.ipynb` |
| `qwen2_5_0_5b_paradetox_directions.pt` | `src/secondthought/steering_rewriter.py` | `research/steering_experimentation/paradetox_hidden_states.ipynb` |

## Promoting a new version

The research notebooks write to `research/steering_experimentation/artifacts/`. These
files are **copies**, so re-running a notebook does not change what the product uses
until you promote the result on purpose:

```bash
cp research/steering_experimentation/artifacts/<file>.pt artifacts/
```

Then check that `steering_rewriter.py` still loads it, and commit both together.

Large model weights do not belong here; they go in `models/`, which is git-ignored.
