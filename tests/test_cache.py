from cua_jev.cache import CachedDecisionPolicy
from cua_jev.models import ActionCandidate, Channel, Observation
from cua_jev.policy import RulePolicy


def test_cache_replays_across_volatile_observation_ids(tmp_path):
    candidates = [ActionCandidate("read", Channel.API, "filesystem.read_text", "Read file")]
    live = CachedDecisionPolicy(RulePolicy(), tmp_path)
    first = live.choose(Observation("task", "read", {"path": "same"}), candidates)
    replay = CachedDecisionPolicy(None, tmp_path, cache_only=True)
    second_observation = Observation("task", "read", {"path": "same"})
    second = replay.choose(second_observation, candidates)
    assert first.candidate_id == second.candidate_id
    assert second.observation_id == second_observation.observation_id
    assert replay.stats == {"calls": 1, "cache_hits": 1}
