"""Regression contract for canonical L6 script objects consumed by L7."""

from pathlib import Path

from native_v2_helpers import activate_native_project, commit_v2, seed_selected_hypothesis
from research_loop.commands.execution import _approved_execution_scripts
from research_loop.compatibility import get_profile
from research_loop.hypothesis_ledger import HypothesisLedger


def _from_memory_l6_fixture(tmp_path: Path):
    project = tmp_path / "P"
    candidate_id = "CROUND2"
    candidate = project / "01_Candidates" / f"{candidate_id}.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        "---\n"
        f"candidate_id: {candidate_id}\n"
        "round_id: 2\n"
        "round_type: continuation\n"
        "current_status: METHOD_APPROVED\n"
        "current_owner: Oppenheimer\n"
        "---\n",
        encoding="utf-8",
    )
    activate_native_project(project)

    hid = seed_selected_hypothesis(
        project, candidate_id=candidate_id, round_id="2", statement="H2"
    )
    ledger = HypothesisLedger(str(tmp_path / "hypotheses.sqlite"))
    schema_version = get_profile(ledger.project_profile(project)).delta_schema_version

    commit_v2(project, candidate_id, "L4", "Fisher", {
        "schema_version": schema_version,
        "strategies": [{
            "strategy_id": "S1",
            "hypothesis_ids": [hid],
            "name": "reuse prior analysis",
            "steps": ["run the approved script"],
        }],
    }, round_id="2")
    if schema_version == "2.1":
        commit_v2(project, candidate_id, "L5", "Tukey", {
            "schema_version": "2.1",
            "attacks": [{
                "attack_id": "A1",
                "strategy_id": "S1",
                "hypothesis_ids": [hid],
                "severity": "HIGH",
                "text": "verify prior reuse",
            }],
            "qc_checkpoints": [{
                "strategy_id": "S1",
                "hypothesis_ids": [hid],
                "name": "QC",
                "criterion": "script is traceable",
            }],
            "failure_stop_rules": [{
                "strategy_id": "S1",
                "hypothesis_ids": [hid],
                "name": "Stop",
                "condition": "traceability missing",
                "reason": "fail closed",
            }],
        }, round_id="2")

    # The L6 traceability gate requires object-form scripts for from-memory
    # candidates. Switch the already-seeded candidate to that real boundary
    # before committing the L6 plan.
    candidate.write_text(
        "---\n"
        f"candidate_id: {candidate_id}\n"
        "round_id: 2\n"
        "round_type: continuation\n"
        "from_memory: true\n"
        "current_status: METHOD_APPROVED\n"
        "current_owner: Oppenheimer\n"
        "---\n",
        encoding="utf-8",
    )

    script = project / "04_Analysis_Outputs" / "round_data_continuity_read.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('ok')\n", encoding="utf-8")

    plan = {
        "schema_version": schema_version,
        "analysis_plan": [{
            "strategy_id": "S1",
            "hypothesis_ids": [hid],
            "scripts": [{
                "name": script.name,
                "branch_id": "round-2-prior-reuse",
                "data_modality": "tabular",
                "grounding": {
                    "type": "prior_reuse",
                    "reused_from": "CROUND1_round_1.json",
                },
            }],
            "parameters": {},
            "outputs": ["result.json"],
            **({
                "feasibility_assessment": {
                    "verdict": "PASS", "evidence": "fixture"
                },
                "attack_resolutions": [{
                    "attack_id": "A1",
                    "verdict": "RESOLVED",
                    "evidence": "traceability object is complete",
                }],
            } if schema_version == "2.1" else {}),
        }],
        "method_decision": "APPROVE",
        "reason": "ready",
    }
    commit_v2(project, candidate_id, "L6", "Oppenheimer", plan, round_id="2")
    return project, candidate_id, script


def test_l7_resolves_from_memory_l6_script_object_by_name(tmp_path):
    project, candidate_id, script = _from_memory_l6_fixture(tmp_path)

    resolved, missing = _approved_execution_scripts(project, candidate_id)

    assert missing == []
    assert resolved == [script]
