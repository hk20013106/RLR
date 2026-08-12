import ast
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "d6352c0ceeb649efa892e36acc66f209d33920be"
_ALLOWED_CHANGED_PREFIXES = (
    "src/rlr_maintenance/",
    "tests/test_meta_rlr_",
)
_ALLOWED_CHANGED_FILES = {
    "docs/superpowers/specs/2026-08-13-meta-rlr-loopx-maintenance-boundary-design.md",
    "docs/superpowers/plans/2026-08-13-meta-rlr-loopx-maintenance-boundary.md",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_research_loop_never_depends_on_maintenance_or_loopx():
    offenders = []
    for path in sorted((ROOT / "src" / "research_loop").rglob("*.py")):
        imports = _imports(path)
        if any(
            module == "rlr_maintenance"
            or module.startswith("rlr_maintenance.")
            or module == "loopx"
            or module.startswith("loopx.")
            for module in imports
        ):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_maintenance_uses_external_loopx_boundary_not_python_modules():
    offenders = []
    for path in sorted((ROOT / "src" / "rlr_maintenance").rglob("*.py")):
        imports = _imports(path)
        if any(module == "loopx" or module.startswith("loopx.") for module in imports):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_phase1_change_scope_stays_outside_rlr_core_when_base_is_available():
    available = subprocess.run(
        ["git", "cat-file", "-e", f"{BASE_SHA}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
    )
    if available.returncode != 0:
        pytest.skip("base commit is unavailable in this shallow checkout")

    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{BASE_SHA}...HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
        check=True,
    )
    changed = [line.strip().replace("\\", "/") for line in diff.stdout.splitlines() if line.strip()]
    unexpected = [
        path
        for path in changed
        if path not in _ALLOWED_CHANGED_FILES
        and not path.startswith(_ALLOWED_CHANGED_PREFIXES)
    ]

    assert unexpected == [], f"Meta-RLR Phase 1 changed out-of-scope paths: {unexpected}"
    assert not any(path.startswith("src/research_loop/") for path in changed)
