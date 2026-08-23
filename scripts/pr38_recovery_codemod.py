from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    print(f"$ {' '.join(args)}")
    if cp.stdout:
        print(cp.stdout)
    if cp.stderr:
        print(cp.stderr, file=sys.stderr)
    if check and cp.returncode:
        raise SystemExit(cp.returncode)
    return cp


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"expected text not found in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def merge_main() -> None:
    run("git", "fetch", "origin", "main")
    cp = run("git", "merge", "--no-commit", "--no-ff", "origin/main", check=False)
    conflicts = run("git", "diff", "--name-only", "--diff-filter=U", check=False).stdout.splitlines()
    allowed = {
        "src/research_loop/topology.py",
        "src/research_loop/commands/lifecycle.py",
    }
    unexpected = set(conflicts) - allowed
    if unexpected:
        raise RuntimeError(f"unexpected merge conflicts: {sorted(unexpected)}")
    for path in conflicts:
        # PR38 owns the L0.5 structural additions; PR39 policy is reapplied below.
        run("git", "checkout", "--ours", "--", path)
        run("git", "add", path)
    if cp.returncode and not conflicts:
        raise RuntimeError("merge failed without resolvable known conflicts")


def verify_current_import_red() -> None:
    cp = run(
        sys.executable,
        "-c",
        "import sys; sys.path.insert(0, 'src'); import research_loop",
        check=False,
    )
    if cp.returncode == 0:
        raise RuntimeError("expected pre-fix import RED, but import already succeeds")
    combined = cp.stdout + cp.stderr
    if "deep_research" not in combined or "subprocess" not in combined:
        raise RuntimeError("import RED is not the expected stale subprocess-observability boundary")
    print("EXPECTED RED: stale subprocess observability boundary reproduced")


def fix_executor_observability_boundary() -> None:
    path = ROOT / "src/research_loop/provider_runtime_observability.py"
    text = path.read_text(encoding="utf-8")
    old_class = re.search(
        r'class _SubprocessProxy:.*?\n\ndef _runtime_dir', text, flags=re.S
    )
    if not old_class:
        raise RuntimeError("_SubprocessProxy block not found")
    new_class = '''class _ExecutorProxy:
    """Observe Deep Research through the canonical ProviderExecutor interface."""

    def __init__(self, original_executor):
        self._original = original_executor

    def run(self, command, **kwargs):
        context = _CONTEXT.get()
        if context is None:
            return self._original.run(command, **kwargs)
        from research_loop.providers.executor import (
            ProviderExecutionError,
            ProviderExecutionResult,
        )

        if isinstance(command, str):
            raise ProviderExecutionError(
                "observed provider execution requires argv form",
                command=command,
            )
        execution = run_observed_provider(
            command=[str(part) for part in command],
            prompt=context["prompt"],
            runtime_dir=context["runtime_dir"],
            backend=context["backend"],
            task_id=context["task_id"],
            candidate_id=context["candidate_id"],
            node=context["node"],
            job_timeout=kwargs.get("timeout"),
            observer_interval=float(os.environ.get("RLR_PROVIDER_OBSERVER_INTERVAL", "1.0")),
            cwd=kwargs.get("cwd"),
            env=kwargs.get("env"),
            input_text=kwargs.get("input_text"),
        )
        context["execution"] = execution
        if execution.final_status in {"job_timed_out", "inactivity_timed_out"}:
            raise ProviderExecutionError(
                f"external provider/tool timed out after {kwargs.get('timeout')}s",
                command=tuple(execution.args),
                returncode=execution.returncode,
                stdout=execution.final_output,
                stderr=execution.stderr,
                timed_out=True,
                timeout=kwargs.get("timeout"),
            )
        result = ProviderExecutionResult(
            command=tuple(execution.args),
            returncode=execution.returncode,
            stdout=execution.final_output,
            stderr=execution.stderr,
        )
        if kwargs.get("check", True) and result.returncode != 0:
            raise ProviderExecutionError(
                f"external provider/tool exited {result.returncode}",
                command=result.command,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                timeout=kwargs.get("timeout"),
            )
        return result


def _runtime_dir'''
    text = text[: old_class.start()] + new_class + text[old_class.end() :]
    old_install = '''    proxy = _SubprocessProxy(deep_research_module.subprocess)\n    deep_research_module.subprocess = proxy\n'''
    new_install = '''    proxy = _ExecutorProxy(deep_research_module.DEFAULT_EXECUTOR)\n    deep_research_module.DEFAULT_EXECUTOR = proxy\n'''
    if old_install not in text:
        raise RuntimeError("legacy observability install block not found")
    text = text.replace(old_install, new_install, 1)
    path.write_text(text, encoding="utf-8")

    # Deep Research already calls DEFAULT_EXECUTOR directly. The separate
    # provider_execution installer duplicated run_and_persist and is removed.
    init = ROOT / "src/research_loop/__init__.py"
    init_text = init.read_text(encoding="utf-8")
    init_text = init_text.replace(
        "from research_loop.provider_execution import install as _install_provider_execution\n",
        "",
    )
    init_text = init_text.replace(
        "_install_provider_execution(deep_research)\n",
        "",
    )
    init_text = init_text.replace(
        "del _install_l0_5_deep_research, _install_provider_execution\n",
        "del _install_l0_5_deep_research\n",
    )
    init.write_text(init_text, encoding="utf-8")

    provider_exec = ROOT / "src/research_loop/provider_execution.py"
    if provider_exec.exists():
        provider_exec.unlink()

    # Old compat code patched subprocess modules. Keep only detached-task status
    # compatibility; executor observation now lives at one interface.
    write(
        "src/research_loop/provider_runtime_compat.py",
        '''"""Compatibility for detached-task provider runtime status only.\n\nProvider process interception is owned by ProviderExecutor +\nprovider_runtime_observability. This module deliberately has no subprocess\nproxy or process-spawning authority.\n"""\nfrom __future__ import annotations\n\nimport json\nimport os\nfrom pathlib import Path\n\n\ndef _read(path: Path) -> dict:\n    try:\n        value = json.loads(path.read_text(encoding="utf-8"))\n    except (OSError, json.JSONDecodeError):\n        return {}\n    return value if isinstance(value, dict) else {}\n\n\ndef install(deep_research_module, detached_task_module, l4_pipeline_module) -> None:\n    del l4_pipeline_module  # compatibility signature; no execution authority here\n    if getattr(deep_research_module, "_provider_observability_compat_installed", False):\n        return\n\n    previous_status = detached_task_module._status\n    previous_validate = detached_task_module._validate_status\n    detailed_failure_terminal = {\n        "provider_failed", "validation_failed", "job_timed_out",\n        "inactivity_timed_out", "cancelled", "provider_dead", "transport_lost",\n    }\n\n    def status(task_id: str, state: str, *, error: str = "", run_id: str = "",\n               attempt_id: str = "", attempt_path: str = "") -> dict:\n        task_dir_value = os.environ.get("RLR_DEEP_RESEARCH_TASK_DIR")\n        before = _read(Path(task_dir_value) / "status.json") if task_dir_value else {}\n        value = previous_status(\n            task_id, state, error=error, run_id=run_id,\n            attempt_id=attempt_id, attempt_path=attempt_path,\n        )\n        if state == "failed":\n            before_state = before.get("state")\n            if before_state == "succeeded":\n                value["state"] = "validation_failed"\n                value["legacy_state"] = "failed"\n            elif before_state in detailed_failure_terminal:\n                value["state"] = before_state\n                value["legacy_state"] = "failed"\n            else:\n                value["state"] = "failed"\n                value["diagnostic_state"] = "provider_failed"\n        return value\n\n    def validate_status(value: dict, task_id: str) -> None:\n        if (\n            value.get("schema_version") == "DeepResearchDetachedTask/v2"\n            and value.get("task_id") == task_id\n            and value.get("state") == "failed"\n        ):\n            return\n        return previous_validate(value, task_id)\n\n    detached_task_module._status = status\n    detached_task_module._validate_status = validate_status\n    deep_research_module._provider_observability_compat_installed = True\n''',
    )


def verify_import_green() -> None:
    run(sys.executable, "-c", "import sys; sys.path.insert(0, 'src'); import research_loop")
    print("GREEN: research_loop import succeeds through ProviderExecutor observability")


def prepare_kb_authority_red() -> None:
    test = ROOT / "tests/test_knowledge_base_authority.py"
    if not test.exists():
        raise RuntimeError("PR39 regression did not arrive from merged main")
    text = test.read_text(encoding="utf-8")
    text = text.replace(
        '        "L0": "read",\n',
        '        "L0": "read",\n        "L0.5": "read-write",\n',
        1,
    )
    test.write_text(text, encoding="utf-8")
    cp = run(
        sys.executable, "-m", "pytest",
        "tests/test_knowledge_base_authority.py", "-q",
        check=False,
    )
    if cp.returncode == 0:
        raise RuntimeError("expected KB authority regression RED before PR39 policy absorption")
    print("EXPECTED RED: topology is not yet canonical KB owner for L0.5")


def absorb_pr39_kb_policy() -> None:
    topology = ROOT / "src/research_loop/topology.py"
    text = topology.read_text(encoding="utf-8")
    if "KNOWLEDGE_BASE_ACCESS =" in text:
        raise RuntimeError("unexpected pre-existing canonical KB policy on PR38 ours")
    policy = '''\n# Canonical per-node authority for the external literature knowledge base.\n# Topology owns this policy; all topology consumers receive an explicit value.\nKNOWLEDGE_BASE_ACCESS = {\n    "L0": "read",\n    "L0.5": "read-write",\n    "L1": "none",\n    "L4": "read-write",\n    "L8.5": "read-write",\n    "L9a": "read", "L9b": "read",\n    "L10a": "read", "L10b": "read", "L10c": "read",\n}\n\n'''
    text = text.replace("\nDAG_NODES = [", policy + "DAG_NODES = [", 1)
    text = text.replace('        "knowledge_base": "read-write",\n', "", 1)
    text = text.replace('        "knowledge_base": "none",\n', "", 1)
    marker = '\nNODE_MAP = {n["node"]: n for n in DAG_NODES}'
    if marker not in text:
        raise RuntimeError("NODE_MAP marker not found")
    apply_policy = '''\n# Materialize permission into every topology view from this one policy table.\nfor _node in DAG_NODES:\n    _node["knowledge_base"] = KNOWLEDGE_BASE_ACCESS.get(_node["node"], "none")\ndel _node\n'''
    text = text.replace(marker, apply_policy + marker, 1)
    topology.write_text(text, encoding="utf-8")

    lifecycle = ROOT / "src/research_loop/commands/lifecycle.py"
    text = lifecycle.read_text(encoding="utf-8")
    text = text.replace(
        "from research_loop.topology import AGENTS, DECISION_TRANSITIONS, NODE_MAP, topology_for_profile\n",
        "from research_loop.topology import (\n    AGENTS, DECISION_TRANSITIONS, KNOWLEDGE_BASE_ACCESS, NODE_MAP,\n    topology_for_profile,\n)\n",
        1,
    )
    text, count = re.subn(
        r'\nKNOWLEDGE_BASE_ACCESS = \{.*?\n\}\n',
        "\n",
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("lifecycle local KB policy block not removed")
    lifecycle.write_text(text, encoding="utf-8")

    run(sys.executable, "-m", "pytest", "tests/test_knowledge_base_authority.py", "-q")
    print("GREEN: PR39 canonical policy absorbed with L0.5 read-write")


def update_executor_regression() -> None:
    path = ROOT / "tests/test_provider_executor.py"
    text = path.read_text(encoding="utf-8")
    old = '''def test_active_provider_and_deep_research_paths_install_executor_boundary():\n    from pathlib import Path\n    import research_loop.deep_research as deep_research\n    import research_loop.providers.base as provider_base\n\n    provider_source = Path(provider_base.__file__).read_text(encoding="utf-8")\n    assert "subprocess.run(" not in provider_source\n    assert "DEFAULT_EXECUTOR.run(" in provider_source\n    assert deep_research._PROVIDER_EXECUTOR_INSTALLED is True\n'''
    new = '''def test_active_provider_and_deep_research_paths_use_executor_boundary():\n    from pathlib import Path\n    import research_loop.deep_research as deep_research\n    import research_loop.providers.base as provider_base\n\n    provider_source = Path(provider_base.__file__).read_text(encoding="utf-8")\n    deep_source = Path(deep_research.__file__).read_text(encoding="utf-8")\n    assert "subprocess.run(" not in provider_source\n    assert "DEFAULT_EXECUTOR.run(" in provider_source\n    assert "subprocess.run(" not in deep_source\n    assert "DEFAULT_EXECUTOR.run(" in deep_source\n    assert callable(deep_research.DEFAULT_EXECUTOR.run)\n'''
    if old not in text:
        raise RuntimeError("old provider executor regression not found")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def targeted_green() -> None:
    run(
        sys.executable, "-m", "pytest",
        "tests/test_provider_executor.py",
        "tests/test_provider_runtime_observability.py",
        "tests/test_knowledge_base_authority.py",
        "-q",
    )


def update_design_docs() -> None:
    spec = ROOT / "docs/superpowers/specs/2026-08-24-l0-5-dynamic-research-provider-executor-design.md"
    text = spec.read_text(encoding="utf-8")
    addition = '''\n## External reuse decision (architecture review)\n\n- Keep RLR's scientific DAG, ResearchSeed, evidence binding, and RunReceipt as\n  authority boundaries; do not add a second orchestration/state framework.\n- Continue using the existing Academic Research/Deep Research backend for this\n  PR. L0.5 defines a stable retrieval boundary rather than embedding one RAG\n  implementation into the scientific state machine.\n- If a locally indexed scientific-paper corpus becomes a requirement, evaluate\n  FutureHouse PaperQA2 first: it already provides scientific metadata handling,\n  agentic query refinement, evidence ranking, grounded citations, and local\n  full-text indexing. Do not implement a home-grown BM25/vector/RAG stack.\n- Generic Haystack/OpenSearch/Qdrant remain lower-level alternatives only when\n  a future storage/index requirement cannot be expressed through PaperQA2.\n- PR39's rule is inherited: Knowledge Base permission has one canonical owner,\n  `research_loop.topology.KNOWLEDGE_BASE_ACCESS`; L0.5 is `read-write`, L1 is\n  `none`.\n'''
    if "## External reuse decision (architecture review)" not in text:
        spec.write_text(text.rstrip() + "\n" + addition, encoding="utf-8")

    plan = ROOT / "docs/superpowers/plans/2026-08-24-pr38-architecture-recovery.md"
    text = plan.read_text(encoding="utf-8")
    text = text.replace(
        "Haystack is reserved for a future local hybrid-retrieval backend if/when L0.5 indexes the local literature corpus.",
        "PaperQA2 is the preferred future local scientific-literature backend if/when L0.5 indexes a local corpus; generic hybrid stores remain fallback infrastructure.",
    )
    text = text.replace(
        "- If local keyword+vector retrieval is implemented later, prefer a mature hybrid retriever (Haystack/OpenSearch/Qdrant) rather than hand-writing BM25/vector fusion.",
        "- If local scientific-literature retrieval is implemented later, evaluate PaperQA2 first; use Haystack/OpenSearch/Qdrant only as lower-level fallback infrastructure rather than hand-writing retrieval.",
    )
    text = text.replace(
        "- Haystack hybrid retrieval: approve as the preferred candidate for a future local-literature retrieval backend if the project requires BM25 + embedding retrieval. Do not implement a home-grown hybrid retriever.",
        "- PaperQA2: preferred candidate for a future local scientific-literature backend because it already combines scientific metadata, agentic query refinement, evidence ranking, grounded citations, and local indexing. Do not implement a home-grown RAG stack.\n- Haystack/OpenSearch/Qdrant: retain only as lower-level fallback infrastructure if a future indexing requirement cannot be expressed through PaperQA2.",
    )
    text = text.replace(
        "**Future trigger for Haystack:** only when L0.5 is required to retrieve against a locally indexed corpus, not merely external PubMed/OpenAlex/web sources.",
        "**Future trigger for PaperQA2:** only when L0.5 is required to retrieve against a locally indexed scientific corpus, not merely external PubMed/OpenAlex/web sources.",
    )
    plan.write_text(text, encoding="utf-8")


def cleanup_bootstrap() -> None:
    for rel in (
        "scripts/pr38_recovery_codemod.py",
        ".github/workflows/pr38-recovery-codemod.yml",
    ):
        path = ROOT / rel
        if path.exists():
            path.unlink()


def main() -> None:
    merge_main()
    verify_current_import_red()
    fix_executor_observability_boundary()
    verify_import_green()
    prepare_kb_authority_red()
    absorb_pr39_kb_policy()
    update_executor_regression()
    update_design_docs()
    targeted_green()
    cleanup_bootstrap()
    run("git", "diff", "--check")
    print("PR38 RECOVERY PHASE 1: PASS")


if __name__ == "__main__":
    main()
