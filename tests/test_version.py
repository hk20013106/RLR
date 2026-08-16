import subprocess
import sys
from pathlib import Path

from research_loop.commands.reporting import __version__ as reporting_version
from research_loop.version import VERSION


def test_runtime_version_is_v094():
    assert VERSION == "0.9.4"


def test_public_cli_reports_the_single_runtime_version_source():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "research_loop_v04.py", "--version"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.stdout.strip() == f"v{VERSION}"


def test_reporting_uses_the_single_runtime_version_source():
    assert reporting_version == VERSION
