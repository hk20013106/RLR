# -*- coding: utf-8 -*-
"""Regression tests for Obsidian vault validation."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sync_to_obsidian

RL = str(Path(__file__).resolve().parent / "research_loop_v04.py")


def _make_project(root):
    project = Path(root) / "ProjectA"
    project.mkdir()
    (project / "00_Project_Index.md").write_text("""---
project_name: ProjectA
kind: project_index
created_at: 2026-01-01T00:00:00
---
# ProjectA
""", encoding="utf-8")
    cand = project / "01_Candidates"
    cand.mkdir()
    (cand / "C1.md").write_text("""---
candidate_id: C1
title: Test Candidate
question: Does X cause Y?
claim: X causes Y
current_status: KEEP
current_owner: Oppenheimer
---
# Test Candidate
""", encoding="utf-8")
    return project


def test_sync_script_rejects_non_obsidian_vault():
    with tempfile.TemporaryDirectory() as d:
        project = _make_project(d)
        fake_vault = Path(d) / "not_a_vault"
        fake_vault.mkdir()

        rc = sync_to_obsidian.sync_project(str(project), vault_dir=str(fake_vault))

        assert rc == 1
        assert not (fake_vault / "ResearchLoop").exists()


def test_controller_obsidian_sync_rejects_non_obsidian_vault():
    with tempfile.TemporaryDirectory() as d:
        project = _make_project(d)
        fake_vault = Path(d) / "not_a_vault"
        fake_vault.mkdir()

        r = subprocess.run([
            sys.executable, RL, "obsidian-sync", str(project),
            "--vault", str(fake_vault),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")

        assert r.returncode != 0
        assert ".obsidian" in r.stderr
        assert not (fake_vault / "ResearchLoop").exists()


def test_controller_obsidian_sync_uses_human_readable_entrypoint():
    with tempfile.TemporaryDirectory() as d:
        project = _make_project(d)
        vault = Path(d) / "vault"
        (vault / ".obsidian").mkdir(parents=True)

        r = subprocess.run([
            sys.executable, RL, "obsidian-sync", str(project),
            "--vault", str(vault),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")

        assert r.returncode == 0, f"exit={r.returncode} stderr={r.stderr}"
        assert (vault / "ResearchLoop" / "ProjectA" / "00_Index.md").exists()
        assert not (vault / "ResearchLoop" / "ProjectA" /
                    "00_Obsidian_Index.md").exists()


def test_sync_script_preserves_existing_audit_dir():
    with tempfile.TemporaryDirectory() as d:
        project = _make_project(d)
        vault = Path(d) / "vault"
        (vault / ".obsidian").mkdir(parents=True)
        audit_dir = vault / "ResearchLoop" / "ProjectA" / "08_Audit"
        audit_dir.mkdir(parents=True)
        marker = audit_dir / "context_manifest_keep.json"
        marker.write_text("{}", encoding="utf-8")

        rc = sync_to_obsidian.sync_project(str(project), vault_dir=str(vault))

        assert rc == 0
        assert marker.exists(), "sync_to_obsidian.py must not delete audit trail"


def _run_as_script():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_as_script())
