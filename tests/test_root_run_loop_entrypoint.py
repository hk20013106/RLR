import subprocess
import sys
from pathlib import Path


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
