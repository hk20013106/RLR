"""The CLI entry point must be self-sufficient without importing engine.py.

`engine.py` historically injected REQUIRED_DEPENDENCIES into common.py and
templates.py by monkey-patch. Any path that reaches the dependency gate WITHOUT
importing engine.py therefore crashed with NameError -- which is exactly what a
standalone CLI install does. These tests run in fresh interpreters so an
accidental engine import inside the pytest session cannot mask the defect.
"""
import os
import subprocess
import sys
from pathlib import Path


SRC = str(Path(__file__).resolve().parents[1] / "src")


def _fresh(code):
    """Run code in a fresh interpreter with only src/ on the import path."""
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC
    return subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, env=env)


def test_common_owns_required_dependencies_without_engine():
    proc = _fresh("import research_loop.common as c; "
                  "assert c.REQUIRED_DEPENDENCIES, 'empty'; "
                  "print(len(c.REQUIRED_DEPENDENCIES))")
    assert proc.returncode == 0, proc.stderr
    assert int(proc.stdout.strip()) >= 3


def test_dependency_check_runs_without_engine():
    proc = _fresh("import research_loop.common as c; c._check_dependencies(None)")
    assert "NameError" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stderr


def test_dependencies_template_renders_without_engine():
    proc = _fresh("import research_loop.templates as t; "
                  "print('python: yaml' in t._dependencies_md('P'))")
    assert "NameError" not in proc.stderr, proc.stderr
    assert proc.stdout.strip() == "True", proc.stderr


def test_cli_check_deps_does_not_crash_without_engine():
    """check-deps may legitimately STOP (exit 3) when deps are missing, but it
    must never raise NameError."""
    proc = _fresh("import sys; sys.argv = ['rlr', 'check-deps']; "
                  "from research_loop.cli import main; sys.exit(main() or 0)")
    assert "NameError" not in proc.stderr, proc.stderr
    assert proc.returncode in (0, 3), f"{proc.returncode}\n{proc.stderr}"


def test_lifecycle_still_exports_required_dependencies():
    """engine.py re-exports the constant from lifecycle; keep that name valid."""
    proc = _fresh("from research_loop.commands.lifecycle import REQUIRED_DEPENDENCIES as R; "
                  "import research_loop.common as c; "
                  "print(R is c.REQUIRED_DEPENDENCIES)")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "True", proc.stderr
