import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from research_loop import (
    deep_research, l0_contract, l85_literature_verification, research_seed,
)
from research_loop.hypothesis_ledger import (
    HypothesisLedger, binding_path, canonical_json,
)
from research_loop.compatibility import (
    DEFAULT_NATIVE_PROFILE,
    PROFILE_V21_CATALOG_1,
    get_profile,
)
from research_loop.delta import artifact_for_node
from research_loop.persona_catalog import resolve_persona_template
from research_loop.providers.base import RunReceipt
from research_loop.topology import topology_for_profile
from research_loop.yamlio import _load_yaml_front, _replace_field


def bootstrap_project_ready(project_dir, controller, *, cwd=None, extra_env=None,
                            profile_id=DEFAULT_NATIVE_PROFILE, project_id=None):
    """Create a real v2 PROJECT_READY fixture without an ARS installation.

    The temporary vault is a genuine required first-mile dependency. PubMed is
    deliberately recorded as an unavailable readiness-only future transport,
    rather than being mocked or promoted to a blocking consumer.
    """
    project = Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)
    index = project / "00_Project_Index.md"
    if not index.exists():
        index.write_text(
            "---\nproject_name: test-project\nkind: project_index\n"
            "created_at: 2026-01-01T00:00:00\n---\n# test-project\n",
            encoding="utf-8",
        )
    vault = project.parent / f"{project.name}-vault"
    (vault / ".obsidian").mkdir(parents=True, exist_ok=True)
    preflight = project / "00_Preflight"
    preflight.mkdir(parents=True, exist_ok=True)
    # Let the production preflight materialize the runtime config so the
    # fixture exercises the same first-mile path as a real project.  Preserve
    # any caller-supplied config instead of overwriting test state.
    pubmed_config = preflight / "pubmed_mcp.json"
    if not pubmed_config.exists():
        pubmed_config.write_text(
            json.dumps({"command": "rlr-fixture-unavailable-pubmed"}) + "\n",
            encoding="utf-8",
        )
    env = {
        **os.environ,
        **(extra_env or {}),
        "OBSIDIAN_VAULT": str(vault),
        "RLR_HOST_BACKEND": "codex",
    }
    store = str(env.get("RLR_HYPOTHESIS_STORE") or "").strip()
    if not store:
        raise AssertionError("ProjectReady fixture requires RLR_HYPOTHESIS_STORE")
    ledger = HypothesisLedger(store)
    if not binding_path(project).is_file():
        ledger.bind_project(
            project, project_id=project_id, profile_id=profile_id,
        )
    else:
        try:
            ledger.require_activated_project(project)
        except Exception as exc:  # test fixture setup should fail explicitly
            raise AssertionError(
                f"invalid native test ledger binding: {binding_path(project)}"
            ) from exc
    ledger.require_binding(project)
    ensure_catalog_paperqa2_binding(project)
    result = subprocess.run(
        [sys.executable, str(controller), "preflight", str(project), "--backend", "codex"],
        capture_output=True, text=True, encoding="utf-8", cwd=cwd, env=env,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    # The native workspace contract intentionally does not consume the
    # historical input_manifest.md.  Keep it absent in fixtures after the
    # production preflight has completed its other readiness probes.
    legacy_manifest = preflight / "input_manifest.md"
    if legacy_manifest.exists():
        legacy_manifest.unlink()
    receipt = project / "00_Preflight" / "preflight_receipt.json"
    receipt_sha = hashlib.sha256(receipt.read_bytes()).hexdigest()
    for candidate_file in sorted((project / "01_Candidates").glob("C*.md")):
        front = _load_yaml_front(candidate_file)
        if front.get("project_ready_receipt_path") is None:
            _replace_field(
                candidate_file,
                "project_ready_receipt_path",
                "00_Preflight/preflight_receipt.json",
            )
        if front.get("project_ready_receipt_sha256") is None:
            _replace_field(
                candidate_file,
                "project_ready_receipt_sha256",
                receipt_sha,
            )
    return env


def ensure_catalog_paperqa2_binding(project_dir):
    """Add the valid test-only PaperQA2 binding required by catalog preflight."""
    project = Path(project_dir)
    binding = json.loads(binding_path(project).read_text(encoding="utf-8"))
    if binding.get("profile_id") != PROFILE_V21_CATALOG_1:
        return
    stub_root = project.parent / f"{project.name}-paperqa2-stub"
    bridge_script = stub_root / "bridge.py"
    paperqa_repo = stub_root / "paperqa-repo"
    pqa_home = stub_root / "pqa-home"
    bridge_script.parent.mkdir(parents=True, exist_ok=True)
    bridge_script.write_text("# PaperQA2 test stub\n", encoding="utf-8")
    paperqa_repo.mkdir(parents=True, exist_ok=True)
    pqa_home.mkdir(parents=True, exist_ok=True)
    runtime_path = deep_research.runtime_config_path(project)
    if runtime_path.exists():
        runtime_config = json.loads(runtime_path.read_text(encoding="utf-8"))
    else:
        runtime_config = deep_research.default_runtime_config("codex")
    runtime_config["paperqa2"] = {
        "bridge_script": str(bridge_script),
        "paperqa_repo": str(paperqa_repo),
        "pqa_home": str(pqa_home),
        "python_executable": sys.executable,
    }
    runtime_path.write_text(
        json.dumps(runtime_config, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def activate_native_project(project_dir):
    project = Path(project_dir)
    store = os.environ["RLR_HYPOTHESIS_STORE"]
    HypothesisLedger(store).bind_project(project)
    return project_dir


def ensure_native_l0_contract(project_dir, candidate_id):
    """Give a native test candidate the same canonical L0 sidecar as production.

    This is test-fixture migration, not a runtime fallback.  Existing valid
    sidecars are revalidated; missing sidecars are synthesized only for initial
    test candidates from their fixture question/claim fields.
    """
    project = Path(project_dir)
    candidate_file = project / "01_Candidates" / f"{candidate_id}.md"
    candidate = _load_yaml_front(candidate_file)
    contract, path, raw = l0_contract.load_contract(project, candidate_id)
    if contract is not None:
        errors = l0_contract.validate_l0_input_contract(
            contract, candidate, project, candidate_id,
            artifact_path=path, raw_bytes=raw,
        )
        if errors:
            raise AssertionError("invalid native L0 test fixture: " + "; ".join(errors))
        return research_seed.load_l1_research_seed(project, candidate_id)

    round_type = str(candidate.get("round_type") or "initial")
    if round_type != "initial":
        raise AssertionError(
            "continuation test fixtures must declare their own canonical L0 sidecar"
        )
    round_id = str(candidate.get("round_id") or "1")
    question = str(candidate.get("question") or "synthetic scientific question")
    claim = str(candidate.get("claim") or "synthetic hypothesis")
    source_input = l0_contract.build_source_input(
        input_type="inline",
        description="synthetic native test fixture input",
        fmt="text",
    )
    contract = l0_contract.promote_to_current_schema(
        l0_contract.build_initial_contract(
            candidate_id, round_id, question, source_input, claim
        )
    )
    path, digest = l0_contract.write_contract(project, candidate_id, contract)
    _replace_field(candidate_file, "schema_version", contract["schema_version"])
    _replace_field(candidate_file, "round_type", "initial")
    _replace_field(candidate_file, "round_id", round_id)
    _replace_field(
        candidate_file, "input_contract_path", path.relative_to(project).as_posix()
    )
    _replace_field(candidate_file, "input_contract_hash", digest)
    return research_seed.load_l1_research_seed(project, candidate_id)


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


def commit_l85_fixture_authority(project_dir, candidate_id, *, result_context="",
                                 round_id="1"):
    """Commit a real synthetic L8.5 artifact for native L10 consumers.

    The production L8.5 emission requires the L4-L7 chain to have advanced the
    candidate's hypothesis to EXECUTED.  Fixtures do not replay that chain, so
    the synthetic hypothesis is pre-advanced to EXECUTED (the state the real
    chain produces); the evidence pack, the native verification run, and the
    L8.5 delta emission itself all go through the real machinery.
    """
    from deep_research_fixtures import persist_synthetic_evidence

    ok, _reason = deep_research.audit_evidence_pack(
        project_dir, candidate_id, "L8.5"
    )
    if ok:
        run_id = str(
            deep_research.unique_run_id(project_dir, candidate_id, "L8.5") or ""
        )
        if not run_id:
            raise AssertionError("existing L8.5 evidence pack is ambiguous")
    else:
        artifact = persist_synthetic_evidence(
            project_dir, candidate_id, "L8.5",
            ["synthetic L8.5 verification"], result_context=result_context,
        )
        run_id = str(artifact["run_id"])
    details = deep_research.evidence_pack_details(
        project_dir, candidate_id, "L8.5", run_id=run_id
    )
    evidence_id = sorted(details["records"])[0]

    hypothesis_id = seed_selected_hypothesis(project_dir, candidate_id)
    store = os.environ["RLR_HYPOTHESIS_STORE"]
    con = sqlite3.connect(store)
    try:
        cursor = con.execute(
            "UPDATE workflow_projection SET workflow_status='EXECUTED' "
            "WHERE occurrence_id=(SELECT occurrence_id FROM occurrences "
            "WHERE hypothesis_id=? AND candidate_id=?)",
            (hypothesis_id, candidate_id),
        )
        if cursor.rowcount != 1:
            raise AssertionError("synthetic L8.5 fixture found no occurrence")
        con.commit()
    finally:
        con.close()

    l85_literature_verification.persist_run_manifest(
        project_dir, candidate_id, run_id=run_id,
        payload={
            "research_seed": {},
            "query_plan": {"plan_id": "qp1", "queries": []},
            "discovery": {},
            "selected_paper_ids": [],
            "source_snapshots": [],
            "located_evidence": [{
                "evidence_id": evidence_id,
                "verification_status": "LOCATED",
                "locator": "char:0:10",
                "text": "synthetic located evidence",
                "retrieval": {
                    "engine": "test",
                    "source_sha256": hashlib.sha256(
                        evidence_id.encode("utf-8")
                    ).hexdigest(),
                    "snapshot_path": "",
                },
            }],
            "semantic_verifications": [],
            "findings": [{"finding_id": "f1", "text": "synthetic finding",
                          "sources": ["L7"]}],
            "verdicts": [{"finding_id": "f1", "verdict": "supports",
                          "evidence_ids": [evidence_id], "reason": "synthetic"}],
        },
    )
    commit_v2(project_dir, candidate_id, "L8.5", "Curie", {
        "schema_version": "2.1",
        "deep_research_run_id": run_id,
        "deep_research_receipt_hash": details["receipt_hash"],
        "assessments": [{
            "hypothesis_id": hypothesis_id,
            "outcome": "SUPPORTS",
            "comparison": "synthetic L8.5 fixture",
            "evidence_ids": [evidence_id],
        }],
        "summary": "synthetic L8.5 fixture delta",
        "searched_keywords": ["synthetic"],
        "papers": [],
    }, round_id)
    return run_id, evidence_id


def write_native_emission_receipts(project_dir, candidate_id, node, persona, source_file,
                                   *, store_path=None):
    """Build an exact synthetic provider boundary for CLI integration tests."""
    project = Path(project_dir)
    source = Path(source_file)
    ledger = HypothesisLedger(store_path or os.environ["RLR_HYPOTHESIS_STORE"])
    profile = get_profile(ledger.project_profile(project))
    seed = ensure_native_l0_contract(project, candidate_id) if node == "L1" else None
    candidate = _load_yaml_front(project / "01_Candidates" / f"{candidate_id}.md")
    project_id = str(ledger.require_binding(project)["project_id"])
    round_id = str(seed["round_id"] if seed is not None
                   else candidate.get("round_id") or "1")
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
    native_l85_evidence = None
    if node in ("L10a", "L10b"):
        # Native L10 consumers validate the frozen L8.5 authority before the
        # gate: mirror the real manifest shape with a synthetic exact run that
        # freezes exactly the evidence IDs this delta cites.
        cited = [
            str(item) for item in
            (json.loads(source.read_text(encoding="utf-8"))
             .get("literature_evidence_ids") or [])
        ]
        run_id = f"{candidate_id}_{node}_l85_authority"
        snapshots = project / "08_Audit" / "l85_snapshots"
        located = []
        for index, evidence_id in enumerate(cited):
            snapshot = snapshots / f"{run_id}_{index}.txt"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(evidence_id.encode("utf-8"))
            located.append({
                "evidence_id": evidence_id,
                "verification_status": "LOCATED",
                "locator": "char:0:10",
                "text": f"synthetic boundary evidence for {evidence_id}",
                "retrieval": {
                    "engine": "test",
                    "source_sha256": hashlib.sha256(
                        evidence_id.encode("utf-8")
                    ).hexdigest(),
                    "snapshot_path": snapshot.relative_to(project).as_posix(),
                },
            })
        l85_literature_verification.persist_run_manifest(
            project, candidate_id, run_id=run_id,
            payload={
                "research_seed": {},
                "query_plan": {"plan_id": "qp1", "queries": []},
                "discovery": {},
                "selected_paper_ids": [],
                "source_snapshots": [],
                "located_evidence": located,
                "semantic_verifications": [],
                "findings": [{"finding_id": "f1", "text": "synthetic finding",
                              "sources": ["L7"]}],
                "verdicts": [{"finding_id": "f1", "verdict": "supports",
                              "evidence_ids": cited, "reason": "synthetic"}],
            },
        )
        native_l85_evidence = {"run_id": run_id, "evidence_ids": cited}
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
        # Native L4 contexts carry the exact evidence authority in their own
        # field while the retired pre-research channel stays None, matching the
        # real context assembler.  L1/L8.5 keep the historical shape.
        "pre_research": (
            {"evidence_run_id": evidence_artifacts["run_id"],
             "evidence_artifacts": evidence_artifacts}
            if evidence_artifacts and node != "L4" else None
        ),
        "native_l4_evidence": (
            evidence_artifacts if node == "L4" else None
        ),
        "native_l85_evidence": native_l85_evidence,
        "research_seed": (
            research_seed.manifest_entry(seed) if seed is not None else None
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
    result_path = project / "04_Analysis_Outputs" / "result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('{"result":"fixture"}\n', encoding="utf-8")
    result_sha = hashlib.sha256(result_path.read_bytes()).hexdigest()
    l7 = commit_v2(project, candidate_id, "L7", "Turing", {
        "schema_version": schema_version, "results": [{
            "result_key": "r1", "hypothesis_ids": [hid], "summary": "result",
            "artifact_refs": [{"path": "04_Analysis_Outputs/result.json",
                               "sha256": result_sha}],
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
