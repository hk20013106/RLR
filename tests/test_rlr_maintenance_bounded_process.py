import json
import os
import sys
import time
from pathlib import Path

import psutil

from rlr_maintenance.bounded_process import run_bounded_process


PYTHON = sys.executable


def _py(source: str) -> list[str]:
    return [PYTHON, "-c", source]


def _write_script(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_normal_completion_returns_bounded_terminal_result(tmp_path):
    result = run_bounded_process(
        _py("import sys; print('out'); print('err', file=sys.stderr)"),
        timeout=5.0,
    )

    assert result.terminal_state == "completed"
    assert result.returncode == 0
    assert result.stdout == f"out{os.linesep}"
    assert result.stderr == f"err{os.linesep}"
    assert result.stdout_truncated is False
    assert result.stderr_truncated is False
    assert result.stdout_bytes == len(f"out{os.linesep}")
    assert result.stderr_bytes == len(f"err{os.linesep}")


def test_nonzero_exit_is_explicit_terminal_failure(tmp_path):
    result = run_bounded_process(_py("import sys; sys.exit(7)"), timeout=5.0)

    assert result.terminal_state == "completed"
    assert result.returncode == 7


def test_hard_timeout_returns_typed_timeout_result(tmp_path):
    started = time.monotonic()
    result = run_bounded_process(
        _py("import time; time.sleep(60)"),
        timeout=0.3,
    )

    assert result.terminal_state == "timed_out"
    assert time.monotonic() - started < 10
    assert result.process_tree_cleanup["attempted"] is True
    assert result.process_tree_cleanup["alive_after_cleanup"] is False


def test_timeout_cleans_up_windows_child_process_tree(tmp_path):
    script = _write_script(
        tmp_path,
        "tree_fixture.py",
        (
            "import json, subprocess, sys, time\n"
            "marker = sys.argv[1]\n"
            "child = subprocess.Popen([sys.executable, '-c', "
            "'import time; time.sleep(60)'])\n"
            "json.dump({'pid': child.pid}, "
            "open(marker, 'w', encoding='utf-8'))\n"
            "time.sleep(60)\n"
        ),
    )
    marker = tmp_path / "child.json"
    child_pid = None
    try:
        result = run_bounded_process(
            [PYTHON, script, str(marker)],
            timeout=1.0,
        )

        child_pid = int(json.loads(marker.read_text(encoding="utf-8"))["pid"])
        assert result.terminal_state == "timed_out"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and psutil.pid_exists(child_pid):
            time.sleep(0.05)
        assert not psutil.pid_exists(child_pid)
    finally:
        if child_pid is not None and psutil.pid_exists(child_pid):
            psutil.Process(child_pid).kill()


def test_oversized_stdout_is_bounded_and_truncated(tmp_path):
    result = run_bounded_process(
        _py("print('x' * 200000)"),
        timeout=5.0,
        max_output_bytes=1024,
    )

    assert result.terminal_state == "completed"
    assert result.stdout_truncated is True
    assert len(result.stdout) <= 1024
    assert result.stdout_bytes > 1024


def test_oversized_stderr_is_bounded_and_truncated(tmp_path):
    result = run_bounded_process(
        _py("import sys; print('x' * 200000, file=sys.stderr)"),
        timeout=5.0,
        max_output_bytes=1024,
    )

    assert result.terminal_state == "completed"
    assert result.stderr_truncated is True
    assert len(result.stderr) <= 1024
    assert result.stderr_bytes > 1024
