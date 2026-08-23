from research_loop import topology
from research_loop.commands import lifecycle
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE


def test_topology_is_canonical_knowledge_base_policy_owner():
    assert lifecycle.KNOWLEDGE_BASE_ACCESS is topology.KNOWLEDGE_BASE_ACCESS

    _nodes, node_map, _sequence = topology.topology_for_profile(DEFAULT_NATIVE_PROFILE)
    expected_access = {
        "L0": "read",
        "L1": "none",
        "L4": "read-write",
        "L8.5": "read-write",
        "L9a": "read",
        "L9b": "read",
        "L10a": "read",
        "L10b": "read",
        "L10c": "read",
    }

    for node_id, expected in expected_access.items():
        assert node_map[node_id].get("knowledge_base") == expected
