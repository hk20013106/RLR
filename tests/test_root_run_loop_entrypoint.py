import subprocess
import sys
from pathlib import Path

import pytest


def test_root_run_loop_propagates_nonzero_main_exit(tmp_path):
    """The repository-root compatibility entrypoint must preserve fail-closed codes."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "run_loop.py"), "run", str(tmp_path), "C_missing"],
        capture_output=True,
        text=True,
        cwd=root,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "no candidate C_missing" in (result.stdout + result.stderr)


@pytest.mark.parametrize("command", ["host-next", "host-submit"])
def test_root_run_loop_exposes_typed_host_protocol_commands(command):
    """Both host protocol operations must be reachable from the root shim."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "run_loop.py"), command, "--help"],
        capture_output=True, text=True, cwd=root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--config" in result.stdout
    if command == "host-next":
        assert "--knowledge-store" in result.stdout
        assert "--resume" in result.stdout
    else:
        assert "REQUEST_ID" in result.stdout
        assert "RESPONSE_PATH" in result.stdout
