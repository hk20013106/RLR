from research_loop.delta_render import _format_delta_body
from sync_to_obsidian import fmt_delta_note


def test_obsidian_native_v21_l6_uses_canonical_delta_renderer():
    delta = {
        "schema_version": "2.1",
        "candidate_id": "C1",
        "analysis_plan": [
            {
                "strategy_id": "S1",
                "hypothesis_ids": ["H1"],
                "scripts": [{"name": "analysis.py"}],
                "parameters": {"alpha": 0.05},
                "outputs": ["result.csv"],
            }
        ],
        "method_decision": "APPROVE",
        "reason": "valid native plan",
    }

    rendered = fmt_delta_note("L6_oppenheimer", delta)
    canonical = _format_delta_body("L6_oppenheimer", delta).rstrip()

    assert rendered == canonical
    assert "Analysis plan" in rendered
