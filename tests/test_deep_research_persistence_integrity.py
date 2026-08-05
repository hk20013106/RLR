import hashlib
import importlib.util
import json
import sys
from pathlib import Path


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
