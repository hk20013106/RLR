"""Test-only import boundary for the relocated Research Loop source tree."""

import sys
import os
import tempfile
from pathlib import Path

import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault(
    "RLR_HYPOTHESIS_STORE",
    str(Path(tempfile.gettempdir()) / f"rlr-pytest-{os.getpid()}.sqlite"),
)


def pytest_configure(config):
    """Install test adapters and propagate coverage before collection."""
    import native_v2_helpers
    from hypothesis_recall_test_support import install

    install(native_v2_helpers)
    if getattr(config.option, "cov_source", None):
        root = Path(__file__).resolve().parents[1]
        os.environ["COVERAGE_PROCESS_START"] = str(root / ".coveragerc")
        os.environ["COVERAGE_FILE"] = str(root / ".coverage")


@pytest.fixture(autouse=True)
def native_v2_knowledge_store(tmp_path, monkeypatch):
    """Every CLI-created test project is explicitly bound to an isolated v2 store."""
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(tmp_path / "hypotheses.sqlite"))
