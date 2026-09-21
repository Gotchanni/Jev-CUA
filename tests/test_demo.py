from cua_jev.demo import filesystem_routing_demo
from cua_jev.policy import RulePolicy


def test_demo_is_reproducible(tmp_path):
    result = filesystem_routing_demo(RulePolicy(), tmp_path, tmp_path / "trace.jsonl")
    assert result.decision.candidate_id == "mcp_read"
    assert result.verification.passed
    assert "region,revenue" in result.receipt.output["text"]
