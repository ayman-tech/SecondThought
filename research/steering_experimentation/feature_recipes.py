"""Extraction/promotion metadata; runtime routing remains catalog-driven."""

FEATURES = {
    "formality": dict(label="Formality", orientation="formal minus informal", scale="raw"),
    "detoxification": dict(label="Detoxification", orientation="neutral minus toxic", scale="unit_l2"),
    "fluency": dict(label="Fluency", orientation="revised minus original", scale="unit_l2"),
    "simplification": dict(label="Simplification", orientation="simple minus complex", scale="unit_l2"),
    "conciseness": dict(label="Conciseness", orientation="compressed minus original", scale="unit_l2"),
    "empathy": dict(label="Empathy", orientation="annotated response minus rationale-ablated response", scale="unit_l2"),
    "politeness": dict(label="Politeness", orientation="courtesy-bearing request minus please-ablated request", scale="unit_l2"),
}
