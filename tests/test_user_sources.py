import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _project(tmp_path: Path, candidate_id: str = "C1") -> tuple[Path, str]:
    project = tmp_path / "P"
    (project / "01_Candidates").mkdir(parents=True)
    (project / "01_Candidates" / f"{candidate_id}.md").write_text(
        f"---\ncandidate_id: {candidate_id}\ncurrent_status: IDEA_SELECTED\n---\n",
        encoding="utf-8",
    )
    return project, candidate_id


def _pdf(path: Path, payload: bytes = b"sample methods text") -> bytes:
    data = b"%PDF-1.7\n" + payload + b"\n%%EOF\n"
    path.write_bytes(data)
    return data


def test_register_pdf_copies_bytes_and_records_sha256(tmp_path):
    from research_loop.user_sources import register_pdf

    project, candidate_id = _project(tmp_path)
    source = tmp_path / "paper.pdf"
    original = _pdf(source)

    record = register_pdf(project, candidate_id, source, doi="10.1000/test")

    stored = project / record["stored_path"]
    sidecar = stored.with_suffix(".json")
    assert stored.read_bytes() == original
    assert record["sha256"] == hashlib.sha256(original).hexdigest()
    assert record["bytes"] == len(original)
    assert record["status"] == "registered"
    assert record["doi"] == "10.1000/test"
    assert record["registration_satisfies_l4"] is False
    assert json.loads(sidecar.read_text(encoding="utf-8"))["user_source_id"] == record["user_source_id"]


def test_register_pdf_is_idempotent_for_same_candidate_and_hash_even_if_renamed(tmp_path):
    from research_loop.user_sources import register_pdf

    project, candidate_id = _project(tmp_path)
    source = tmp_path / "paper.pdf"
    data = _pdf(source)
    renamed = tmp_path / "renamed-copy.pdf"
    renamed.write_bytes(data)

    first = register_pdf(project, candidate_id, source)
    second = register_pdf(project, candidate_id, renamed)

    assert second == first
    directory = project / "09_Literature_Database" / "user_sources" / candidate_id
    assert len(list(directory.glob("*.pdf"))) == 1
    assert len(list(directory.glob("*.json"))) == 1


def test_register_pdf_rejects_non_pdf_and_unknown_candidate(tmp_path):
    from research_loop.user_sources import UserSourceError, register_pdf

    project, candidate_id = _project(tmp_path)
    not_pdf = tmp_path / "paper.pdf"
    not_pdf.write_text("not a PDF", encoding="utf-8")

    with pytest.raises(UserSourceError, match="PDF"):
        register_pdf(project, candidate_id, not_pdf)
    valid = tmp_path / "valid.pdf"
    _pdf(valid)
    with pytest.raises(UserSourceError, match="candidate"):
        register_pdf(project, "C404", valid)


def test_registered_sources_are_candidate_scoped(tmp_path):
    from research_loop.user_sources import register_pdf, registered_sources, verify_registered_source

    project, c1 = _project(tmp_path, "C1")
    (project / "01_Candidates" / "C2.md").write_text(
        "---\ncandidate_id: C2\ncurrent_status: IDEA_SELECTED\n---\n",
        encoding="utf-8",
    )
    source = tmp_path / "paper.pdf"
    _pdf(source)
    record = register_pdf(project, c1, source)

    assert registered_sources(project, c1) == [record]
    assert registered_sources(project, "C2") == []
    assert verify_registered_source(project, c1, record["user_source_id"], record["sha256"]) == (True, "")
    ok, reason = verify_registered_source(project, "C2", record["user_source_id"], record["sha256"])
    assert ok is False and "candidate" in reason.lower()


def test_standalone_script_prints_registration_json(tmp_path):
    project, candidate_id = _project(tmp_path)
    source = tmp_path / "paper.pdf"
    _pdf(source)

    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "import_literature_pdf.py"),
         str(project), candidate_id, "--file", str(source), "--pmid", "123456"],
        capture_output=True, text=True, encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["pmid"] == "123456"
    assert result["status"] == "registered"
    assert result["registration_satisfies_l4"] is False
    assert "sha256" in result and "stored_path" in result
