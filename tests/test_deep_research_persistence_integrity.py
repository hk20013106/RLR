import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from research_loop import deep_research as wrapped_deep_research
from research_loop.api import EngineAPI
from research_loop.compatibility import PROFILE_V21_CATALOG_1
from research_loop.hypothesis_ledger import HypothesisLedger

ROOT = Path(__file__).resolve().parent.parent
DEEP_RESEARCH_PATH = ROOT / "src" / "research_loop" / "deep_research.py"


def _load_canonical_module():
    """Load deep_research.py without package-level runtime installers."""
    module_name = "_rlr_canonical_deep_research_integrity_test"
    spec = importlib.util.spec_from_file_location(module_name, DEEP_RESEARCH_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _payload(module, source_payload: str) -> dict:
    return {
        "schema_version": module.SCHEMA_VERSION,
        "queries": ["fixture query"],
        "papers": [{
            "doi": "10.1000/canonical-source-bytes",
            "pmid": "12345678",
            "url": "https://example.org/canonical-source-bytes",
            "title": "Canonical source byte fixture",
            "source_database": "fixture",
            "metadata": {"year": 2026, "journal": "Fixture"},
            "source_metadata_response": {
                "id": "12345678",
                "title": "Canonical source byte fixture",
            },
            "open_access": True,
            "content_type": "application/xml; type=jats",
            "source_payload": source_payload,
            "paper_type": "primary",
            "extracts": [{
                "section": section,
                "text": text,
                "locator": locator,
                "extraction_method": "fixture",
                "verification_status": "located",
            } for section, text, locator in [
                ("Results", "Observed result.", "Results paragraph 1"),
                ("Discussion", "Interpreted result.", "Discussion paragraph 1"),
                ("Conclusion", "Concluding result.", "Conclusion paragraph 1"),
                (
                    "Materials and methods",
                    "Method details for the retained source.",
                    "Methods paragraph 1",
                ),
            ]],
        }],
        "review_search": {
            "query": "fixture review",
            "status": "none_found",
            "receipt": "fixture 0",
        },
        "verification": [],
    }


def _host_receipt(tmp_path, monkeypatch, module, payload, *, source="declared", node="L4"):
    store = tmp_path / "hypotheses.sqlite"
    ledger = HypothesisLedger(store)
    binding = ledger.bind_project(
        tmp_path, "PROJECT:host-literature-test",
        profile_id=PROFILE_V21_CATALOG_1,
    )
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(store))
    cursor = ledger.snapshot_candidate(tmp_path, "C1", "1")
    raw_response = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    response_input = tmp_path / "host-response-submission.json"
    response_input.write_bytes(raw_response)
    request = EngineAPI().prepare_host_request(
        tmp_path,
        kind="literature",
        identity={
            "project_id": str(binding["project_id"]),
            "candidate_id": "C1", "round_id": "1", "node": node,
            "persona": "Curie", "profile_id": PROFILE_V21_CATALOG_1,
            "stage": "literature_review", "attempt": 1, "cursor": cursor,
        },
        inputs={"payload_sha256": hashlib.sha256(raw_response).hexdigest()},
        tools_policy="literature-only",
        output_contract={"type": "object", "schema_version": module.SCHEMA_VERSION},
    )
    response = EngineAPI().submit_host_response(
        tmp_path, request["request_id"], response_input, expected_cursor=cursor
    )
    return {
        "schema_version": "DeepResearchHostReceipt/v1",
        "source": "host_session",
        "request_id": request["request_id"],
        "host_request_path": request["request_path"],
        "host_request_sha256": request["request_sha256"],
        "raw_response_path": response["raw_response_path"],
        "raw_response_sha256": response["raw_response_sha256"],
        "host_session_id": "declared-session-1" if source == "declared" else None,
        "host_session_id_source": source,
    }


def test_canonical_persist_run_writes_exact_utf8_source_bytes(monkeypatch, tmp_path):
    module = _load_canonical_module()
    source_payload = "<article>\n<section>alpha</section>\n</article>\n"
    expected_bytes = source_payload.encode("utf-8")
    expected_hash = hashlib.sha256(expected_bytes).hexdigest()
    original_write_text = Path.write_text

    def windows_style_write_text(path, data, *args, **kwargs):
        normalized = str(path).replace("\\", "/")
        if "/evidence_packs/sources/" in normalized:
            data = data.replace("\n", "\r\n")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", windows_style_write_text)
    artifact = module.persist_run(
        tmp_path,
        "C1",
        "L4",
        _payload(module, source_payload),
        module.skill_receipt(
            "codex", ["codex", "exec"], "prompt", "fixture"
        ),
    )

    paper_path = tmp_path / artifact["papers"][0]["path"]
    paper = json.loads(paper_path.read_text(encoding="utf-8"))
    source_path = tmp_path / paper["source_payload_path"]
    persisted_bytes = source_path.read_bytes()

    assert source_path.suffix == ".xml"
    assert persisted_bytes == expected_bytes
    assert len(persisted_bytes) == len(expected_bytes)
    assert paper["content_hash"] == expected_hash
    assert {item["source_hash"] for item in paper["evidence_extracts"]} == {
        expected_hash
    }
    assert hashlib.sha256(persisted_bytes).hexdigest() == expected_hash


def test_host_literature_receipt_persists_and_audits_without_subprocess_claims(
    tmp_path, monkeypatch
):
    module = _load_canonical_module()
    source_payload = "<article>host-reviewed evidence</article>\n"
    payload = _payload(module, source_payload)
    receipt = _host_receipt(tmp_path, monkeypatch, module, payload)

    artifact = module.persist_run(
        tmp_path, "C1", "L4", payload, receipt,
        project_id="PROJECT:host-literature-test", round_id="1",
        profile_id="v2.1-catalog-1", research_persona="Curie",
    )

    assert artifact["skill_receipt"] == receipt
    valid, reason = module.audit_evidence_pack(
        tmp_path, "C1", "L4", run_id=artifact["run_id"]
    )
    assert valid, reason


def test_host_literature_audit_rechecks_raw_response_bytes(tmp_path, monkeypatch):
    module = _load_canonical_module()
    payload = _payload(module, "<article>host-reviewed evidence</article>\n")
    receipt = _host_receipt(
        tmp_path, monkeypatch, module, payload, source="unavailable"
    )
    artifact = module.persist_run(
        tmp_path, "C1", "L4", payload, receipt,
        project_id="PROJECT:host-literature-test", round_id="1",
        profile_id="v2.1-catalog-1", research_persona="Curie",
    )
    Path(receipt["raw_response_path"]).write_bytes(
        Path(receipt["raw_response_path"]).read_bytes() + b"tampered"
    )

    valid, reason = module.audit_evidence_pack(
        tmp_path, "C1", "L4", run_id=artifact["run_id"]
    )

    assert not valid
    assert "host" in reason.lower() or "response" in reason.lower()


@pytest.mark.parametrize("node", ["L4", "L8.5"])
def test_package_receipt_owner_dispatches_host_literature_receipt(
    tmp_path, monkeypatch, node
):
    payload = _payload(
        wrapped_deep_research, "<article>package owner host bytes</article>\n"
    )
    if node == "L8.5":
        payload["verification"] = [{
            "finding": "H1 predicts the observed method outcome",
            "verdict": "supports",
            "evidence_ids": ["10.1000/canonical-source-bytes"],
        }]
    receipt = _host_receipt(
        tmp_path, monkeypatch, wrapped_deep_research, payload, node=node
    )

    artifact = wrapped_deep_research.persist_run(
        tmp_path, "C1", node, payload, receipt, result_context="authorized host context",
        project_id="PROJECT:host-literature-test", round_id="1",
        profile_id="v2.1-catalog-1", research_persona="Curie",
    )
    valid, reason = wrapped_deep_research.audit_evidence_pack(
        tmp_path, "C1", node, run_id=artifact["run_id"]
    )
    assert valid, reason
