"""Repository-level test fixtures for external runtime presence checks.

These fixtures keep CI hermetic.  They never execute Codex; they only provide a
PATH-visible sentinel for tests whose scope is PROJECT_READY/L0 behavior rather
than external CLI installation.  Real Codex availability is exercised by local
acceptance/E2E runs, not GitHub Actions.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def test_only_codex_path_sentinel(request, tmp_path: Path, monkeypatch):
    """Expose a fake ``codex`` executable only to positive preflight fixtures.

    Keep tests that intentionally exercise a missing provider untouched.
    ``structured_execution.runtime_ready`` only calls ``shutil.which`` in these
    positive fixtures; the sentinel is never launched.
    """
    module_name = request.module.__name__
    needs_sentinel = module_name.endswith("test_l0_intake") or (
        module_name.endswith("test_runtime_plumbing")
        and request.node.name == "test_cold_start_formal_l0_run_stops_after_receipt"
    )
    if not needs_sentinel:
        return

    bin_dir = tmp_path / "fake-provider-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        executable = bin_dir / "codex.cmd"
        executable.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
    else:
        executable = bin_dir / "codex"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    current_path = os.environ.get("PATH", "")
    monkeypatch.setenv(
        "PATH",
        str(bin_dir) + (os.pathsep + current_path if current_path else ""),
    )
