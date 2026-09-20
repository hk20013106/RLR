"""Native v2.1 L4 evidence authority closure (T1-T6, T10 + junction).

The fresh real cold-start E2E reached L4 emit-delta and failed with
``native L4 emission requires exact evidence artifact hashes``: the native L4
context manifest never froze the exact L4B evidence authority (``pre_research``
is deliberately None for native L4), while the emission validator and the L4C
handle binder still required it.  These tests pin the single frozen authority
chain from canonical context assembly to the L4.5 projection.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from native_v2_helpers import bootstrap_project_ready, seed_selected_hypothesis
from test_l4b_to_l4c_context import METHOD_TEXT, _bind_round_data, _fetcher, _manifest

from research_loop import deep_research as dr
from research_loop import l4_evidence_bundle as bundle
from research_loop import l4_pipeline as l4p
from research_loop.commands import ledger as ledger_commands
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.context import cmd_assemble_context
from research_loop.engine import main as engine_main
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.providers.base import RunReceipt

RL = Path(__file__).resolve().parents[1] / "research_loop_v04.py"


def _native_l4_project(tmp_path, monkeypatch, paperqa_runtime):
    """Real native v2.1 project with one staged L4B evidence bundle."""
    project = tmp_path / "project"
    project.mkdir()
    store = tmp_path / "hypotheses.sqlite"
    ledger = HypothesisLedger(store)
    binding = ledger.bind_project(project, profile_id=PROFILE_V21_CATALOG_1)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    candidate = project / "01_Candidates" / "C1.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        "---\n"
        "candidate_id: C1\n"
        "question: Which method should test H1?\n"
        "claim: H1 predicts differential expression.\n"
        "round_id: 1\n"
        "current_status: IDEA_SELECTED\n"
        "---\n",
        encoding="utf-8",
    )
    bootstrap_project_ready(
        project, RL, extra_env={"RLR_HYPOTHESIS_STORE": str(store)}
    )
    _bind_round_data(project)
    hypothesis_id = seed_selected_hypothesis(project, "C1")
    l4a = _manifest(project, str(binding["project_id"]))
    artifact = bundle.run_l4b_evidence(
        l4p,
        dr,
        project,
        "C1",
        l4a,
        tmp_path / "work",
        project_id=str(binding["project_id"]),
        round_id="1",
        profile_id=PROFILE_V21_CATALOG_1,
        research_persona="Curie",
        fetcher=_fetcher,
        paperqa_runtime=paperqa_runtime,
    )
    return project, store, artifact, hypothesis_id


def _assemble_args(project, store, run_id):
    return SimpleNamespace(
        project_dir=str(project),
        cand_id="C1",
        node="L4",
        authorization_id=None,
        knowledge_store=str(store),
        template_mode="contract",
        pre_research_mode="digest",
        pre_research_token_budget=None,
        context_token_budget=12000,
        evidence_run_id=run_id,
    )


def _latest_manifest(project):
    manifest_path = sorted(
        (project / "08_Audit").glob("context_manifest_L4_*.json")
    )[-1]
    return manifest_path, json.loads(manifest_path.read_text(encoding="utf-8"))


def _provider_delta(artifact, hypothesis_id, *, run_id=None):
    """A provider-boundary delta that satisfies the staged L4C contract."""
    catalog = bundle.l4c_reference_catalog(artifact)
    card_handle = catalog["evidence_cards"][0]["handle"]
    anchor_handle = catalog["method_anchors"][0]["handle"]
    return {
        "schema_version": "2.1",
        "candidate_id": "C1",
        "deep_research_run_id": run_id or artifact["run_id"],
        "strategies": [{
            "strategy_id": "S1",
            "hypothesis_ids": [hypothesis_id],
            "name": "Differential-expression analysis",
            "steps": ["fit model"],
        }],
        "method_components": [{
            "component_id": "differential_expression",
            "name": "Differential-expression model",
            "required": True,
            "rationale": "Tests H1.",
        }],
        "method_candidates": [{
            "method_id": "deseq2",
            "component_id": "differential_expression",
            "hypothesis_ids": [hypothesis_id],
            "name": "DESeq2",
            "status": "eligible",
            "purpose": "Estimate differential expression.",
            "applicable_to": ["RNA-seq counts"],
            "implementation_steps": ["fit a negative-binomial model"],
            "assumptions": ["count input"],
            "expected_outputs": ["adjusted probabilities"],
            "strengths": ["auditable implementation"],
            "limitations": ["requires adequate replication"],
            "alternatives": ["edgeR"],
            "method_anchor_handles": [anchor_handle],
            "evidence_card_handles": [card_handle],
            "evidence_gap_handles": [],
            "required_inputs": ["RNA-seq count matrix"],
            "optional_diagnostics": ["RNA quality"],
            "missing_inputs": [],
            "rejection_reasons": [],
            "missing_source": "",
            "execution_required": True,
        }],
    }


def _provider_boundary(project, manifest_path, delta_path):
    """Build the controlled provider receipt bound to the real manifest."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    rendered = Path(manifest["rendered_context_path"])
    rendered_hash = str(manifest["rendered_context_sha256"])
    audit = project / "08_Audit" / "test_provider_receipts"
    audit.mkdir(parents=True, exist_ok=True)
    prompt = audit / "C1_L4_prompt.txt"
    prompt.write_bytes(rendered.read_bytes())
    receipt_path = audit / "C1_L4_provider_receipt.json"
    RunReceipt(
        node="L4",
        persona="Fisher",
        provider="synthetic-native-l4-boundary",
        timestamp="2026-09-20T00:00:00Z",
        context_hash=rendered_hash,
        project_id=str(manifest["project_id"]),
        candidate_id="C1",
        round_id=str(manifest["round_id"]),
        profile_id=str(manifest["profile_id"]),
        context_manifest_path=str(manifest_path),
        context_manifest_hash=hashlib.sha256(
            Path(manifest_path).read_bytes()
        ).hexdigest(),
        rendered_context_path=str(rendered),
        rendered_context_hash=rendered_hash,
        prompt_file=str(prompt),
        prompt_hash=hashlib.sha256(prompt.read_bytes()).hexdigest(),
        provider_delta_path=str(delta_path),
        provider_delta_hash=hashlib.sha256(delta_path.read_bytes()).hexdigest(),
    ).write(receipt_path)
    return receipt_path


def _emit(project, store, manifest_path, receipt_path, delta_path):
    return engine_main([
        "emit-delta", str(project), "C1", "--node", "L4", "--persona", "Fisher",
        "--file", str(delta_path),
        "--knowledge-store", str(store),
        "--context-manifest", str(manifest_path),
        "--provider-receipt", str(receipt_path),
    ])


def _hypothesis_commits(project):
    return sorted((project / "08_Audit" / "hypothesis_commits").glob("H*_C1_L4.json"))


def _second_l4_run(project, store):
    """Persist a second legal L4 evidence run for the same candidate."""
    payload = {
        "schema_version": dr.SCHEMA_VERSION,
        "queries": ["synthetic second L4 run"],
        "papers": [{
            "url": "https://example.invalid/C1/L4-second",
            "title": "Synthetic second L4 fixture",
            "source_database": "synthetic-test",
            "source_metadata_response": {"candidate_id": "C1", "node": "L4"},
            "open_access": False,
            "extracts": [
                {"section": section, "text": f"{section} evidence",
                 "locator": f"{section} 1"}
                for section in ("Results", "Discussion", "Conclusion", "Methods")
            ],
        }],
        "review_search": {
            "status": "none_found",
            "receipt": "synthetic zero-result review search",
        },
    }
    ledger = HypothesisLedger(store)
    project_id = str(ledger.require_binding(project)["project_id"])
    return dr.persist_run(
        project, "C1", "L4", payload,
        dr.skill_receipt("codex", ["codex", "exec"], "synthetic", "test"),
        project_id=project_id, round_id="1", profile_id=PROFILE_V21_CATALOG_1,
        research_persona="Curie",
    )


def _full_boundary(tmp_path, monkeypatch, paperqa_runtime):
    project, store, artifact, hypothesis_id = _native_l4_project(
        tmp_path, monkeypatch, paperqa_runtime
    )
    assert cmd_assemble_context(_assemble_args(project, store, artifact["run_id"])) == 0
    manifest_path, manifest = _latest_manifest(project)
    delta_path = tmp_path / "L4_Fisher_delta.json"
    delta_path.write_text(
        json.dumps(_provider_delta(artifact, hypothesis_id)), encoding="utf-8"
    )
    receipt_path = _provider_boundary(project, manifest_path, delta_path)
    return (
        project, store, artifact, manifest_path, manifest, delta_path,
        receipt_path,
    )


# --- T1 + T6 + junction: assembly freezes the exact native evidence ---------


def test_t1_native_l4_context_freezes_exact_evidence_authority(
    tmp_path, monkeypatch, capsys, l4_paperqa2_runtime
):
    project, store, artifact, _hid = _native_l4_project(
        tmp_path, monkeypatch, l4_paperqa2_runtime(METHOD_TEXT)[0]
    )
    assert cmd_assemble_context(_assemble_args(project, store, artifact["run_id"])) == 0
    manifest_path, manifest = _latest_manifest(project)

    # T6: the retired pre-research channel stays None for native L4.
    assert manifest["pre_research"] is None

    frozen = manifest["native_l4_evidence"]
    assert isinstance(frozen, dict)
    assert frozen["run_id"] == artifact["run_id"]
    assert frozen["target_node"] == "L4"
    assert frozen == dr.evidence_artifact_manifest(
        project, "C1", "L4", artifact["run_id"]
    )

    # Junction regression (producer -> consumer field compatibility): the
    # ledger consumer must read exactly the field the assembler wrote.
    args = _assemble_args(project, store, artifact["run_id"])
    assert ledger_commands._native_l4_evidence_manifest(args, manifest) == frozen


# --- T2 + T10: assemble -> provider boundary -> emit -> L4.5 -----------------


def test_t2_native_l4_emit_succeeds_and_t10_l45_uses_same_frozen_evidence(
    tmp_path, monkeypatch, capsys, l4_paperqa2_runtime
):
    (
        project, store, artifact, manifest_path, manifest, delta_path,
        receipt_path,
    ) = _full_boundary(
        tmp_path, monkeypatch, l4_paperqa2_runtime(METHOD_TEXT)[0]
    )
    frozen = manifest["native_l4_evidence"]

    rc = _emit(project, store, manifest_path, receipt_path, delta_path)
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "native L4 emission requires exact evidence artifact hashes" not in captured.err
    assert "DELTA V2 VALIDATION: PASS" in captured.out

    commits = _hypothesis_commits(project)
    assert commits, "native L4 emission must reach the canonical commit boundary"
    receipt = json.loads(commits[-1].read_text(encoding="utf-8"))
    # T10: commit provenance carries the same canonical exact manifest.
    assert receipt["provenance"]["evidence_artifacts"] == frozen

    l45_commits = sorted(
        (project / "08_Audit" / "l4_method_commits").glob("C1_*.json")
    )
    assert l45_commits, "staged L4.5 projection must reuse the frozen evidence"
    l45 = json.loads(l45_commits[-1].read_text(encoding="utf-8"))
    assert l45["l4b_run_id"] == artifact["run_id"]
    assert l45["l4b_evidence_manifest"] == frozen


# --- T3: frozen run wins even when a second run appears ----------------------


def test_t3_native_l4_binding_uses_frozen_run_not_latest(
    tmp_path, monkeypatch, capsys, l4_paperqa2_runtime
):
    project, store, artifact, hypothesis_id = _native_l4_project(
        tmp_path, monkeypatch, l4_paperqa2_runtime(METHOD_TEXT)[0]
    )
    assert cmd_assemble_context(_assemble_args(project, store, artifact["run_id"])) == 0
    manifest_path, manifest = _latest_manifest(project)
    frozen = manifest["native_l4_evidence"]

    second = _second_l4_run(project, store)
    assert second["run_id"] != artifact["run_id"]
    # The run is now ambiguous: name-based inference can no longer pick one.
    assert dr.unique_run_id(project, "C1", "L4") is None

    delta_path = tmp_path / "L4_Fisher_delta.json"
    delta_path.write_text(
        json.dumps(_provider_delta(artifact, hypothesis_id)), encoding="utf-8"
    )
    receipt_path = _provider_boundary(project, manifest_path, delta_path)
    rc = _emit(project, store, manifest_path, receipt_path, delta_path)
    captured = capsys.readouterr()
    assert rc == 0, captured.err

    receipt = json.loads(_hypothesis_commits(project)[-1].read_text(encoding="utf-8"))
    assert receipt["provenance"]["evidence_artifacts"] == frozen
    assert receipt["provenance"]["evidence_artifacts"]["run_id"] == artifact["run_id"]
    edge_paths = sorted(
        (project / "08_Audit" / "artifact_transformations").glob("C1_L4_*.json")
    )
    assert edge_paths
    edge = json.loads(edge_paths[-1].read_text(encoding="utf-8"))
    assert edge["evidence_run_id"] == artifact["run_id"]


# --- T4: evidence file tamper fails closed -----------------------------------


def test_t4_native_l4_evidence_tamper_fails_closed(
    tmp_path, monkeypatch, capsys, l4_paperqa2_runtime
):
    (
        project, store, artifact, manifest_path, manifest, delta_path,
        receipt_path,
    ) = _full_boundary(
        tmp_path, monkeypatch, l4_paperqa2_runtime(METHOD_TEXT)[0]
    )
    paper = next(
        item for item in manifest["native_l4_evidence"]["files"]
        if item["kind"] == "paper"
    )
    paper_path = project / paper["path"]
    paper_path.write_text(
        paper_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )

    rc = _emit(project, store, manifest_path, receipt_path, delta_path)
    captured = capsys.readouterr()
    assert rc == 1
    assert "evidence artifacts changed since context assembly" in captured.err
    assert not _hypothesis_commits(project)


# --- T5: evidence reference substitution fails closed ------------------------


def test_t5_native_l4_evidence_substitution_fails_closed(
    tmp_path, monkeypatch, capsys, l4_paperqa2_runtime
):
    project, store, artifact, hypothesis_id = _native_l4_project(
        tmp_path, monkeypatch, l4_paperqa2_runtime(METHOD_TEXT)[0]
    )
    assert cmd_assemble_context(_assemble_args(project, store, artifact["run_id"])) == 0
    manifest_path, manifest = _latest_manifest(project)

    second = _second_l4_run(project, store)
    delta_path = tmp_path / "L4_Fisher_delta.json"
    delta_path.write_text(
        json.dumps(_provider_delta(artifact, hypothesis_id)), encoding="utf-8"
    )
    # The provider boundary binds the genuine assembly-time manifest bytes
    # first; the frozen evidence reference is then substituted for another
    # legal run.
    receipt_path = _provider_boundary(project, manifest_path, delta_path)
    substituted = dr.evidence_artifact_manifest(
        project, "C1", "L4", second["run_id"]
    )
    manifest["native_l4_evidence"] = substituted
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    rc = _emit(project, store, manifest_path, receipt_path, delta_path)
    captured = capsys.readouterr()
    assert rc == 1
    # The manifest bytes no longer match the provider receipt that binds them.
    assert "does not bind the exact context manifest" in captured.err
    assert not _hypothesis_commits(project)


# --- N1: the retired pre-research channel is not a native L4 authority -------


def test_n1_missing_native_l4_evidence_cannot_fall_back_to_pre_research(
    tmp_path, monkeypatch, capsys, l4_paperqa2_runtime
):
    """Retiring the frozen authority field must fail closed, not fall back."""
    project, store, artifact, hypothesis_id = _native_l4_project(
        tmp_path, monkeypatch, l4_paperqa2_runtime(METHOD_TEXT)[0]
    )
    assert cmd_assemble_context(_assemble_args(project, store, artifact["run_id"])) == 0
    manifest_path, manifest = _latest_manifest(project)
    frozen = manifest["native_l4_evidence"]

    # Pre-provider tamper: the frozen authority is retired while the same legal
    # run is offered through the retired pre-research channel.  The provider
    # receipt binds the tampered bytes afterwards, so the manifest hash chain
    # cannot be what rejects this emission.
    manifest.pop("native_l4_evidence")
    manifest["pre_research"] = {
        "evidence_run_id": frozen["run_id"],
        "evidence_artifacts": frozen,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    delta_path = tmp_path / "L4_Fisher_delta.json"
    delta_path.write_text(
        json.dumps(_provider_delta(artifact, hypothesis_id)), encoding="utf-8"
    )
    receipt_path = _provider_boundary(project, manifest_path, delta_path)

    rc = _emit(project, store, manifest_path, receipt_path, delta_path)
    captured = capsys.readouterr()
    assert rc == 1
    assert "does not bind the exact context manifest" not in captured.err
    assert "lacks the frozen evidence authority" in captured.err
    assert not _hypothesis_commits(project)


# --- N2: assembly must freeze an exact evidence run before it is usable ------


def _manifests(project):
    return sorted((project / "08_Audit").glob("context_manifest_L4_*.json"))


def _remove_l4_runs(project):
    """Delete every persisted L4 run, i.e. the 'no evidence run yet' state."""
    runs_dir, _, _ = dr._run_paths(Path(project))
    removed = list(runs_dir.glob("C1_L4_*.json"))
    for path in removed:
        path.unlink()
    assert removed, "fixture must have persisted an L4 run to remove"


def test_n2a_assembly_fails_closed_without_any_evidence_run(
    tmp_path, monkeypatch, capsys, l4_paperqa2_runtime
):
    project, store, _artifact, _hid = _native_l4_project(
        tmp_path, monkeypatch, l4_paperqa2_runtime(METHOD_TEXT)[0]
    )
    _remove_l4_runs(project)

    rc = cmd_assemble_context(_assemble_args(project, store, None))
    captured = capsys.readouterr()
    assert rc == 3
    assert "requires an exact evidence run" in captured.err
    assert not _manifests(project), "no usable native L4 manifest may be created"


def test_n2b_assembly_fails_closed_when_evidence_runs_are_ambiguous(
    tmp_path, monkeypatch, capsys, l4_paperqa2_runtime
):
    project, store, artifact, _hid = _native_l4_project(
        tmp_path, monkeypatch, l4_paperqa2_runtime(METHOD_TEXT)[0]
    )
    second = _second_l4_run(project, store)
    assert second["run_id"] != artifact["run_id"]
    assert dr.unique_run_id(project, "C1", "L4") is None

    before = _manifests(project)
    rc = cmd_assemble_context(_assemble_args(project, store, None))
    captured = capsys.readouterr()
    assert rc == 3
    assert "requires an exact evidence run" in captured.err
    assert _manifests(project) == before, "no new manifest may be created"
