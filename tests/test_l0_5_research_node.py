import json

from research_loop.compatibility import DEFAULT_NATIVE_PROFILE
from research_loop.preresearch import PRE_RESEARCH_MAP
from research_loop.topology import topology_for_profile


def test_native_topology_has_explicit_l0_5_research_node_between_l0_and_l1():
    _nodes, node_map, sequence = topology_for_profile(DEFAULT_NATIVE_PROFILE)

    assert "L0.5" in node_map
    assert sequence.index("L0") + 1 == sequence.index("L0.5")
    assert sequence.index("L0.5") + 1 == sequence.index("L1")

    l05 = node_map["L0.5"]
    assert l05["persona"] == "Curie"
    assert l05["node_kind"] == "research"
    assert l05["research_required"] is True
    assert l05["research_persona"] == "Curie"
    assert l05["pre_research"] == "deep_research"
    assert l05["knowledge_base"] == "read-write"

    l1 = node_map["L1"]
    assert "pre_research" not in l1
    assert l1.get("knowledge_base", "none") == "none"


def test_active_pre_research_configuration_contains_no_hardcoded_domain_queries():
    for node, config in PRE_RESEARCH_MAP.items():
        assert config["queries"] == [], f"{node} still owns hardcoded seed queries"

    serialized = json.dumps(PRE_RESEARCH_MAP, ensure_ascii=False).lower()
    for leaked_example in (
        "heart rate",
        "cardiac",
        "wgcna",
        "bat",
        "shrew",
        "ecm",
        "module preservation",
        "clusterprofiler",
    ):
        assert leaked_example not in serialized


def test_deep_research_declares_l0_5_as_native_discovery_stage():
    from research_loop import deep_research

    assert "L0.5" in deep_research._STAGES
