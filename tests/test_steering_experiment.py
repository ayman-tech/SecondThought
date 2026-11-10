from __future__ import annotations

import torch

from secondthought.steering_experiment import (
    TextPair,
    clean_generation,
    make_steering_hook,
    parse_candidate_name,
    stratified_split,
    summarize_outputs,
)

from steering_experimentation.run_experiment import parser


def test_stratified_split_is_balanced_disjoint_and_reproducible() -> None:
    pairs = [TextPair(f"s{i}", f"t{i}", f"g{i % 2}", str(i)) for i in range(20)]
    first = stratified_split(pairs, extraction_pairs=8, heldout_pairs=4, seed=42)
    second = stratified_split(pairs, extraction_pairs=8, heldout_pairs=4, seed=42)
    assert first == second
    extraction, heldout = first
    assert {pair.row_id for pair in extraction}.isdisjoint(pair.row_id for pair in heldout)
    assert {group: sum(pair.group == group for pair in extraction) for group in ("g0", "g1")} == {"g0": 4, "g1": 4}


def test_steering_hook_uses_raw_alpha_scaled_delta() -> None:
    hook = make_steering_hook(torch.tensor([1.0, -2.0]), 2.0)
    residual = torch.zeros((1, 2, 2))
    modified, tail = hook(None, (), (residual, "cache"))
    assert torch.equal(modified, torch.tensor([[[2.0, -4.0], [2.0, -4.0]]]))
    assert tail == "cache"


def test_candidate_names_and_summary() -> None:
    assert parse_candidate_name("layer12_final_token") == (12, "final_token")
    rows = [
        {"alpha": 1.0, "word_length_ratio": 1.0, "word_set_jaccard": 0.5, "contraction_count": 1, "slang_count": 0, "exclamation_count": 0, "word_overlap": 0.5, "edit_ratio": 0.5, "number_recall": 1.0, "critical_value_recall": 1.0, "critical_value_exact": True, "critical_value_missing_count": 0, "critical_value_unsupported_count": 0, "exact_copy": False, "empty_output": False},
        {"alpha": 2.0, "word_length_ratio": 2.0, "word_set_jaccard": 0.2, "contraction_count": 0, "slang_count": 0, "exclamation_count": 0, "word_overlap": 0.2, "edit_ratio": 0.8, "number_recall": 0.5, "critical_value_recall": 0.5, "critical_value_exact": False, "critical_value_missing_count": 1, "critical_value_unsupported_count": 0, "exact_copy": False, "empty_output": False},
    ]
    assert [row["alpha"] for row in summarize_outputs(rows)] == [1.0, 2.0]


def test_clean_generation_stops_before_next_few_shot_example() -> None:
    assert clean_generation("A cleaner rewrite.\n\nInput: another example") == "A cleaner rewrite."


def test_cli_accepts_generation_candidate_override() -> None:
    args = parser().parse_args(
        [
            "--model", "test/model",
            "--dataset-loader", "file",
            "--dataset", "pairs.csv",
            "--artifact", "directions.pt",
            "--candidate-report", "candidates.csv",
            "--candidate", "layer16_final_token",
        ]
    )
    assert args.candidate == "layer16_final_token"

