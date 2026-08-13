"""Test-only import boundary for the relocated Research Loop source tree."""

import hashlib
import json
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


def _write_minimal_finalized_round(project, candidate_id, round_id="1"):
    """Write the smallest valid prior-round boundary for a scope-limited fixture.

    These legacy tests exercise loop-memory/intake/report behavior, not manifest
    completeness. Dedicated L0 state tests cover complete artifact discovery and
    hash verification. Production code never uses this helper.
    """
    from research_loop.hypothesis_ledger import binding_path
    from research_loop.l0_state import ROUND_MANIFEST_SCHEMA

    project = Path(project)
    binding = json.loads(binding_path(project).read_text(encoding="utf-8"))
    payload = {
        "schema_version": ROUND_MANIFEST_SCHEMA,
        "project_id": str(binding["project_id"]),
        "candidate_id": str(candidate_id),
        "round_id": str(round_id),
        "artifacts": [],
    }
    path = (project / "08_Audit" / "round_manifests" /
            f"{candidate_id}_round_{round_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def complete_l0_finalization_fixtures(request, monkeypatch, tmp_path):
    """Migrate pre-round-manifest tests without adding production fallbacks.

    Only named historical tests receive their missing physical precondition.
    Their original behavioral scope remains unchanged.
    """
    module = request.module
    name = request.node.name

    if (module.__name__.endswith("test_l0_input_contract")
            and name == "test_continuation_full_rc0_physical_injection"):
        original = module._seed_full

        def finalized_seed(proj, **overrides):
            seed = original(proj, **overrides)
            memory = json.loads(seed.read_text(encoding="utf-8"))
            path, digest = _write_minimal_finalized_round(
                proj, memory["source_candidate_id"], memory.get("parent_round_id", "1")
            )
            memory["round_manifest_path"] = path.relative_to(proj).as_posix()
            memory["round_manifest_sha256"] = digest
            seed.write_text(json.dumps(memory), encoding="utf-8")
            return seed

        monkeypatch.setattr(module, "_seed_full", finalized_seed)

    if (module.__name__.endswith("test_v06_divergence")
            and name == "test_emit_loop_memory_deterministic_and_schema"):
        original = module._seed_candidate_with_deltas

        def finalized_candidate(proj):
            candidate_id = original(proj)
            _write_minimal_finalized_round(proj, candidate_id, "1")
            return candidate_id

        monkeypatch.setattr(module, "_seed_candidate_with_deltas", finalized_candidate)

    if (module.__name__.endswith("test_v06_divergence")
            and name == "test_aggregate_report_no_silent_clobber"):
        vault = tmp_path / "obsidian-vault"
        (vault / ".obsidian").mkdir(parents=True)
        monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))


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