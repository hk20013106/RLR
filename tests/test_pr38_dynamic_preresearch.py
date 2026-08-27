from research_loop.preresearch import PRE_RESEARCH_MAP


def test_active_preresearch_has_no_repository_owned_query_literals():
    for node in ("L1", "L4", "L7", "L8.5"):
        assert PRE_RESEARCH_MAP[node]["queries"] == [], node
