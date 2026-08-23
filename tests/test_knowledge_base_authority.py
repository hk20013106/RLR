from research_loop import topology
from research_loop.commands import lifecycle
from research_loop.compatibility import DEFAULT_NATIVE_PROFILE


def test_topology_is_canonical_knowledge_base_policy_owner():
    assert lifecycle.KNOWLEDGE_BASE_ACCESS is topology.KNOWLEDGE_BASE_ACCESS

    nodes, node_map, _sequence = topology.topology_for_profile(DEFAULT_NATIVE_PROFILE)
    expected_access = {
        "L0": "read",
        "L0.5": "read-write",
        "L1": "none",
        "L4": "read-write",
        "L8.5": "read-write",
        "L9a": "read",
        "L9b": "read",
        "L10a": "read",
        "L10b": "read",
        "L10c": "read",
    }
    assert topology.KNOWLEDGE_BASE_ACCESS == expected_access

    for node in nodes:
        node_id = node["node"]
        expected = expected_access.get(node_id, "none")
        assert node_map[node_id]["knowledge_base"] == expected
