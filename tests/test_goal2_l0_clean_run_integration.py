"""Replay the Goal 2 L0 provider-to-receipt boundary without network access."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import run_loop
from research_loop.providers.command import CommandProvider


HERE = Path(__file__).resolve().parent.parent
CONTROLLER = HERE / "research_loop_v04.py"


def _run_controller(*args, env):
    return subprocess.run(
        [sys.executable, str(CONTROLLER), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def test_l0_replay_uses_persisted_context_bytes_before_receipt(tmp_path, monkeypatch):
    """Exercise the real L0 context/API/provider/receipt chain with a replay."""
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    env["RLR_HYPOTHESIS_STORE"] = str(tmp_path / "hypotheses.sqlite")
    project = tmp_path / "project"

    created = _run_controller(
        "new-project", str(project), "Goal 2 L0 replay", "--profile",
        "v2.1-catalog-1",
        env=env,
    )
    assert created.returncode == 0, created.stderr
    candidate_result = _run_controller(
        "new-candidate", str(project), "--title", "Replay", "--question",
        "Which context bytes reach the provider?", "--claim", "The bytes bind",
        "--input", "Goal 2 captured boundary fixture", env=env,
    )
    assert candidate_result.returncode == 0, candidate_result.stderr
    candidate = candidate_result.stdout.strip().splitlines()[0]

    replay_delta = tmp_path / "provider_delta.json"
    replay_delta.write_text(
        json.dumps({"schema_version": "2.1", "candidate_id": candidate},
                   separators=(",", ":")),
        encoding="utf-8",
    )

    writer = tmp_path / "replay_provider.py"
    writer.write_text(
        "import shutil, sys; shutil.copyfile(sys.argv[1], sys.argv[2])",
        encoding="utf-8",
    )
    provider = CommandProvider({
        "command": (
            f'"{sys.executable}" "{writer}" "{replay_delta}" '
            "{output_file}"
        ),
        "timeout": 30,
    })
    monkeypatch.setattr(run_loop, "provider_for", lambda *_args, **_kwargs: provider)
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", env["RLR_HYPOTHESIS_STORE"])

    step = {
        "node": "L0",
        "persona": "Linnaeus",
        "profile_id": "v2.1-catalog-1",
        "schema_version": "2.1",
        "tools_policy": "no-fs",
        "everos_read_scopes": [],
    }
    ok = run_loop.exec_cognitive(
        str(project),
        candidate,
        step,
        SimpleNamespace(data={}),
        SimpleNamespace(evidence_run_ids={}, provider=None),
        tmp_path / "run",
        "1",
        do_advance=False,
        failure_state={},
    )

    assert ok is True
    receipt_files = list((tmp_path / "run").glob("L0_Linnaeus_receipt.json"))
    assert len(receipt_files) == 1
    receipt = json.loads(receipt_files[0].read_text(encoding="utf-8"))
    assert receipt["context_hash"] == receipt["rendered_context_hash"]
    assert Path(receipt["provider_delta_path"]).read_bytes() == replay_delta.read_bytes()
