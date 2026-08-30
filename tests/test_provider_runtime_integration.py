from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("prompt_transport", ["stdin", "argv"])
def test_runtime_receipt_hashes_actual_provider_prompt(
    tmp_path, monkeypatch, prompt_transport
):
    """Receipt provenance must bind the prompt physically sent to the provider."""
    monkeypatch.setenv("RLR_FAKE_CODEX_MODE", "stream")
    monkeypatch.setenv("RLR_FAKE_CODEX_DELAY", "0.01")
    runtime_dir = tmp_path / f"runtime-{prompt_transport}"
    legacy_final = tmp_path / f"final-{prompt_transport}.json"
    stale_context_prompt = "stale generic L4 prompt that was not executed"
    actual_prompt = f"actual L4A method-inventory prompt via {prompt_transport}"
    context = {
        "runtime_dir": runtime_dir,
        "task_id": f"dr-prompt-{prompt_transport}",
        "candidate_id": "C1",
        "node": "L4",
        "backend": "codex",
        "prompt": stale_context_prompt,
        "execution": None,
    }
    command = [
        sys.executable,
        str(FIXTURE),
        "exec",
        "--json",
        "--output-last-message",
        str(legacy_final),
    ]
    invocation_kwargs = {}
    if prompt_transport == "stdin":
        invocation_kwargs["input"] = actual_prompt
    else:
        command.append(actual_prompt)

    token = _CONTEXT.set(context)
    try:
        completed = deep_research.execute_provider_invocation(
            command,
            invocation_kwargs,
            timeout=3,
        )
    finally:
        _CONTEXT.reset(token)

    assert completed.returncode == 0
    receipt = json.loads((runtime_dir / "runtime_receipt.json").read_text(encoding="utf-8"))
    expected_hash = hashlib.sha256(actual_prompt.encode("utf-8")).hexdigest()
    stale_hash = hashlib.sha256(stale_context_prompt.encode("utf-8")).hexdigest()
    assert receipt["prompt_hash"] == expected_hash
    assert receipt["prompt_hash"] != stale_hash
