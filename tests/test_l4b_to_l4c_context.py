import json
from types import SimpleNamespace

from native_v2_helpers import seed_selected_hypothesis
from research_loop import deep_research as dr
from research_loop import l4_evidence_bundle as bundle
from research_loop import l4_inventory
from research_loop import l4_pipeline as l4p
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.context import cmd_assemble_context
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.preresearch import PRE_RESEARCH_MAP, _validate_pre_research_content


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
    assert artifact["evidence_cards"][0]["evidence_card_id"] in summary
    assert artifact["evidence_gaps"][0]["evidence_gap_id"] in summary

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
    assert artifact["evidence_cards"][0]["evidence_card_id"] in output
    assert artifact["evidence_gaps"][0]["evidence_gap_id"] in output
    assert "L4B retrieves exact registered sources" in output

    manifests = sorted((project / "08_Audit").glob("context_manifest_L4_*.json"))
    assert manifests
    context_manifest = json.loads(manifests[-1].read_text(encoding="utf-8"))
    assert context_manifest["pre_research"]["evidence_run_id"] == artifact["run_id"]
    assert context_manifest["pre_research"]["evidence_artifacts"][
        "receipt_schema"
    ] == "EvidenceRunReceipt/v1.1"
