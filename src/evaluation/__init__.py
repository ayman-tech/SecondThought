"""Metrics for scoring rewrites.

    evaluation.py     the original metrics: toxicity, similarity, critical values, diagnostics.
                      Standard library only (the learned scorers load lazily).
    evaluation_v2.py  the same metrics plus the formality columns.

Import from the submodules, for example `from evaluation.evaluation import evaluate_records`.
Nothing is re-exported here, so importing the package stays cheap.
"""
