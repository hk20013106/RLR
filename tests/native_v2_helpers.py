import hashlib
import json
import os
from pathlib import Path

from research_loop.hypothesis_ledger import (
    HypothesisLedger, canonical_json,
)
from research_loop.delta import artifact_key_for


def activate_native_project(project_dir):
    project = Path(project_dir)
    store = os.environ["RLR_HYPOTHESIS_STORE"]
    HypothesisLedger(store).bind_project(project)
    return project_dir


def commit_v2(project_dir, candidate_id, node, persona, delta, round_id="1"):
    project = Path(project_dir)
    ledger = HypothesisLedger(os.environ["RLR_HYPOTHESIS_STORE"])
    key = artifact_key_for(node, persona)
    target = project / "02_Agent_Notes" / persona / f"{candidate_id}_{key}_delta.v2.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    result = ledger.commit_delta(
        project_dir=project, candidate_id=candidate_id, round_id=str(round_id),
        node=node, persona=persona, delta=delta, delta_path=target,
    )
    raw = canonical_json(result.normalized_delta)
    if not target.exists():
        target.write_text(raw, encoding="utf-8")
    assert target.read_text(encoding="utf-8") == raw
    receipt_path = project / "08_Audit" / "hypothesis_commits" / (
        f"H{result.commit_seq:08d}_{candidate_id}_{node}.json"
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_raw = canonical_json(result.receipt)
    if not receipt_path.exists():
        receipt_path.write_text(receipt_raw, encoding="utf-8")
    assert receipt_path.read_text(encoding="utf-8") == receipt_raw
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    receipt_digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    ledger.finalize_emission(result.delta_hash, artifact_sha256=digest,
                             receipt_sha256=receipt_digest)
    return result


def seed_selected_hypothesis(project_dir, candidate_id="C1", round_id="1",
                             statement="H_prev"):
    ledger = HypothesisLedger(os.environ["RLR_HYPOTHESIS_STORE"])
    schema_version = ("2.1" if ledger.project_profile(project_dir) == "v2.1" else "2.0")
    proposals = [{
        "proposal_key": "p1", "statement": statement,
        "operationalization": "measure H", "falsification_criteria": ["H absent"],
        "rationale": "test",
    }]
    if schema_version == "2.1":
        proposals.extend([
            {"proposal_key": "p2", "statement": f"{statement} alternative 1",
             "operationalization": "measure alternative", "falsification_criteria": ["absent"], "rationale": "test"},
            {"proposal_key": "p3", "statement": f"{statement} alternative 2",
             "operationalization": "measure alternative", "falsification_criteria": ["absent"], "rationale": "test"},
        ])
    l1 = commit_v2(project_dir, candidate_id, "L1", "Einstein", {
        "schema_version": schema_version, "hypotheses": proposals,
        "primary_proposal_key": "p1", "key_uncertainty": "effect",
    }, round_id)
    hid = l1.normalized_delta["primary_hypothesis_id"]
    if schema_version == "2.1":
        commit_v2(project_dir, candidate_id, "L2", "Feynman", {
            "schema_version": "2.1", "attacks": [], "confounders": [],
            "diagnostic_tests": [], "verdicts": [
                {
                    "hypothesis_id": item["hypothesis_id"],
                    "outcome": "SURVIVES" if item["hypothesis_id"] == hid else "REJECT",
                    "reason": "fixture verdict",
                }
                for item in l1.normalized_delta["hypotheses"]
            ],
        }, round_id)
    triage = []
    for item in l1.normalized_delta["hypotheses"]:
        selected = item["hypothesis_id"] == hid
        record = {"hypothesis_id": item["hypothesis_id"],
                  "disposition": "SELECTED" if selected else "REJECTED",
                  "reason_code": "TESTABLE" if schema_version == "2.1" else "TEST",
                  "reason": "testable"}
        if schema_version == "2.1":
            record["assessments"] = {
                field: {"verdict": "PASS" if selected else "FAIL", "evidence": "fixture"}
                for field in ("testability", "novelty", "feasibility", "impact")
            }
        triage.append(record)
    commit_v2(project_dir, candidate_id, "L3", "Oppenheimer", {
        "schema_version": schema_version, "triage": triage, "route_to": "Fisher",
    }, round_id)
    return hid


def seed_revise_continuation(project_dir, candidate_id="C_prev", *, write_memory=True,
                             loop_type="divergent"):
    project = Path(project_dir)
    candidate_file = project / "01_Candidates" / f"{candidate_id}.md"
    candidate_file.parent.mkdir(parents=True, exist_ok=True)
    if not candidate_file.exists():
        candidate_file.write_text(
            "---\n" f"candidate_id: {candidate_id}\n" "question: Q0\n"
            "claim: H_prev\nround_id: 1\nround_type: initial\n---\n",
            encoding="utf-8",
        )
    hid = seed_selected_hypothesis(project, candidate_id, statement="H_prev")
    ledger = HypothesisLedger(os.environ["RLR_HYPOTHESIS_STORE"])
    schema_version = "2.1" if ledger.project_profile(project) == "v2.1" else "2.0"
    commit_v2(project, candidate_id, "L4", "Fisher", {
        "schema_version": schema_version, "strategies": [{
            "strategy_id": "S1", "hypothesis_ids": [hid], "name": "method",
            "steps": ["measure"],
        }],
    })
    if schema_version == "2.1":
        commit_v2(project, candidate_id, "L5", "Tukey", {
            "schema_version": "2.1",
            "attacks": [{"attack_id": "A1", "strategy_id": "S1",
                         "hypothesis_ids": [hid], "severity": "HIGH", "text": "fixture"}],
            "qc_checkpoints": [{"strategy_id": "S1", "hypothesis_ids": [hid],
                                "name": "QC", "criterion": "pass"}],
            "failure_stop_rules": [{"strategy_id": "S1", "hypothesis_ids": [hid],
                                    "name": "Stop", "condition": "failure", "reason": "fixture"}],
        })
    commit_v2(project, candidate_id, "L6", "Oppenheimer", {
        "schema_version": schema_version, "analysis_plan": [{
            "strategy_id": "S1", "hypothesis_ids": [hid], "scripts": [],
            "parameters": {}, "outputs": ["result.json"],
            **({"feasibility_assessment": {"verdict": "PASS", "evidence": "fixture"},
                "attack_resolutions": [{"attack_id": "A1", "verdict": "RESOLVED",
                                        "evidence": "fixture"}]} if schema_version == "2.1" else {}),
        }], "method_decision": "APPROVE", "reason": "ready",
    })
    l7 = commit_v2(project, candidate_id, "L7", "Turing", {
        "schema_version": schema_version, "results": [{
            "result_key": "r1", "hypothesis_ids": [hid], "summary": "result",
            "artifact_refs": [{"path": "04_Analysis_Outputs/result.json",
                               "sha256": "a" * 64}],
        }], "scripts_run": [], "warnings": [], "failures": [],
    })
    evidence_id = l7.normalized_delta["results"][0]["evidence_id"]
    commit_v2(project, candidate_id, "L8", "Tukey" if schema_version == "2.1" else "Curie", {
        "schema_version": schema_version, "evidence_assessments": [{
            "evidence_id": evidence_id, "verification": "VERIFIED",
            "relations": [{"hypothesis_id": hid, "outcome": "INCONCLUSIVE",
                           "reason": "weak"}],
        }],
    })
    commit_v2(project, candidate_id, "L9a", "Feynman", {
        "schema_version": schema_version, "assessments": [{
            "hypothesis_id": hid, "epistemic_status": "INSUFFICIENT_EVIDENCE",
            "reason": "weak", "evidence_ids": [evidence_id],
        }],
    })
    l10 = commit_v2(project, candidate_id, "L10b", "Oppenheimer", {
        "schema_version": schema_version, "decision": "REVISE", "reason": "evidence weak",
        "next_steps": ["collect new data"], "hypothesis_decisions": [{
            "hypothesis_id": hid, "disposition": "REVISE", "reason": "refine",
        }], "next_round_proposal": {
            "proposal_key": "next", "statement": "H_next",
            "operationalization": "measure next H",
            "falsification_criteria": ["next H absent"],
            "relationship": "DERIVED_FROM", "parent_hypothesis_ids": [hid],
            "loop_type": loop_type, "reason": "new direction",
        },
    })
    if not write_memory:
        return candidate_id, hid, l10.normalized_delta["next_round_proposal"]["hypothesis_id"]
    from research_loop.engine import _build_loop_memory
    memory = _build_loop_memory(project, candidate_id,
                                os.environ["RLR_HYPOTHESIS_STORE"])
    path = project / "08_Audit" / "loop_memory" / f"{candidate_id}_next_loop_memory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, indent=2, ensure_ascii=False,
                               sort_keys=True), encoding="utf-8")
    return path


commit_finalized = commit_v2
