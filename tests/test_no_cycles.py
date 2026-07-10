"""Phase 0 safety net: import-cycle guard.

Rev-2 C5 (Codex): "circular import risk is understated." Once research_loop/*
exists (Phase 1+), context needs topology/paths/pre-research/ledger/templates,
and a back-edge (engine->context->engine) would create a cycle instantly. This
guard builds the intra-repo import graph over local top-level modules AND the
future research_loop/ package, and asserts it is acyclic. It is dependency-free
(stdlib ast) so it runs from Phase 0 and automatically covers new modules as
they are extracted -- no .importlinter runtime needed.

Baseline (v0.7-migration): current top-level modules are already acyclic.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Local modules/packages we own and want kept acyclic. research_loop/ does not
# exist yet (Phase 1) -- discovery below picks it up automatically once created.
LOCAL_TOPLEVEL = {
    "research_loop_v04", "run_loop", "orchestrator", "pitfall_ledger",
    "ars_card_adapter", "manage_literature_db", "sync_to_obsidian",
}


def _local_module_files():
    """Map local module name -> file, for root .py and research_loop/ package."""
    files = {}
    for p in REPO.glob("*.py"):
        files[p.stem] = p
    pkg = REPO / "research_loop"
    if pkg.exists():
        for p in pkg.rglob("*.py"):
            rel = p.relative_to(REPO).with_suffix("")
            files[".".join(rel.parts)] = p
    return files


def _imports_of(path):
    """Return the set of imported top-level names/dotted paths in a .py file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


def _build_graph():
    files = _local_module_files()
    known = set(files)
    known_roots = {name.split(".")[0] for name in known} | LOCAL_TOPLEVEL
    graph = {}
    for name, path in files.items():
        deps = set()
        for imp in _imports_of(path):
            root = imp.split(".")[0]
            if imp in known:
                deps.add(imp)
            elif root in known_roots and root != name.split(".")[0]:
                deps.add(root)
        graph[name] = deps
    return graph


def _find_cycle(graph):
    """Return a cycle path if one exists, else None (DFS with colouring)."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}

    def visit(n, stack):
        color[n] = GREY
        stack.append(n)
        for m in graph.get(n, ()):
            if m not in graph:
                continue
            if color.get(m) == GREY:
                return stack[stack.index(m):] + [m]
            if color.get(m) == WHITE:
                r = visit(m, stack)
                if r:
                    return r
        stack.pop()
        color[n] = BLACK
        return None

    for n in graph:
        if color[n] == WHITE:
            r = visit(n, [])
            if r:
                return r
    return None


def test_repo_import_graph_is_acyclic():
    graph = _build_graph()
    cycle = _find_cycle(graph)
    assert cycle is None, f"IMPORT CYCLE detected: {' -> '.join(cycle)}"


def test_providers_never_import_engine():
    """Dependency inversion (Rev-2 C1): providers/* must not import the engine.

    Enforced from Phase 4 onward when research_loop/providers/ exists; a no-op
    (vacuously true) until then.
    """
    pkg = REPO / "research_loop" / "providers"
    if not pkg.exists():
        return
    for p in pkg.rglob("*.py"):
        imps = _imports_of(p)
        bad = {i for i in imps if i.split(".")[0] in {"research_loop_v04"}
               or i in {"research_loop.engine", "research_loop.api"}}
        assert not bad, f"{p.name} must not import engine ({bad})"
