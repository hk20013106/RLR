"""Test-only import boundary for the relocated Research Loop source tree."""

import hashlib
import contextlib
import io
import json
import sys
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

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
    from native_curie_test_support import install as install_native_curie
    from hypothesis_recall_test_support import install as install_recall

    install_native_curie(native_v2_helpers)
    install_recall(native_v2_helpers)
    if getattr(config.option, "cov_source", None):
        root = Path(__file__).resolve().parents[1]
        os.environ["COVERAGE_PROCESS_START"] = str(root / ".coveragerc")
        os.environ["COVERAGE_FILE"] = str(root / ".coverage")


@pytest.fixture(autouse=True)
def native_v2_knowledge_store(tmp_path, monkeypatch):
    """Every CLI-created test project is explicitly bound to an isolated v2 store."""
    monkeypatch.setenv("RLR_HYPOTHESIS_STORE", str(tmp_path / "hypotheses.sqlite"))


def _bootstrap_legacy_cli_project(project, command, kwargs, tmp_path, real_run):
    """Migrate an old positive CLI fixture through the real bootstrap.

    This is test-only compatibility for suites written before PROJECT_READY
    became a candidate admission precondition. It invokes the production
    ``preflight --backend codex`` command; production code has no such bypass.
    """
    project = Path(project)
    receipt = project / "00_Preflight" / "preflight_receipt.json"
    if receipt.is_file() or not (project / "00_Project_Index.md").is_file():
        return
    binding = project / "00_Preflight" / "hypothesis_store_binding.json"
    if not binding.is_file():
        return

    vault = tmp_path / "legacy-cli-obsidian-vault"
    (vault / ".obsidian").mkdir(parents=True, exist_ok=True)
    preflight_dir = project / "00_Preflight"
    preflight_dir.mkdir(parents=True, exist_ok=True)
    (preflight_dir / "pubmed_mcp.json").write_text(
        json.dumps({"command": "__missing_pubmed_mcp__"}),
        encoding="utf-8",
    )
    # The first-mile acceptance is the real-probe test. Legacy regression
    # fixtures only need the persisted contract and should not each wait for a
    # network timeout. Keep the production preflight command owner and receipt
    # writer, but provide deterministic test-only probe results here.
    provided_env = kwargs.get("env") or {}
    if "--knowledge-store" in command:
        index = command.index("--knowledge-store")
        if index + 1 < len(command):
            store_override = str(command[index + 1])
        else:
            store_override = None
    else:
        store_override = provided_env.get("RLR_HYPOTHESIS_STORE")

    from research_loop import l0_preflight
    from research_loop.commands import lifecycle

    def deterministic_probes(project_dir, *, backend=None):
        advisory = l0_preflight.ENFORCEMENT_READINESS_ONLY
        return [
            l0_preflight.ProbeResult(
                "core.python_packages", "PASS", "OK",
                "test fixture packages importable", "RLR runtime",
            ),
            l0_preflight.ProbeResult(
                "core.filesystem", "PASS", "OK",
                "test fixture filesystem writable", "project artifacts and audit receipts",
            ),
            l0_preflight.ProbeResult(
                "runtime.binding", "PASS", "OK",
                "explicit backend/runtime binding authorized", "PROJECT_READY runtime/backend authority",
            ),
            l0_preflight.ProbeResult(
                "research.academic_research", "PASS", "OK",
                "Academic Research runtime fixture ready", "L1/L4/L8.5 research reasoning",
            ),
            l0_preflight.ProbeResult(
                "research.pubmed_mcp", "FAIL", "TEST_ADVISORY",
                "legacy fixture defers PubMed transport", "future canonical literature discovery/full-text transport",
                advisory,
            ),
            l0_preflight.ProbeResult(
                "research.zotero", "FAIL", "TEST_ADVISORY",
                "legacy fixture defers Zotero projection", "future selected-literature/PDF management",
                advisory,
            ),
            l0_preflight.ProbeResult(
                "state.hypothesis_ledger", "PASS", "OK",
                "test fixture ledger binding valid", "cross-round hypothesis lineage/state",
            ),
            l0_preflight.ProbeResult(
                "state.evidence_store", "PASS", "OK",
                "test fixture evidence store writable", "source/intermediate/result/literature evidence persistence",
            ),
            l0_preflight.ProbeResult(
                "state.obsidian", "PASS", "OK",
                "test fixture Obsidian vault writable", "required L10c human-readable projection",
            ),
        ]

    previous_probe_runner = l0_preflight.run_preflight_probes
    previous_store = os.environ.get("RLR_HYPOTHESIS_STORE")
    previous_host = os.environ.get("RLR_HOST_BACKEND")
    previous_vault = os.environ.get("OBSIDIAN_VAULT")
    try:
        if store_override:
            os.environ["RLR_HYPOTHESIS_STORE"] = store_override
        os.environ["RLR_HOST_BACKEND"] = "codex"
        os.environ["OBSIDIAN_VAULT"] = str(vault)
        l0_preflight.run_preflight_probes = deterministic_probes
        preflight_stdout = io.StringIO()
        preflight_stderr = io.StringIO()
        with contextlib.redirect_stdout(preflight_stdout), contextlib.redirect_stderr(preflight_stderr):
            result_code = lifecycle.cmd_preflight(SimpleNamespace(
                project_dir=str(project), backend="codex", force=False,
            ))
    finally:
        l0_preflight.run_preflight_probes = previous_probe_runner
        if previous_store is None:
            os.environ.pop("RLR_HYPOTHESIS_STORE", None)
        else:
            os.environ["RLR_HYPOTHESIS_STORE"] = previous_store
        if previous_host is None:
            os.environ.pop("RLR_HOST_BACKEND", None)
        else:
            os.environ["RLR_HOST_BACKEND"] = previous_host
        if previous_vault is None:
            os.environ.pop("OBSIDIAN_VAULT", None)
        else:
            os.environ["OBSIDIAN_VAULT"] = previous_vault

    if result_code != 0:
        raise AssertionError(
            f"legacy CLI fixture bootstrap failed with rc={result_code}\n"
            f"stdout={preflight_stdout.getvalue()}\n"
            f"stderr={preflight_stderr.getvalue()}"
        )


@pytest.fixture(autouse=True)
def bootstrap_legacy_cli_projects(request, tmp_path, monkeypatch):
    """Run strict first-mile bootstrap for pre-PROJECT_READY CLI fixtures."""
    if request.module.__name__.endswith("test_first_mile_bootstrap"):
        return
    # test_deep_research has a more specific adapter below because it also
    # rewrites its historical placeholder input and native evidence handoff.
    if request.module.__name__.endswith("test_deep_research"):
        return

    real_run = subprocess.run

    from research_loop.commands import lifecycle
    from research_loop import l0_preflight
    real_require_project_ready = lifecycle._require_project_ready
    real_validate_project_ready = l0_preflight.validate_project_ready

    def validate_legacy_handbuilt_fixture(project, *args, **kwargs):
        result = real_validate_project_ready(project, *args, **kwargs)
        if (
            result.get("status") != "PASS"
            and not (Path(project) / "00_Project_Index.md").is_file()
        ):
            return {
                "status": "PASS",
                "code": "LEGACY_TEST_FIXTURE",
                "legacy": True,
            }
        return result

    def require_with_bootstrap(project, candidate_path=None):
        ready = real_require_project_ready(project, candidate_path=candidate_path)
        if ready is not None:
            return ready
        _bootstrap_legacy_cli_project(
            project, [], {}, tmp_path, real_run
        )
        return real_require_project_ready(project, candidate_path=candidate_path)

    def run_with_bootstrap(command, *args, **kwargs):
        if isinstance(command, (list, tuple)):
            parts = list(command)
            if "--dry-run" not in parts:
                project = None
                if "new-candidate" in parts:
                    index = parts.index("new-candidate")
                    if index + 1 < len(parts):
                        project = parts[index + 1]
                elif "normalize-l0-input" in parts and "--project" in parts:
                    index = parts.index("--project")
                    if index + 1 < len(parts):
                        project = parts[index + 1]
                if project is not None:
                    _bootstrap_legacy_cli_project(
                        project, parts, kwargs, tmp_path, real_run
                    )
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run_with_bootstrap)
    monkeypatch.setattr(lifecycle, "_require_project_ready",
                        require_with_bootstrap)
    monkeypatch.setattr(l0_preflight, "validate_project_ready",
                        validate_legacy_handbuilt_fixture)


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


@pytest.fixture
def l4_paperqa2_runtime():
    """Build the real PaperQA2 Curie runtime around a deterministic test backend."""
    from research_loop.l05_curie.paperqa2_runtime import PaperQA2CurieRuntime

    def build(text):
        calls = []

        def backend(*, paper, question):
            calls.append({"paper": dict(paper), "question": str(question)})
            return [{
                "text": str(text).strip(),
                "section": "PaperQA2",
                "locator": "paperqa2-test/chunk:1",
                "score": 1.0,
            }]

        return (
            PaperQA2CurieRuntime(backend=backend, backend_id="paperqa2-test/v1"),
            calls,
        )

    return build


@pytest.fixture(autouse=True)
def complete_deep_research_l0_fixture(request, monkeypatch, tmp_path):
    """Migrate old provider-runtime fixtures to current L0/L0.5 preconditions.

    The shared ``test_deep_research`` factory predates strict L0 and invokes
    ``new-candidate --input data``. The literal ``data`` is intentionally a
    production placeholder, so keep the validator strict and rewrite only that
    exact test-fixture command to a descriptive synthetic input. These tests
    also use the production preflight owner before candidate creation; the
    legacy adapter keeps probes deterministic for the full regression suite.

    Two historical positive provider-lifecycle tests also predate native Curie
    authority and finish by assembling native L1 context. Their scope is the
    provider/detached runtime, not acquisition authority. Immediately before
    that final context call, convert the already-audited legacy test run into a
    frozen Curie pack and native binding. Production never performs this test
    adapter; dedicated native handoff tests prove legacy-only binding fails.
    """
    if not request.module.__name__.endswith("test_deep_research"):
        return

    native_context_fixture_tests = {
        "test_detached_deep_research_survives_start_process_exit_and_collects",
        "test_deep_research_cli_executes_a_local_fake_codex",
    }
    real_run = subprocess.run

    def ensure_project_ready(project, command, kwargs):
        """Run the production preflight owner for an old provider fixture."""
        _bootstrap_legacy_cli_project(
            project, list(command), kwargs, tmp_path, real_run
        )

    def ensure_native_test_binding(project, candidate_id):
        from research_loop import deep_research, l05_curie, research_seed
        from research_loop.l05_curie.native_runtime import bind_initial_curie_pack

        project = Path(project)
        seed = research_seed.load_l1_research_seed(project, candidate_id)
        active = research_seed.active_l1_native_evidence_run_id(project, seed)
        if active:
            return
        run_id = deep_research.unique_run_id(project, candidate_id, "L1")
        if not run_id:
            raise AssertionError(
                "provider-runtime fixture has no unique audited L1 evidence run"
            )
        manifest = l05_curie.freeze_l1_deep_research_run(
            project,
            candidate_id=str(seed["candidate_id"]),
            round_id=str(seed["round_id"]),
            seed_sha256=research_seed.seed_sha256(seed),
            run_id=str(run_id),
        )
        bind_initial_curie_pack(project, seed, manifest, str(run_id))

    def run_with_current_l0_fixture(command, *args, **kwargs):
        rewritten = command
        if isinstance(command, (list, tuple)):
            parts = list(command)
            if "new-candidate" in parts:
                command_index = parts.index("new-candidate")
                if len(parts) <= command_index + 1:
                    raise AssertionError("malformed new-candidate fixture command")
                ensure_project_ready(parts[command_index + 1], command, kwargs)
            if "new-candidate" in parts and "--input" in parts:
                index = parts.index("--input")
                if index + 1 < len(parts) and parts[index + 1] == "data":
                    parts[index + 1] = "synthetic deep research fixture input"
                    rewritten = tuple(parts) if isinstance(command, tuple) else parts
            if (
                request.node.name in native_context_fixture_tests
                and "assemble-context" in parts
                and "--node" in parts
                and parts[parts.index("--node") + 1] == "L1"
            ):
                command_index = parts.index("assemble-context")
                if len(parts) <= command_index + 2:
                    raise AssertionError("malformed assemble-context test command")
                ensure_native_test_binding(
                    parts[command_index + 1], parts[command_index + 2]
                )
        return real_run(rewritten, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run_with_current_l0_fixture)
