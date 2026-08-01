import hashlib
import json
import os
from pathlib import Path

from research_loop import deep_research
from research_loop.hypothesis_ledger import (
    HypothesisLedger, canonical_json,
)
from research_loop.compatibility import get_profile
from research_loop.delta import artifact_for_node
from research_loop.persona_catalog import resolve_persona_template
from research_loop.providers.base import RunReceipt
from research_loop.topology import topology_for_profile
from research_loop.yamlio import _load_yaml_front


def activate_native_project(project_dir):
    project = Path(project_dir)
    store = os.environ["RLR_HYPOTHESIS_STORE"]
    HypothesisLedger(store).bind_project(project)
    return project_dir


def commit_v2(project_dir, candidate_id, node, persona, delta, round_id="1"):
    project = Path(project_dir)
    ledger = HypothesisLedger(os.environ["RLR_HYPOTHESIS_STORE"])
    profile = get_profile(ledger.project_profile(project))
    artifact = artifact_for_node(profile, node)
    key = artifact.storage_key
    target = (project / "02_Agent_Notes" / artifact.storage_persona
              / f"{candidate_id}_{key}_delta.v2.json")
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


def write_native_emission_receipts(project_dir, candidate_id, node, persona, source_file,
                                   *, store_path=None):
    """Build an exact synthetic provider boundary for CLI integration tests."""
    project = Path(project_dir)
    source = Path(source_file)
    ledger = HypothesisLedger(store_path or os.environ["RLR_HYPOTHESIS_STORE"])
    profile = get_profile(ledger.project_profile(project))
    candidate = _load_yaml_front(project / "01_Candidates" / f"{candidate_id}.md")
    project_id = str(ledger.require_binding(project)["project_id"])
    round_id = str(candidate.get("round_id") or "1")
    authorization = ledger.materialize_authorized_context(
        project, candidate_id, round_id, node
    )
    evidence_artifacts = None
    if node in {"L1", "L4", "L8.5"}:
        run_id = deep_research.unique_run_id(project, candidate_id, node)
        if not run_id:
            payload = {
                "schema_version": deep_research.SCHEMA_VERSION,
                "queries": [f"synthetic {node} receipt fixture"],
                "papers": [{
                    "url": f"https://example.invalid/{candidate_id}/{node}",
                    "title": "Synthetic receipt fixture",
                    "source_database": "synthetic-test",
                    "source_metadata_response": {
                        "candidate_id": candidate_id, "node": node,
                    },
                    "open_access": False,
                    "extracts": [
                        {"section": section, "text": f"{section} evidence",
                         "locator": f"{section} 1"}
                        for section in (
                            "Results", "Discussion", "Conclusion", "Methods"
                        )
                    ],
                }],
            }
            if node == "L4":
                payload["review_search"] = {
                    "status": "none_found",
                    "receipt": "synthetic zero-result review search",
                }
            if node == "L8.5":
                payload["verification"] = [{
                    "finding": "synthetic result",
                    "verdict": "supports",
                    "evidence_ids": [],
                }]
            _, node_map, _ = topology_for_profile(profile.profile_id)
            artifact = deep_research.persist_run(
                project, candidate_id, node, payload,
                deep_research.skill_receipt(
                    "codex", ["codex", "exec"], "synthetic", "test"
                ),
                result_context=(
                    '{"synthetic":"result"}' if node == "L8.5" else ""
                ),
                project_id=project_id, round_id=round_id,
                profile_id=profile.profile_id,
                research_persona=str(
                    node_map[node].get("research_persona") or "Curie"
                ),
            )
            if node == "L8.5":
                artifact["verification"][0]["evidence_ids"] = [
                    artifact["papers"][0]["evidence_ids"][0]
                ]
                run_path = project / artifact["path"]
                run_path.write_text(
                    json.dumps(
                        artifact, ensure_ascii=False, indent=2, sort_keys=True
                    ),
                    encoding="utf-8",
                )
            run_id = artifact["run_id"]
        evidence_artifacts = deep_research.evidence_artifact_manifest(
            project, candidate_id, node, run_id
        )
    audit = project / "08_Audit" / "test_provider_receipts"
    audit.mkdir(parents=True, exist_ok=True)
    rendered = audit / f"{candidate_id}_{node}_context.txt"
    rendered.write_text(f"synthetic rendered context for {candidate_id} {node}\n", encoding="utf-8")
    rendered_hash = hashlib.sha256(rendered.read_bytes()).hexdigest()
    prompt = audit / f"{candidate_id}_{node}_prompt.txt"
    prompt.write_text(rendered.read_text(encoding="utf-8"), encoding="utf-8")
    resolution = resolve_persona_template(profile, persona)
    manifest = {
        "schema_version": "ContextManifest/v2",
        "project_id": project_id,
        "candidate_id": candidate_id,
        "round_id": round_id,
        "node": node,
        "persona": persona,
        "profile_id": profile.profile_id,
        "rendered_context_path": str(rendered),
        "rendered_context_sha256": rendered_hash,
        "persona_catalog_sha256": resolution.catalog_sha256,
        "persona_catalog_entry_sha256": resolution.entry_sha256,
        "persona_template_sha256": resolution.template_sha256,
        "persona_body_sha256": resolution.body_sha256,
        "injected_deltas": [],
        "pre_research": (
            {"evidence_run_id": evidence_artifacts["run_id"],
             "evidence_artifacts": evidence_artifacts}
            if evidence_artifacts else None
        ),
        "hypothesis_authorization": {
            "authorization_id": authorization["authorization_id"],
            "as_of_commit_seq": authorization["as_of_commit_seq"],
            "projection_hash": authorization["projection_hash"],
            "artifact_hash": authorization["artifact_hash"],
            "event_ids": authorization["event_ids"],
        },
    }
    manifest_path = audit / f"{candidate_id}_{node}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    receipt_path = audit / f"{candidate_id}_{node}_provider_receipt.json"
    RunReceipt(
        node=node, persona=persona, provider="synthetic-test-provider",
        timestamp="2026-07-30T00:00:00Z", context_hash=rendered_hash,
        project_id=project_id, candidate_id=candidate_id, round_id=manifest["round_id"],
        profile_id=profile.profile_id, context_manifest_path=str(manifest_path),
        context_manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        rendered_context_path=str(rendered), rendered_context_hash=rendered_hash,
        prompt_file=str(prompt),
        prompt_hash=hashlib.sha256(prompt.read_bytes()).hexdigest(),
        provider_delta_path=str(source),
        provider_delta_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
    ).write(receipt_path)
    return manifest_path, receipt_path


write_catalog_emission_receipts = write_native_emission_receipts


def seed_selected_hypothesis(project_dir, candidate_id="C1", round_id="1",
                             statement="H_prev"):
    ledger = HypothesisLedger(os.environ["RLR_HYPOTHESIS_STORE"])
    schema_version = get_profile(ledger.project_profile(project_dir)).delta_schema_version
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
    schema_version = get_profile(ledger.project_profile(project)).delta_schema_version
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
