from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "ci_change_scope.py"


def _module():
    spec = spec_from_file_location("ci_change_scope", MODULE_PATH)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ci_change_scope_policy():
    classify = _module().classify_paths
    assert classify(["README.md", "docs/README_CN.md"]) == "docs-only"
    assert classify(["README_CN.md"]) == "docs-only"
    assert classify(["docs/README_CN.md", "src/research_loop/gates.py"]) == "full"
    assert classify([".github/workflows/ci.yml"]) == "full"
    assert classify(["AGENTS.md"]) == "full"
    assert classify([]) == "full"
