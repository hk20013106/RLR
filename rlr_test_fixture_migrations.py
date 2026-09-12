"""Narrow pytest migrations for legacy native fixtures.

These adapters change test setup only. Production ProjectReady, Obsidian, and
formal-runtime gates remain unchanged and fail closed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent
CONTROLLER = ROOT / "research_loop_v04.py"


@pytest.fixture(autouse=True)
def migrate_l0_intake_preflight(request, monkeypatch):
    """Route old L0-intake setup through the canonical ProjectReady helper."""
    if not request.module.__name__.endswith("test_l0_intake"):
        return

    import native_v2_helpers

    module = request.module
    original_run = module._run

    def run_with_project_ready(*args, extra_env=None):
        if args and args[0] == "preflight":
            project = Path(args[1])
            command = [sys.executable, str(CONTROLLER), *args]
            try:
                native_v2_helpers.bootstrap_project_ready(
                    project, CONTROLLER, extra_env=extra_env
                )
            except AssertionError as exc:
                return subprocess.CompletedProcess(
                    command, 3, stdout="", stderr=str(exc)
                )
            return subprocess.CompletedProcess(
                command, 0, stdout="", stderr=""
            )
        return original_run(*args, extra_env=extra_env)

    monkeypatch.setattr(module, "_run", run_with_project_ready)


@pytest.fixture(autouse=True)
def force_formal_runtime_unavailable(request, monkeypatch):
    """Keep runner-ordering tests deterministic on CI hosts already in rlr."""
    if not request.module.__name__.endswith("test_full_dag_authority_closure"):
        return
    if not request.node.name.startswith(
        "test_runner_blocks_before_provider_when_formal_runtime_is_unavailable"
    ):
        return

    import run_loop

    def unavailable_runtime():
        raise run_loop.runtime_preflight.RuntimePreflightError(
            "synthetic unavailable formal runtime fixture"
        )

    monkeypatch.setattr(
        run_loop.runtime_preflight, "require_ready", unavailable_runtime
    )
