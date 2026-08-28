import json

import pytest

from research_loop import l4_method_registry as registry


def _method(method_id="differential_expression_deseq2", name="DESeq2"):
    return {
        "method_id": method_id,
        "name": name,
        "purpose": "Test differential expression.",
        "inventory_reason": "Required by H1.",
        "source_asset_ids": [],
        "source_hints": [],
    }


def test_builtin_registry_adds_deseq2_canonical_source(tmp_path):
    inventory, receipt = registry.apply_registry(tmp_path, [_method()])

    hint = inventory[0]["source_hints"][0]
    assert hint["doi"] == "10.1186/s13059-014-0550-8"
    assert hint["pmid"] == "25516281"
    assert hint["pmcid"] == "PMC4302049"
    assert receipt["matches"] == [{
        "method_id": "differential_expression_deseq2",
        "canonical_method_ids": ["deseq2"],
    }]


def test_builtin_registry_adds_url_bound_bh_fdr_implementation_source(tmp_path):
    inventory, receipt = registry.apply_registry(
        tmp_path,
        [_method(
            method_id="multiple_testing_fdr",
            name="Benjamini-Hochberg false-discovery-rate control",
        )],
    )

    hint = inventory[0]["source_hints"][0]
    assert hint["source_ref_id"] == "r-stats-p-adjust"
    assert hint["doi"] == ""
    assert hint["pmid"] == ""
    assert hint["pmcid"] == ""
    assert hint["url"] == (
        "https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html"
    )
    assert hint["source_kind"] == "official_documentation"
    assert receipt["matches"] == [{
        "method_id": "multiple_testing_fdr",
        "canonical_method_ids": ["multiple_testing_fdr"],
    }]


def test_registry_does_not_add_unmentioned_methods(tmp_path):
    inventory, receipt = registry.apply_registry(
        tmp_path, [_method(method_id="wgcna", name="WGCNA")]
    )

    assert inventory[0]["source_hints"] == []
    assert receipt["matches"] == []


def test_project_registry_overrides_builtin_entry(tmp_path):
    path = tmp_path / "09_Literature_Database/l4/method_source_registry.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "schema_version": registry.REGISTRY_SCHEMA_VERSION,
        "methods": [{
            "canonical_method_id": "deseq2",
            "aliases": ["deseq2"],
            "source_hints": [{
                "source_ref_id": "project-deseq2-doc",
                "title": "Project-approved DESeq2 documentation",
                "year": 2026,
                "doi": "",
                "pmid": "",
                "pmcid": "",
                "url": "https://bioconductor.org/packages/DESeq2/",
                "source_kind": "official_documentation",
                "rationale": "Project-approved canonical implementation source.",
                "full_text_locations": [
                    "https://bioconductor.org/packages/DESeq2/"
                ],
            }],
        }],
    }), encoding="utf-8")

    inventory, receipt = registry.apply_registry(tmp_path, [_method()])

    assert inventory[0]["source_hints"] == [{
        "source_ref_id": "project-deseq2-doc",
        "title": "Project-approved DESeq2 documentation",
        "year": 2026,
        "doi": "",
        "pmid": "",
        "pmcid": "",
        "url": "https://bioconductor.org/packages/DESeq2/",
        "source_kind": "official_documentation",
        "rationale": "Project-approved canonical implementation source.",
        "full_text_locations": [
            "https://bioconductor.org/packages/DESeq2/"
        ],
    }]
    assert receipt["project_sha256"]


def test_malformed_project_registry_fails_closed(tmp_path):
    path = tmp_path / "09_Literature_Database/l4/method_source_registry.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(registry.MethodRegistryError, match="fields are invalid"):
        registry.apply_registry(tmp_path, [_method()])
