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
# Canonical orchestration creates the cursor-bound recall before L1 context.
# Existing positive CLI fixtures model that orchestration through this opt-in.
os.environ.setdefault("RLR_AUTO_HYPOTHESIS_RECALL", "1")


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


@pytest.fixture(autouse=True)
def complete_legacy_staged_l4_fixtures(request, monkeypatch):
    """Complete abbreviated pre-provenance fixtures without weakening runtime gates.

    Dedicated provenance tests exercise the real manifest, corpus, and identity
    validation paths. These adapters only preserve older tests whose scope is
    L4 call ordering or L4.5 idempotency rather than provenance validation.
    """
    module = request.module
    name = request.node.name

    if module.__name__.endswith("test_l4_pipeline") and name in {
        "test_l45_commit_is_hash_bound_and_idempotent",
        "test_l45_rejects_changed_l4c_delta",
    }:
        original = module._linked_evidence

        def linked_evidence(manifest):
            artifact = original(manifest)
            artifact["l4a_run_id"] = manifest["run_id"]
            return artifact

        monkeypatch.setattr(module, "_linked_evidence", linked_evidence)

    if (
        module.__name__.endswith("test_l4_pipeline")
        and name == "test_install_runs_l4a_then_delegates_l4b_with_frozen_catalog"
    ):
        # This test verifies L4A→L4B call ordering and prompt injection. Its
        # synthetic manifest intentionally has no persisted file; linkage and
        # frozen-corpus enforcement are covered by test_l4_provenance_hardening.
        monkeypatch.setattr(module.l4p, "_persist_l4b_linkage", lambda *_a, **_k: None)
