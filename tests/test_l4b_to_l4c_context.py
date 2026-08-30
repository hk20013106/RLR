import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from native_v2_helpers import seed_selected_hypothesis
import run_loop
from research_loop import deep_research as dr
from research_loop import l0_contract, l0_data
from research_loop import l4_evidence_bundle as bundle
from research_loop import l4_inventory
from research_loop import l4_pipeline as l4p
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.context import cmd_assemble_context
from research_loop.engine import main as engine_main
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.hypothesis_contracts import validate_provider_submission
from research_loop.preresearch import PRE_RESEARCH_MAP, _validate_pre_research_content
from research_loop.providers.base import RunReceipt


METHOD_TEXT = (
    "DESeq2 estimates size factors from median ratios, fits negative-binomial "
    "models, moderates dispersion estimates, tests coefficients, and reports "
    "adjusted probabilities. " * 14
)
A1_XML = (
    "<?xml version='1.0' encoding='UTF-8'?>"
    "<article><front><article-meta>"
    "<article-id pub-id-type='doi'>10.1186/s13059-014-0550-8</article-id>"
    "<article-id pub-id-type='pmcid'>PMC4302049</article-id>"
    "</article-meta></front><body>"
    "<sec id='methods'><title>Materials and methods</title>"
    f"<p>{METHOD_TEXT}</p></sec>"
    "<sec><title>Results</title><p>Results.</p></sec>"
    "</body></article>"
)


def _source_hint(source_ref_id, *, doi, pmid, pmcid="", url=""):
    return {
        "source_ref_id": source_ref_id,
        "title": source_ref_id,
        "year": 2014,
        "doi": doi,
        "pmid": pmid,
        "pmcid": pmcid,
        "url": url,
        "source_kind": "method_paper",
        "rationale": "Canonical implementation source.",
        "full_text_locations": [],
    }


def _method(method_id, source_hint):
    return {
        "method_id": method_id,
        "name": method_id,
        "purpose": "Provide an auditable implementation method.",
        "inventory_reason": "The selected hypothesis requires this method.",
        "source_asset_ids": [],
        "source_hints": [source_hint],
    }


def _manifest(project, project_id):
    payload = {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "DESeq2 and ComBat exact method sources",
            "purpose": "Resolve exact method identifiers.",
            "status": "completed",
            "receipt": "fixture",
        }],
        "assets": [],
        "method_inventory": [
            _method(
                "deseq2",
                _source_hint(
                    "deseq2-love-2014",
                    doi="10.1186/s13059-014-0550-8",
                    pmid="25516281",
                    pmcid="PMC4302049",
                ),
            ),
            _method(
                "combat",
                _source_hint(
                    "combat-johnson-2007",
                    doi="10.1093/biostatistics/kxj037",
                    pmid="16632515",
                    url="https://pubmed.ncbi.nlm.nih.gov/16632515/",
                ),
            ),
        ],
    }
    return l4_inventory.persist_discovery(
        l4p,
        dr,
        project,
        "C1",
        payload,
        dr.skill_receipt("codex", ["codex", "exec"], "inventory", "test"),
        question="Which method should test H1?",
        claim="H1 predicts differential expression.",
        project_id=project_id,
        round_id="1",
        profile_id=PROFILE_V21_CATALOG_1,
    )


def _fetcher(url):
    if "PMC4302049" in url or "s13059-014-0550-8" in url:
        return {
            "requested_url": url,
            "resolved_url": url,
            "redirect_chain": [],
            "http_status": 200,
            "content_type": "application/xml",
            "body": A1_XML.encode("utf-8"),
        }
    raise OSError("fixture source unavailable")


def _bind_round_data(project):
    """Give L4 fixtures the same canonical L0 data authority as a real round."""
    source_input = l0_contract.build_source_input(
        input_type="inline",
        description="synthetic L4 context fixture input",
        fmt="text",
    )
    contract = l0_contract.promote_to_current_schema(
        l0_contract.build_initial_contract(
            "C1",
            "1",
            "Which method should test H1?",
            source_input,
            "H1 predicts differential expression.",
        )
    )
    l0_contract.write_contract(project, "C1", contract)
    l0_data.write_current_round_data_binding(project, "C1")


def test_staged_l4b_passes_real_l4_context_boundary(
    tmp_path, monkeypatch, capsys
):
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
    _bind_round_data(project)
    seed_selected_hypothesis(project, "C1")

    manifest = _manifest(project, str(binding["project_id"]))
    artifact = bundle.run_l4b_evidence(
        l4p,
        dr,
        project,
        "C1",
        manifest,
        tmp_path / "work",
        project_id=str(binding["project_id"]),
        round_id="1",
        profile_id=PROFILE_V21_CATALOG_1,
        research_persona="Curie",
        fetcher=_fetcher,
    )
    assert bundle.audit_bundle(l4p, dr, project, "C1", artifact) == (True, "")

    summary = (project / artifact["summary_path"]).read_text(encoding="utf-8")
    assert _validate_pre_research_content(summary, PRE_RESEARCH_MAP["L4"]) == (
        True,
        "",
    )
    assert "10.1186/s13059-014-0550-8" in summary
    assert "## Query log" in summary
    assert "## Tool receipt" in summary
    assert "### L4C reference handles" in summary
    assert "E1 method=deseq2 evidence card" in summary
    assert "G1 method=combat evidence gap" in summary
    assert artifact["evidence_cards"][0]["evidence_card_id"] not in summary
    assert artifact["evidence_gaps"][0]["evidence_gap_id"] not in summary

    evidence_manifest = dr.evidence_artifact_manifest(
        project, "C1", "L4", artifact["run_id"]
    )
    assert evidence_manifest["receipt_schema"] == "EvidenceRunReceipt/v1.1"

    args = SimpleNamespace(
        project_dir=str(project),
        cand_id="C1",
        node="L4",
        authorization_id=None,
        knowledge_store=str(store),
        template_mode="contract",
        pre_research_mode="digest",
        pre_research_token_budget=None,
        context_token_budget=8000,
        evidence_run_id=artifact["run_id"],
    )
    assert cmd_assemble_context(args) == 0
    output = capsys.readouterr().out
    assert artifact["run_id"] in output
    assert "E1 method=deseq2 evidence card" in output
    assert "G1 method=combat evidence gap" in output
    assert artifact["evidence_cards"][0]["evidence_card_id"] not in output
    assert artifact["evidence_gaps"][0]["evidence_gap_id"] not in output
    assert "L4B retrieves exact registered sources" in output

    manifests = sorted((project / "08_Audit").glob("context_manifest_L4_*.json"))
    assert manifests
    context_manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    assert context_manifest["pre_research"]["evidence_run_id"] == artifact["run_id"]
    assert context_manifest["pre_research"]["evidence_artifacts"][
        "receipt_schema"
    ] == "EvidenceRunReceipt/v1.1"


def test_emit_delta_is_the_l4_handle_binding_boundary(tmp_path, monkeypatch):
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
    )

    assemble_args = SimpleNamespace(
        project_dir=str(project), cand_id="C1", node="L4",
        authorization_id=None, knowledge_store=str(store),
        template_mode="contract", pre_research_mode="digest",
        pre_research_token_budget=None, context_token_budget=8000,
        evidence_run_id=artifact["run_id"],
    )
    assert cmd_assemble_context(assemble_args) == 0
    manifest_path = sorted(
        (project / "08_Audit").glob("context_manifest_L4_*.json")
    )[-1]
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    rendered_path = Path(manifest_data["rendered_context_path"])
    prompt_path = tmp_path / "provider-prompt.txt"
    prompt_path.write_text("provider prompt\n", encoding="utf-8")

    raw_data = {
        "schema_version": "2.1",
        "deep_research_run_id": artifact["run_id"],
        "strategies": [{
            "strategy_id": "S1", "hypothesis_ids": [hypothesis_id],
            "name": "Differential-expression analysis", "steps": ["fit model"],
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
            "method_anchor_handles": ["A1"],
            "evidence_card_handles": ["E1"],
            "evidence_gap_handles": [],
            "required_inputs": ["RNA-seq count matrix"],
            "optional_diagnostics": ["RNA quality"],
            "missing_inputs": [],
            "rejection_reasons": [],
            "missing_source": "",
            "execution_required": True,
        }],
    }
    provider_schema = run_loop._provider_output_schema(
        project,
        "L4",
        {"schema_version": "2.1", "profile_id": PROFILE_V21_CATALOG_1},
    )
    provider_candidate = provider_schema["properties"]["method_candidates"]["items"]
    assert {
        "evidence_card_handles",
        "evidence_gap_handles",
        "method_anchor_handles",
    } <= set(provider_candidate["properties"])
    assert not {
        "evidence_card_ids",
        "evidence_gap_ids",
        "method_anchor_ids",
    } & set(provider_candidate["properties"])
    assert validate_provider_submission(
        "L4",
        raw_data,
        schema_version="2.1",
        profile_id=PROFILE_V21_CATALOG_1,
    ) == []
    raw_path = tmp_path / "L4_Fisher_provider.json"
    raw_path.write_text(json.dumps(raw_data), encoding="utf-8")
    rendered_hash = hashlib.sha256(rendered_path.read_bytes()).hexdigest()
    provider_receipt = tmp_path / "provider-receipt.json"
    RunReceipt(
        node="L4", persona="Fisher", provider="main-agent",
        timestamp="2026-08-28T00:00:00Z", context_hash=rendered_hash,
        project_id=str(binding["project_id"]), candidate_id="C1", round_id="1",
        profile_id=PROFILE_V21_CATALOG_1,
        context_manifest_path=str(manifest_path),
        context_manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        rendered_context_path=str(rendered_path), rendered_context_hash=rendered_hash,
        prompt_file=str(prompt_path),
        prompt_hash=hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        provider_delta_path=str(raw_path),
        provider_delta_hash=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
    ).write(provider_receipt)

    assert engine_main([
        "emit-delta", str(project), "C1", "--node", "L4",
        "--persona", "Fisher", "--file", str(raw_path),
        "--context-manifest", str(manifest_path),
        "--provider-receipt", str(provider_receipt),
        "--knowledge-store", str(store),
    ]) == 0

    canonical = next(
        (project / "02_Agent_Notes" / "Fisher").glob("C1_*_delta.v2.json")
    )
    committed = json.loads(canonical.read_text(encoding="utf-8"))
    candidate = committed["method_candidates"][0]
    assert candidate["evidence_card_ids"] == [
        artifact["evidence_cards"][0]["evidence_card_id"]
    ]
    assert candidate["method_anchor_ids"] == [
        artifact["evidence_cards"][0]["anchor_id"]
    ]
    assert not list(tmp_path.glob("L4_Fisher_provider_bound.json"))
    commit_receipt = next(
        (project / "08_Audit" / "hypothesis_commits").glob("*C1_L4.json")
    )
    provenance = json.loads(commit_receipt.read_text(encoding="utf-8"))["provenance"]
    edge_path = Path(provenance["transformation_receipt_path"])
    edge = json.loads(edge_path.read_text(encoding="utf-8"))
    assert edge["raw_provider_delta_path"] == str(raw_path)
    assert edge["bound_delta_path"] == str(canonical)
    assert edge["bound_delta_sha256"] == hashlib.sha256(canonical.read_bytes()).hexdigest()
