import httpx
import pytest

from cua_jev.errors import PolicyError
from cua_jev.models import ActionCandidate, Channel, Observation
from cua_jev.policy import JevPolicy, RulePolicy


def candidates():
    return [
        ActionCandidate("gui", Channel.GUI, "uia.invoke", "Click a button"),
        ActionCandidate("mcp", Channel.MCP, "mcp.filesystem.read", "Read with MCP"),
    ]


def test_rule_policy_prefers_structured_read_only_channel():
    obs = Observation("read", "read file", {})
    assert RulePolicy().choose(obs, candidates()).candidate_id == "mcp"


def test_jev_policy_validates_and_returns_choice():
    def handler(request):
        assert "secret" not in request.content.decode()
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "action": {
                        "choice": "mcp",
                        "probabilities": {"gui": 0.1, "mcp": 0.9},
                        "confidence": 0.8,
                    }
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    policy = JevPolicy(api_key="secret", client=client, retries=0)
    decision = policy.choose(Observation("read", "read file", {}), candidates())
    assert decision.candidate_id == "mcp"
    assert decision.probabilities["mcp"] == 0.9


def test_jev_policy_rejects_inconsistent_choice():
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "answers": {
                    "action": {
                        "choice": "gui",
                        "probabilities": {"gui": 0.1, "mcp": 0.9},
                        "confidence": 0.8,
                    }
                }
            },
        )

    policy = JevPolicy(
        api_key="secret", client=httpx.Client(transport=httpx.MockTransport(handler)), retries=0
    )
    with pytest.raises(PolicyError, match="invalid Jev"):
        policy.choose(Observation("read", "read file", {}), candidates())
