import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE = ROOT / "src" / "rlr_maintenance"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_phase2_has_no_loopx_python_internal_dependency():
    for name in ("loopx_cli.py", "codex_cli.py", "workspace.py", "host.py"):
        assert not any(value == "loopx" or value.startswith("loopx.") for value in _imports(MAINTENANCE / name))


def test_phase2_has_no_parallel_scheduler_database_or_daemon_module():
    forbidden = {"daemon.py", "scheduler.py", "database.py", "state_store.py", "queue.py"}
    assert not forbidden.intersection(path.name for path in MAINTENANCE.iterdir())


def test_github_workflows_do_not_drive_meta_rlr_run_once():
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = path.read_text(encoding="utf-8").lower()
        assert "meta_rlr.py run-once" not in text
