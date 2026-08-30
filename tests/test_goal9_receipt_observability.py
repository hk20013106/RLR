from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_loop
from research_loop.providers.command import CommandProvider
from research_loop.providers.base import RunReceipt, ProviderError


def _manifest(tmp_path: Path, context: str = "context") -> Path:
    rendered = tmp_path / "rendered_context.txt"
    rendered.write_text(context, encoding="utf-8")
    manifest = tmp_path / "context_manifest.json"
    manifest.write_text(json.dumps({
        "project_id": "P1",
        "rendered_context_path": str(rendered),
        "rendered_context_sha256": hashlib.sha256(
            rendered.read_bytes()
        ).hexdigest(),
    }), encoding="utf-8")
    return manifest


def _step() -> dict:
    return {
        "tools_policy": "no-fs",
        "everos_read_scopes": [],
        "profile_id": "v2.1-catalog-1",
    }


def _provider_command(tmp_path: Path, mode: str) -> str:
    script = tmp_path / "provider_fixture.py"
    script.write_text(
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "mode, output = sys.argv[1], Path(sys.argv[2])\n"
        "if mode == 'success':\n"
        "    output.write_text(json.dumps({'schema_version': '2.1', 'candidate_id': 'C1'}), encoding='utf-8')\n"
        "    raise SystemExit(0)\n"
        "if mode == 'nonzero':\n"
        "    raise SystemExit(7)\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    return f'"{sys.executable}" "{script}" {mode} "{{output_file}}"'


def test_successful_command_call_persists_provider_exit_and_timeout(
    tmp_path
):
    run_dir = tmp_path / "run"
    delta = {"schema_version": "2.1", "candidate_id": "C1"}
    provider = CommandProvider({
        "command": _provider_command(tmp_path, "success"),
    })
    assert provider.run_agent(
        "L1", "Einstein", "context", run_dir=str(run_dir)
    ) == delta
    config = tmp_path / "runner.yaml"
    config.write_text("mode: headless\n", encoding="utf-8")

    receipt_path = run_loop.write_receipt(
        run_dir, "L1", "Einstein", provider, "context", _step(), "C1", "1",
        manifest=str(_manifest(tmp_path)), provider_delta_file=provider.last_delta_file,
        config_path=config,
    )
    receipt = RunReceipt.read(receipt_path)

    assert receipt.schema_version == "RunReceipt/v2"
    assert receipt.exit_code == 0
    assert receipt.timed_out is False
    assert receipt.terminal_state == "completed"


@pytest.mark.parametrize(
    ("mode", "expected_returncode", "timed_out", "terminal_state"),
    [("timeout", None, True, "timed_out"), ("nonzero", 7, False, "provider_failed")],
)
def test_failed_command_call_preserves_execution_metadata_and_persists_receipt(
    tmp_path, mode, expected_returncode, timed_out, terminal_state
):
    run_dir = tmp_path / "run"
    provider = CommandProvider({
        "command": _provider_command(tmp_path, mode),
        "timeout": 0.2 if timed_out else None,
    })
    with pytest.raises(ProviderError) as excinfo:
        provider.run_agent(
            "L4", "Fisher", "context", run_dir=str(run_dir)
        )

    error = excinfo.value
    if expected_returncode is not None:
        assert error.returncode == expected_returncode
    else:
        assert error.returncode == provider.last_exit_code
    assert error.timed_out is timed_out
    assert error.terminal_state == terminal_state
    config = tmp_path / "runner.yaml"
    config.write_text("mode: headless\n", encoding="utf-8")

    receipt_path = run_loop.write_receipt(
        run_dir, "L4", "Fisher", provider, "context", _step(), "C1", "1",
        manifest=str(_manifest(tmp_path)), execution_status="failed",
        config_path=config,
    )
    receipt = RunReceipt.read(receipt_path)

    assert receipt.schema_version == "RunReceipt/v2"
    assert receipt.exit_code == error.returncode
    assert receipt.timed_out is timed_out
    assert receipt.terminal_state == terminal_state
    assert receipt.execution_status == "failed"
    assert receipt.provider_delta_path == ""


def test_historical_v2_receipt_without_execution_fields_remains_readable(tmp_path):
    payload = {
        "node": "L1",
        "persona": "Einstein",
        "provider": "command",
        "timestamp": "2026-08-30T00:00:00",
        "context_hash": "a" * 64,
        "project_id": "P1",
        "candidate_id": "C1",
        "round_id": "1",
        "profile_id": "v2.1-catalog-1",
        "context_manifest_path": "manifest.json",
        "context_manifest_hash": "b" * 64,
        "rendered_context_path": "context.txt",
        "rendered_context_hash": "a" * 64,
        "prompt_file": "prompt.txt",
        "prompt_hash": "c" * 64,
        "provider_delta_path": "delta.json",
        "provider_delta_hash": "d" * 64,
        "raw_provider_delta_path": "delta.json",
        "raw_provider_delta_hash": "d" * 64,
        "git_head": "e" * 40,
        "git_dirty": False,
        "working_tree_diff_sha256": "f" * 64,
        "config_sha256": "0" * 64,
        "code_state_id": "1" * 64,
        "schema_version": "RunReceipt/v2",
    }
    path = tmp_path / "historical-v2.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    receipt = RunReceipt.read(path)

    assert receipt.schema_version == "RunReceipt/v2"
    assert receipt.exit_code is None
    assert receipt.timed_out is None


def test_exec_cognitive_persists_failure_receipt_before_classification(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    manifest = _manifest(tmp_path)
    provider = CommandProvider({
        "command": _provider_command(tmp_path, "nonzero"),
    })
    monkeypatch.setattr(
        run_loop, "assemble_context",
        lambda *args, **kwargs: ("context", str(manifest)),
    )
    monkeypatch.setattr(run_loop, "provider_for", lambda *args, **kwargs: provider)
    monkeypatch.setattr(run_loop, "_provider_output_schema", lambda *args: None)
    monkeypatch.setattr(run_loop, "auto_pitfall", lambda *args, **kwargs: None)
    config = tmp_path / "runner.yaml"
    config.write_text("mode: headless\n", encoding="utf-8")
    cfg = SimpleNamespace(data={}, source_path=str(config))
    args = SimpleNamespace(evidence_run_ids={}, provider=None)
    state = {"loopx_policy": run_loop.LoopXRetryPolicy(retry_threshold=2)}
    run_dir = tmp_path / "run"

    assert run_loop.exec_cognitive(
        str(project), "C1", {"node": "L4", "persona": "Fisher"},
        cfg, args, run_dir, "1", failure_state=state,
    ) is False

    receipt = RunReceipt.read(run_dir / "L4_Fisher_receipt.json")
    assert receipt.execution_status == "failed"
    assert receipt.exit_code == 7
    assert receipt.timed_out is False
    assert state["last_loopx_failure"]["failure_class"] == "EXTERNAL"
