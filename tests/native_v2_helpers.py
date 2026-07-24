import hashlib
import json
import os
from pathlib import Path

from research_loop.hypothesis_ledger import (
    HypothesisLedger, canonical_json,
)


def activate_native_project(project_dir):
    project = Path(project_dir)
    store = os.environ["RLR_HYPOTHESIS_STORE"]
    HypothesisLedger(store).bind_project(project)
    return project_dir


def commit_v2(project_dir, candidate_id, node, persona, delta, round_id="1"):
    project = Path(project_dir)
    ledger = HypothesisLedger(os.environ["RLR_HYPOTHESIS_STORE"])
    key = f"{node}_{persona.lower()}"
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
    l1 = commit_v2(project_dir, candidate_id, "L1", "Einstein", {
        "schema_version": "2.0", "hypotheses": [{
            "proposal_key": "p1", "statement": statement,
            "operationalization": "measure H", "falsification_criteria": ["H absent"],
            "rationale": "test",
        }], "primary_proposal_key": "p1", "key_uncertainty": "effect",
    }, round_id)
    hid = l1.normalized_delta["primary_hypothesis_id"]
    commit_v2(project_dir, candidate_id, "L3", "Oppenheimer", {
        "schema_version": "2.0", "triage": [{
            "hypothesis_id": hid, "disposition": "SELECTED",
            "reason_code": "TEST", "reason": "testable",
        }], "route_to": "Fisher",
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
    commit_v2(project, candidate_id, "L4", "Fisher", {
        "schema_version": "2.0", "strategies": [{
            "strategy_id": "S1", "hypothesis_ids": [hid], "name": "method",
            "steps": ["measure"],
        }],
    })
    commit_v2(project, candidate_id, "L6", "Oppenheimer", {
        "schema_version": "2.0", "analysis_plan": [{
            "strategy_id": "S1", "hypothesis_ids": [hid], "scripts": [],
            "parameters": {}, "outputs": ["result.json"],
        }], "method_decision": "APPROVE", "reason": "ready",
    })
    l7 = commit_v2(project, candidate_id, "L7", "Turing", {
        "schema_version": "2.0", "results": [{
            "result_key": "r1", "hypothesis_ids": [hid], "summary": "result",
            "artifact_refs": [{"path": "04_Analysis_Outputs/result.json",
                               "sha256": "a" * 64}],
        }], "scripts_run": [], "warnings": [], "failures": [],
    })
    evidence_id = l7.normalized_delta["results"][0]["evidence_id"]
    commit_v2(project, candidate_id, "L8", "Curie", {
        "schema_version": "2.0", "evidence_assessments": [{
            "evidence_id": evidence_id, "verification": "VERIFIED",
            "relations": [{"hypothesis_id": hid, "outcome": "INCONCLUSIVE",
                           "reason": "weak"}],
        }],
    })
    commit_v2(project, candidate_id, "L9a", "Feynman", {
        "schema_version": "2.0", "assessments": [{
            "hypothesis_id": hid, "epistemic_status": "INSUFFICIENT_EVIDENCE",
            "reason": "weak", "evidence_ids": [evidence_id],
        }],
    })
    l10 = commit_v2(project, candidate_id, "L10b", "Oppenheimer", {
        "schema_version": "2.0", "decision": "REVISE", "reason": "evidence weak",
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
