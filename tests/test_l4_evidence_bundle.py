import json
from pathlib import Path

import pytest

from research_loop import deep_research as dr
from research_loop import l4_pipeline as l4p
from research_loop import l4_inventory
from research_loop import l4_evidence_bundle as bundle


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


def _receipt():
    return dr.skill_receipt(
        "codex", ["codex", "exec"], "inventory prompt", "test"
    )


def _asset(*, selection_status="reserve"):
    return {
        "asset_id": "A1",
        "doi": "10.1186/s13059-014-0550-8",
        "pmid": "25516281",
        "url": "https://pubmed.ncbi.nlm.nih.gov/25516281/",
        "title": (
            "Moderated estimation of fold change and dispersion for RNA-seq "
            "data with DESeq2"
        ),
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
        "relevance_score": 8.0,
        "selection_status": selection_status,
        "selection_reason": "General literature ranking.",
        "hypothesis_ids": ["H1"],
        "method_component_hints": ["differential_expression"],
        "diagnostic_requirements": [],
    }


def _hint(*, source_ref_id="A1-source", doi="10.1186/s13059-014-0550-8",
          pmid="25516281", pmcid="PMC4302049", url=""):
    return {
        "source_ref_id": source_ref_id,
        "title": _asset()["title"],
        "year": 2014,
        "doi": doi,
        "pmid": pmid,
        "pmcid": pmcid,
        "url": url,
        "source_kind": "method_paper",
        "rationale": "Canonical implementation source.",
        "full_text_locations": [],
    }


def _method(method_id="deseq2", *, source_asset_ids=None, source_hints=None):
    return {
        "method_id": method_id,
        "name": method_id,
        "purpose": "Provide an auditable implementation method.",
        "inventory_reason": "The selected hypothesis requires this method.",
        "source_asset_ids": list(source_asset_ids or []),
        "source_hints": list(source_hints or []),
    }


def _payload(*, assets=None, methods=None):
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "method metadata",
            "purpose": "Resolve exact method identifiers.",
            "status": "completed",
            "receipt": "fixture",
        }],
        "assets": list(assets or []),
        "method_inventory": list(methods or []),
    }


def _persist(project, *, assets=None, methods=None):
    return l4_inventory.persist_discovery(
        l4p,
        dr,
        project,
        "C1",
        _payload(assets=assets, methods=methods),
        _receipt(),
        question="Which method should test H1?",
        claim="H1 predicts differential expression.",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )


def _response(url, payload=A1_XML):
    return {
        "requested_url": url,
        "resolved_url": url,
        "redirect_chain": [],
        "http_status": 200,
        "content_type": "application/xml",
        "body": payload.encode("utf-8"),
    }


def test_inventory_promotes_referenced_reserve_asset(tmp_path):
    manifest = _persist(
        tmp_path,
        assets=[_asset(selection_status="reserve")],
        methods=[_method(source_asset_ids=["A1"])],
    )

    assert manifest["inventory_schema"] == l4_inventory.INVENTORY_SCHEMA_VERSION
    assert manifest["selected_asset_ids"] == ["A1"]
    assert manifest["assets"][0]["selection_status"] == "selected"
    assert manifest["method_inventory"][0]["source_asset_ids"] == ["A1"]
    assert l4p.validate_l4a_manifest(tmp_path, manifest) == (True, "")


def test_inventory_hint_materializes_selected_exact_source(tmp_path):
    manifest = _persist(
        tmp_path,
        assets=[],
        methods=[_method(source_hints=[_hint()])],
    )

    assert len(manifest["assets"]) == 1
    source = manifest["assets"][0]
    assert source["selection_status"] == "selected"
    assert source["doi"] == "10.1186/s13059-014-0550-8"
    assert source["pmid"] == "25516281"
    assert manifest["method_inventory"][0]["source_asset_ids"] == [
        source["asset_id"]
    ]


def test_l4b_mixed_cards_and_gaps_pass_integrity_audit(tmp_path):
    project = tmp_path / "project"
    methods = [
        _method("deseq2", source_hints=[_hint()]),
        _method(
            "combat",
            source_hints=[_hint(
                source_ref_id="combat-source",
                doi="10.1093/biostatistics/kxj037",
                pmid="16632515",
                pmcid="",
                url="https://pubmed.ncbi.nlm.nih.gov/16632515/",
            )],
        ),
    ]
    manifest = _persist(project, assets=[], methods=methods)

    def fetcher(url):
        if "PMC4302049" in url or "s13059-014-0550-8" in url:
            return _response(url)
        raise OSError("fixture source unavailable")

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

    assert artifact["evidence_bundle_schema"] == bundle.EVIDENCE_BUNDLE_SCHEMA
    assert "method_components" not in artifact
    assert "method_candidates" not in artifact
    assert [card["method_id"] for card in artifact["evidence_cards"]] == [
        "deseq2"
    ]
    assert [gap["method_id"] for gap in artifact["evidence_gaps"]] == [
        "combat"
    ]
    assert bundle.audit_bundle(l4p, dr, project, "C1", artifact) == (True, "")
    assert dr.audit_evidence_pack(
        project, "C1", "L4", run_id=artifact["run_id"]
    ) == (True, "")


def test_l4b_no_source_becomes_gap_not_global_failure(tmp_path):
    project = tmp_path / "project"
    manifest = _persist(
        project,
        # Preserve the established L4A invariant that at least one literature
        # asset is selected, while proving that this inventory method itself
        # does not need an exact source to let L4B persist a truthful gap.
        assets=[_asset(selection_status="selected")],
        methods=[_method("unresolved", source_hints=[])],
    )

    artifact = bundle.run_l4b_evidence(
        l4p, dr, project, "C1", manifest, tmp_path / "work", fetcher=None
    )

    assert artifact["evidence_cards"] == []
    assert artifact["evidence_gaps"][0]["method_id"] == "unresolved"
    assert "no exact source identifier" in artifact["evidence_gaps"][0][
        "failure_reason"
    ]
    assert bundle.audit_bundle(l4p, dr, project, "C1", artifact) == (True, "")


def test_l4b_audit_rejects_tampered_source_payload(tmp_path):
    project = tmp_path / "project"
    manifest = _persist(
        project,
        assets=[],
        methods=[_method(source_hints=[_hint()])],
    )
    artifact = bundle.run_l4b_evidence(
        l4p,
        dr,
        project,
        "C1",
        manifest,
        tmp_path / "work",
        fetcher=lambda url: _response(url),
    )
    paper = json.loads((project / artifact["papers"][0]["path"]).read_text(
        encoding="utf-8"
    ))
    (project / paper["source_payload_path"]).write_text(
        "tampered payload", encoding="utf-8"
    )

    ok, reason = bundle.audit_bundle(l4p, dr, project, "C1", artifact)
    assert ok is False
    assert "content hash mismatch" in reason


def _evidence_artifact():
    return {
        "run_id": "C1_L4_bundle",
        "evidence_cards": [{
            "evidence_card_id": "CARD1",
            "method_id": "M1",
            "anchor_id": "ANCHOR1",
            "status": "accepted",
        }],
        "evidence_gaps": [{
            "evidence_gap_id": "GAP1",
            "method_id": "M2",
            "status": "unresolved",
        }],
    }


def _candidate(method_id, *, execution_required, cards=None, gaps=None):
    return {
        "method_id": method_id,
        "component_id": "MC1",
        "status": "eligible",
        "execution_required": execution_required,
        "evidence_card_ids": list(cards or []),
        "evidence_gap_ids": list(gaps or []),
        "method_anchor_ids": ["ANCHOR1"] if cards else [],
    }


def test_required_path_accepts_card_and_allows_optional_gap():
    delta = {
        "deep_research_run_id": "C1_L4_bundle",
        "method_components": [{
            "component_id": "MC1", "name": "model", "required": True,
            "rationale": "required",
        }],
        "method_candidates": [
            _candidate("M1", execution_required=True, cards=["CARD1"]),
            _candidate("M2", execution_required=False, gaps=["GAP1"]),
        ],
    }

    components, candidates = bundle._validate_required_paths(
        dr, _evidence_artifact(), delta
    )
    assert components[0]["required"] is True
    assert len(candidates) == 2


def test_required_path_rejects_gap_as_substitute_for_card():
    delta = {
        "deep_research_run_id": "C1_L4_bundle",
        "method_components": [{
            "component_id": "MC1", "name": "model", "required": True,
            "rationale": "required",
        }],
        "method_candidates": [
            _candidate("M2", execution_required=True, gaps=["GAP1"]),
        ],
    }

    with pytest.raises(dr.DeepResearchError, match="lacks an accepted evidence card"):
        bundle._validate_required_paths(dr, _evidence_artifact(), delta)


def test_required_path_rejects_wrong_evidence_run():
    delta = {
        "deep_research_run_id": "OTHER",
        "method_components": [{
            "component_id": "MC1", "name": "model", "required": True,
            "rationale": "required",
        }],
        "method_candidates": [
            _candidate("M1", execution_required=True, cards=["CARD1"]),
        ],
    }

    with pytest.raises(dr.DeepResearchError, match="deep_research_run_id"):
        bundle._validate_required_paths(dr, _evidence_artifact(), delta)
