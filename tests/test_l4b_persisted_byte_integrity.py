import hashlib
import json
from pathlib import Path

from research_loop import deep_research as dr
from research_loop import l4_evidence_bundle as bundle
from research_loop import l4_inventory
from research_loop import l4_pipeline as l4p


METHOD_TEXT = (
    "DESeq2 estimates size factors, fits negative-binomial models, moderates "
    "dispersion estimates, tests coefficients, and reports adjusted values. " * 14
)
A1_XML = (
    "<?xml version='1.0' encoding='UTF-8'?>\n"
    "<article>\n<body>\n"
    "<sec id='methods'><title>Materials and methods</title>\n"
    f"<p>{METHOD_TEXT}</p>\n</sec>\n"
    "</body>\n</article>\n"
)


def _manifest(project: Path) -> dict:
    payload = {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "DESeq2 canonical method source",
            "purpose": "Resolve exact method identifiers.",
            "status": "completed",
            "receipt": "fixture",
        }],
        "assets": [{
            "asset_id": "A1",
            "doi": "10.1186/s13059-014-0550-8",
            "pmid": "25516281",
            "url": "https://pubmed.ncbi.nlm.nih.gov/25516281/",
            "title": "Moderated estimation of fold change and dispersion for RNA-seq data with DESeq2",
            "year": 2014,
            "role": "method",
            "journal": "Genome Biology",
            "abstract": "Metadata only.",
            "source_database": "PubMed",
            "source_metadata_response": json.dumps(
                {"pmcid": "PMC4302049", "id": "25516281"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            "open_access_status": "open",
            "full_text_status": "available_oa",
            "full_text_locations": [
                "https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/"
            ],
            "relevance_score": 10.0,
            "selection_status": "selected",
            "selection_reason": "Canonical method source.",
            "hypothesis_ids": ["H1"],
            "method_component_hints": ["differential_expression"],
            "diagnostic_requirements": [],
        }],
        "method_inventory": [{
            "method_id": "deseq2",
            "name": "DESeq2",
            "purpose": "Differential-expression modelling.",
            "inventory_reason": "The hypothesis requires differential expression.",
            "source_asset_ids": ["A1"],
            "source_hints": [{
                "source_ref_id": "deseq2-love-2014",
                "asset_id": "A1",
                "title": "Moderated estimation of fold change and dispersion for RNA-seq data with DESeq2",
                "year": 2014,
                "doi": "10.1186/s13059-014-0550-8",
                "pmid": "25516281",
                "pmcid": "PMC4302049",
                "url": "",
                "source_kind": "method_paper",
                "rationale": "Canonical implementation source.",
                "full_text_locations": [],
            }],
        }],
    }
    receipt = dr.skill_receipt(
        "codex", ["codex", "exec"], "inventory prompt", "fixture"
    )
    return l4_inventory.persist_discovery(
        l4p,
        dr,
        project,
        "C1",
        payload,
        receipt,
        question="Which method should test H1?",
        claim="H1 predicts differential expression.",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )


def test_staged_l4b_persists_and_audits_exact_downloaded_bytes(tmp_path):
    project = tmp_path / "project"
    manifest = _manifest(project)

    def fetcher(url):
        return {
            "requested_url": url,
            "resolved_url": url,
            "redirect_chain": [],
            "http_status": 200,
            "content_type": "application/xml",
            "body": A1_XML.encode("utf-8"),
        }

    artifact = bundle.run_l4b_evidence(
        l4p,
        dr,
        project,
        "C1",
        manifest,
        tmp_path / "work",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
        fetcher=fetcher,
    )

    paper = json.loads(
        (project / artifact["papers"][0]["path"]).read_text(encoding="utf-8")
    )
    source_path = project / paper["source_payload_path"]
    persisted_bytes = source_path.read_bytes()
    expected_bytes = A1_XML.encode("utf-8")
    expected_hash = hashlib.sha256(expected_bytes).hexdigest()
    receipt = json.loads(
        (project / paper["retrieval_receipt_path"]).read_text(encoding="utf-8")
    )["selected_attempt"]

    assert source_path.suffix == ".xml"
    assert persisted_bytes == expected_bytes
    assert len(persisted_bytes) == receipt["byte_length"] == len(expected_bytes)
    assert hashlib.sha256(persisted_bytes).hexdigest() == expected_hash
    assert paper["content_hash"] == receipt["content_hash"] == expected_hash
    assert {item["source_hash"] for item in paper["evidence_extracts"]} == {
        expected_hash
    }
    assert {card["content_hash"] for card in artifact["evidence_cards"]} == {
        expected_hash
    }
    assert bundle.audit_bundle(l4p, dr, project, "C1", artifact) == (True, "")
