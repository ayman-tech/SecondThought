"""Protect split isolation, provenance, and all-layer fluency integration."""
import hashlib
import json
import zipfile

import pytest
import torch

from research.steering_experimentation import prepare_fluency_pairs as preparation
from research.steering_experimentation.extract_lab_vectors import load_fluency, validate_split
from secondthought.lab.catalog import get_catalog
from secondthought.lab.interventions import Intervention, compile_interventions


def row(source, target, doc, label="fluency"):
    return dict(before_sent=source, after_sent=target, doc_id=doc, labels=label)


def test_preparation_preserves_official_splits_and_removes_cross_document_duplicates(tmp_path, monkeypatch):
    archive = tmp_path / "source.zip"
    train = [row("They is working today.", "They are working today.", "a"),
             row("We was working yesterday.", "We were working yesterday.", "b"),
             row("The team are here now.", "The team is here now.", "shared"),
             row("She have arrived today.", "She has arrived today.", "c"),
             row("Keep all 42 items.", "Keep all 43 items.", "d")]
    dev = [row("She have arrived today.", "She has arrived today.", "heldout"),
           row("He have arrived today.", "He has arrived today.", "heldout2"),
           row("Another document sentence.", "A different sentence.", "shared", "clarity")]
    with zipfile.ZipFile(archive, "w") as bundle:
        for split, rows in (("train", train), ("dev", dev)):
            bundle.writestr(f"IteraTeR/human_sent_level/{split}.json",
                            "\n".join(json.dumps(r) for r in rows))
        # Test is deliberately invalid: preparation must never open it.
        bundle.writestr("IteraTeR/human_sent_level/test.json", "not json")
    monkeypatch.setattr(preparation, "SHA256", hashlib.sha256(archive.read_bytes()).hexdigest())
    output = tmp_path / "pairs.jsonl"
    _, report = preparation.prepare(archive, output)
    extraction, heldout, _ = load_fluency(output)
    validate_split(extraction, heldout)
    assert {p.group for p in extraction} == {"a", "b"}
    assert {p.group for p in heldout} == {"heldout", "heldout2"}
    assert report["counts"]["train_excluded_document_overlap"] == 1
    assert report["counts"]["train_excluded_duplicate_sentence"] == 1
    assert report["counts"]["train_excluded_number_change"] == 1
    output.write_text(output.read_text() + "\n")
    with pytest.raises(ValueError, match="checksum"):
        load_fluency(output)


def test_untrusted_archive_is_rejected(tmp_path):
    path = tmp_path / "bad.zip"
    path.write_bytes(b"untrusted")
    with pytest.raises(ValueError, match="checksum"):
        preparation.prepare(path, tmp_path / "pairs.jsonl")


def test_all_fluency_layers_poolings_and_three_feature_composition():
    catalog = get_catalog()
    entries = [v for v in catalog.spec.vectors if v.feature_id == "fluency"]
    assert {(v.layer_index, v.pooling) for v in entries} == {
        (i, p) for i in range(24) for p in ("mean", "final_token")}
    assert len(entries) == 48
    for vector in entries:
        assert catalog.vector(vector.id).shape == (896,)
        assert catalog.vector(vector.id).norm() == pytest.approx(1, abs=1e-6)
    interventions = [Intervention(vector_id=f"qwen-{f}-l7-mean-v1", strength=0.25)
                     for f in ("formality", "detoxification", "fluency")]
    compiled = compile_interventions(catalog, "qwen2.5-0.5b-instruct", interventions)
    expected = sum((catalog.vector(i.vector_id) * i.strength for i in interventions))
    assert torch.allclose(compiled[7], expected)
