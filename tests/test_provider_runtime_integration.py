from __future__ import annotations

import json
import sys
from pathlib import Path

from research_loop import deep_research
from research_loop import l4_inventory
from research_loop import l4_pipeline
from research_loop import method_evidence
from research_loop import method_review_navigation
from research_loop.provider_runtime_observability import _CONTEXT


FIXTURE = Path(__file__).parent / "fixtures" / "fake_codex_jsonl.py"


def test_l4_wrappers_do_not_own_provider_processes():
    """L4 extensions keep scientific contracts but delegate provider execution."""
    assert callable(deep_research.execute_provider_invocation)
    for module in (
        l4_inventory,
        l4_pipeline,
        method_evidence,
        method_review_navigation,
    ):
        assert not hasattr(module, "subprocess")
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "execute_provider_invocation(" in source


def test_active_deep_research_provider_boundary_is_observed(tmp_path, monkeypatch):
    """The canonical provider invocation helper feeds the JSONL observer."""
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
        completed = deep_research.execute_provider_invocation(
            [
                sys.executable,
                str(FIXTURE),
                "exec",
                "--json",
                "--output-last-message",
                str(legacy_final),
            ],
            {},
            timeout=3,
        )
    finally:
        _CONTEXT.reset(token)

    assert completed.returncode == 0
    assert context["execution"] is not None
    assert (runtime_dir / "events.jsonl").stat().st_size > 0
    final = json.loads((runtime_dir / "final_output.json").read_text(encoding="utf-8"))
    assert final["schema_version"] == "1.0"
    assert (runtime_dir / "runtime_receipt.json").is_file()
