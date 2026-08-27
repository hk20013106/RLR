from research_loop.compatibility import DEFAULT_NATIVE_PROFILE, PROFILE_V20, PROFILE_V21
from research_loop.topology import topology_for_profile


def test_native_profile_exposes_explicit_l05_between_l0_and_l1():
    _, node_map, sequence = topology_for_profile(DEFAULT_NATIVE_PROFILE)

    assert sequence[:3] == ["L0", "L0.5", "L1"]
    l05 = node_map["L0.5"]
    assert l05["persona"] == "Curie"
    assert l05["node_kind"] == "research"
    assert l05["research_required"] is True
    assert l05["knowledge_base"] == "read-write"

    l1 = node_map["L1"]
    assert "pre_research" not in l1
    assert "research_persona" not in l1
    assert "research_required" not in l1
    assert l1["knowledge_base"] == "none"


def test_legacy_profiles_keep_l1_owned_preresearch_without_l05():
    for profile_id in (PROFILE_V20, PROFILE_V21):
        _, node_map, sequence = topology_for_profile(profile_id)

        assert "L0.5" not in sequence
        assert "L0.5" not in node_map
        l1 = node_map["L1"]
        assert l1["pre_research"] == "deep_research"
        assert l1["research_persona"] == "Curie"
        assert l1["research_required"] is True
