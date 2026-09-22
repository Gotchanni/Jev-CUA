import json
from pathlib import Path

import pytest

from cua_jev.cost import codex_reference_usd, codex_standard_credits, jev_model_usd


def test_published_pilot_costs_recompute_from_token_counters() -> None:
    fixture = Path(__file__).resolve().parents[1] / "benchmarks" / "v2-cost-pilot-2026-09-23.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    for item in data["jev"]["successful_hybrid_medians"].values():
        assert jev_model_usd(item["input_tokens"]) == pytest.approx(item["usd"])
    for item in data["codex"]["one_pilot_per_task"].values():
        counts = (item["input_tokens"], item["cached_input_tokens"], item["output_tokens"])
        assert codex_reference_usd(*counts) == pytest.approx(item["usd"])
        assert codex_standard_credits(*counts) == pytest.approx(item["usd"] / 0.04)


def test_codex_cost_rejects_impossible_cache_count() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        codex_reference_usd(1, 2, 0)
