import json
import sys
from pathlib import Path

from research_loop import deep_research as dr
from research_loop import l4_inventory
from research_loop import l4_pipeline as l4p
from research_loop.provider_runtime_observability import _CONTEXT


FIXTURE = Path(__file__).parent / "fixtures" / "fake_codex_jsonl.py"


def test_inventory_wire_schema_omits_unsupported_unique_items():
    schema = l4_inventory.discovery_schema(l4p)

    def walk(value):
        if isinstance(value, dict):
            if "uniqueItems" in value:
                yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    assert list(walk(schema)) == []


def _payload():
    return {
        "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
        "queries": [{
            "query_id": "Q1",
            "query": "DESeq2 method paper",
            "purpose": "Resolve the canonical source.",
            "status": "completed",
            "receipt": "fixture",
        }],
        "assets": [{
            "asset_id": "A1",
            "doi": "10.1186/s13059-014-0550-8",
            "pmid": "25516281",
            "url": "https://pubmed.ncbi.nlm.nih.gov/25516281/",
            "title": "Moderated estimation with DESeq2",
            "year": 2014,
            "role": "method",
            "journal": "Genome Biology",
            "abstract": "metadata",
            "source_database": "PubMed",
            "source_metadata_response": json.dumps(
                {"pmcid": "PMC4302049"}, sort_keys=True, separators=(",", ":")
            ),
            "open_access_status": "open",
            "full_text_status": "available_oa",
            "full_text_locations": [
                "https://pmc.ncbi.nlm.nih.gov/articles/PMC4302049/"
            ],
            "relevance_score": 10.0,
            "selection_status": "selected",
            "selection_reason": "Canonical source.",
            "hypothesis_ids": ["H1"],
            "method_component_hints": ["deseq2"],
            "diagnostic_requirements": [],
        }],
        "method_inventory": [{
            "method_id": "deseq2",
            "name": "DESeq2",
            "purpose": "Differential-expression modelling.",
            "inventory_reason": "Required by H1.",
            "source_asset_ids": ["A1"],
            "source_hints": [],
        }],
    }


def test_inventory_manifest_identical_retry_is_idempotent(tmp_path):
    receipt = dr.skill_receipt(
        "codex", ["codex", "exec"], "prompt", "fixture"
    )
    kwargs = {
        "question": "Which method tests H1?",
        "claim": "H1 predicts differential expression.",
        "project_id": "P1",
        "round_id": "1",
        "profile_id": "v2.1-catalog-1",
    }

    first = l4_inventory.persist_discovery(
        l4p, dr, tmp_path, "C1", _payload(), receipt, **kwargs
    )
    second = l4_inventory.persist_discovery(
        l4p, dr, tmp_path, "C1", _payload(), receipt, **kwargs
    )

    assert second == first
    assert first["manifest_sha256"]
    assert len(list(tmp_path.glob(
        "09_Literature_Database/l4/discovery/manifests/*.json"
    ))) == 1


def test_native_manifest_validator_requires_nonempty_inventory_and_selected_assets(
    tmp_path,
):
    receipt = dr.skill_receipt(
        "codex", ["codex", "exec"], "prompt", "fixture"
    )
    legacy = l4p.persist_l4a_discovery(
        tmp_path,
        "C1",
        {
            "schema_version": l4p.L4A_DISCOVERY_SCHEMA_VERSION,
            "queries": [{
                "query_id": "Q1",
                "query": "legacy metadata query",
                "purpose": "Fixture legacy L4A discovery.",
                "status": "completed",
                "receipt": "fixture",
            }],
            "assets": _payload()["assets"],
        },
        receipt,
        question="Q",
        claim="H",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )

    ok, reason = l4p.validate_native_l4a_manifest(tmp_path, legacy)

    assert ok is False
    assert reason.startswith("LEGACY_L4A_MANIFEST_INCOMPATIBLE")


def test_native_manifest_validator_rejects_unregistered_inventory_source(tmp_path):
    receipt = dr.skill_receipt(
        "codex", ["codex", "exec"], "prompt", "fixture"
    )
    manifest = l4_inventory.persist_discovery(
        l4p,
        dr,
        tmp_path,
        "C1",
        _payload(),
        receipt,
        question="Q",
        claim="H",
        project_id="P1",
        round_id="1",
        profile_id="v2.1-catalog-1",
    )
    tampered = dict(manifest)
    tampered["method_inventory"] = [
        dict(manifest["method_inventory"][0], source_asset_ids=["MISSING"])
    ]
    tampered["manifest_sha256"] = l4p._sha256_json(
        {key: value for key, value in tampered.items() if key != "manifest_sha256"}
    )
    path = tmp_path / manifest["path"]
    path.write_text(
        json.dumps(tampered, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    ok, reason = l4p.validate_native_l4a_manifest(tmp_path, tampered)

    assert ok is False
    assert "source_asset_ids" in reason


def test_l4_inventory_codex_jsonl_owner_uses_observability_proxy(
    monkeypatch, tmp_path
):
    payload = _payload()
    observed_stdout = []

    monkeypatch.setattr(
        dr,
        "build_invocation",
        lambda *args, **kwargs: (
            [sys.executable, str(FIXTURE), "exec", "--json", "--output-last-message", str(tmp_path / "final.json")],
            "inventory prompt",
        ),
    )
    monkeypatch.setattr(dr, "resolve_subprocess_executable", lambda command: command)
    monkeypatch.setattr(
        dr,
        "subprocess_invocation",
        lambda command, prompt: (command, {}),
    )
    monkeypatch.setattr(
        dr,
        "_parse_cli_output",
        lambda stdout: observed_stdout.append(stdout) or payload,
    )
    context = {
        "runtime_dir": tmp_path / "runtime",
        "task_id": "l4a-inventory-jsonl",
        "candidate_id": "C1",
        "node": "L4",
        "backend": "codex",
        "prompt": "inventory prompt",
        "execution": None,
    }
    token = _CONTEXT.set(context)
    try:
        manifest = l4_inventory.run_discovery(
            l4p,
            dr,
            tmp_path / "project",
            "C1",
            "Q",
            "H",
            dr.RuntimeSpec("codex", sys.executable, timeout=3),
            tmp_path / "work",
            project_id="P1",
            round_id="1",
            profile_id="v2.1-catalog-1",
        )
    finally:
        _CONTEXT.reset(token)

    assert manifest["inventory_schema"] == l4_inventory.INVENTORY_SCHEMA_VERSION
    assert manifest["method_inventory"]
    assert len(observed_stdout) == 1
    json.loads(observed_stdout[0])
    assert context["execution"] is not None
    assert (context["runtime_dir"] / "events.jsonl").stat().st_size > 0
    assert (context["runtime_dir"] / "stderr.log").stat().st_size > 0
    assert (context["runtime_dir"] / "runtime_receipt.json").is_file()
