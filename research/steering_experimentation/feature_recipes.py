"""Extraction/promotion metadata; runtime routing remains catalog-driven."""

FEATURES = {
    "formality": dict(label="Formality", orientation="formal minus informal", scale="raw"),
    "detoxification": dict(label="Detoxification", orientation="neutral minus toxic", scale="unit_l2"),
    "fluency": dict(label="Fluency", orientation="revised minus original", scale="unit_l2"),
}
