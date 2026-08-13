from __future__ import annotations

import json
import sys
from pathlib import Path

from research_loop import deep_research
from research_loop import l4_inventory
from research_loop import method_evidence
from research_loop import method_review_navigation
from research_loop.provider_runtime_observability import _CONTEXT


FIXTURE = Path(__file__).parent / "fixtures" / "fake_codex_jsonl.py"


def test_native_l4a_inventory_provider_boundary_is_observed():
    """The native L4A owner must share PR #14's subprocess runtime proxy."""
    assert l4_inventory.subprocess is deep_research.subprocess


def test_active_deep_research_provider_boundary_is_observed(tmp_path, monkeypatch):
    """The final installed run_and_persist owner must not bypass the runtime proxy."""
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    runtime_dir = tmp_path / "runtime"
    legacy_final = tmp_path / "deep_research_final_output.json"
    context = {
        "runtime_dir": runtime_dir,
        "task_id": "dr-integration",
        "candidate_id": "C1",
        "node": "L1",
        "backend": "codex",
        "prompt": "integration fixture prompt",
        "execution": None,
    }
    token = _CONTEXT.set(context)
    try:
        completed = method_review_navigation.subprocess.run(
            [
                sys.executable,
                str(FIXTURE),
                "exec",
                "--json",
                "--output-last-message",
                str(legacy_final),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=3,
            check=False,
        )
    finally:
        _CONTEXT.reset(token)

    assert completed.returncode == 0
    assert context["execution"] is not None
    assert (runtime_dir / "events.jsonl").stat().st_size > 0
    final = json.loads((runtime_dir / "final_output.json").read_text(encoding="utf-8"))
    assert final["schema_version"] == "1.0"
    assert (runtime_dir / "runtime_receipt.json").is_file()
    assert method_review_navigation.subprocess is deep_research.subprocess
    assert method_evidence.subprocess is deep_research.subprocess
