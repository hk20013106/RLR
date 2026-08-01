"""Shared tiny helpers: persona titles, timestamps, input-alias, everos scopes (Phase 2b-1 leaf).

Depends only on stdlib and extracted leaf modules.
"""
import datetime as _dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from research_loop.paths import _candidate_file
from research_loop.topology import AGENTS
from research_loop.yamlio import _replace_field, _yaml_value


PERSONA_TITLE = {
    "Linnaeus": "Catalog Master",
    "Einstein": "Conceptual Explorer",
    "Feynman": "Reality Checker",
    "Oppenheimer": "Cold Director",
    "Fisher": "Design Architect",
    "Tukey": "EDA Scout",
    "Turing": "Execution Engine",
    "Curie": "Evidence Auditor",
    "Darwin": "Evolutionary Biologist",
    "Jobs": "Story Strategist",
}

def _now():
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def _stamp():
    return _dt.datetime.now().strftime("%Y%m%d%H%M%S%f")

def _input_alias(source_input):
    """Path-free alias for a source_input description: directory parts of any
    path-like token are dropped, keeping only file/basename + free text. Lets
    cognitive nodes see *what* the inputs are without the raw filesystem layout.
    """
    if not source_input:
        return ""
    return re.sub(r"\S*[\\/]\S*",
                  lambda m: re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1],
                  source_input)

def _everos_scopes_for(node_info, project_id):
    """Concrete EverOS read scopes for a node (declared, not enforced here)."""
    return [s.replace("<id>", project_id)
            for s in node_info.get("everos_read_scopes", [])]


def _port_open(host, port, timeout=0.6):
    import socket
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _dep_present(dep):
    """True if a dependency is satisfied. A non-empty `attest_env` env var ALWAYS
    satisfies it -- the fail-closed escape hatch for things Python cannot
    introspect (Claude skills, GUI apps like Zotero/Obsidian)."""
    import os
    ae = dep.get("attest_env")
    if ae and os.environ.get(ae, "").strip():
        return True
    kind, name = dep.get("kind"), dep.get("name", "")
    if kind == "python":
        import importlib.util
        return importlib.util.find_spec(name) is not None
    if kind == "command":
        return shutil.which(name) is not None
    if kind == "env":
        v = os.environ.get(dep.get("env", name), "").strip()
        return bool(v) and (not dep.get("check_path") or Path(v).expanduser().exists())
    if kind == "port":
        host, _, port = (dep.get("addr") or "").partition(":")
        return bool(port) and _port_open(host or "127.0.0.1", port)
    if kind == "skill":
        return False  # only satisfiable via attest_env (handled above): fail closed
    return False


def _dep_fix_hint(dep):
    kind, ae = dep.get("kind"), dep.get("attest_env")
    if kind == "python":
        return f"pip install {dep.get('pip', dep['name'])}"
    if kind == "command":
        return f"install / put on PATH: {dep['name']}"
    if kind == "skill":
        return f"enable {dep.get('label', dep['name'])}, then attest: set {ae}=1"
    if kind == "port":
        return (f"start {dep.get('label', dep['name'])} (connector {dep.get('addr')})"
                + (f", or set {ae}=1" if ae else ""))
    if kind == "env":
        return (f"set ${dep.get('env')}" + (" to an existing path" if dep.get("check_path") else "")
                + (f", or set {ae}=1" if ae else ""))
    return "(see 00_Preflight/dependencies.md)"


def _parse_declared_deps(project_dir):
    """Extra required deps declared in 00_Preflight/dependencies.md: lines of the
    form '- python: NAME', '- command: NAME', or '- env: VAR' under a
    '## Required' heading."""
    f = Path(project_dir) / "00_Preflight" / "dependencies.md"
    deps, required = [], False
    if not f.exists():
        return deps
    for line in f.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("##"):
            required = "required" in s.lower()
            continue
        if required:
            m = re.match(r"-\s*(python|command|env):\s*([^\s(]+)", s, re.I)
            if m:
                deps.append({"kind": m.group(1).lower(), "name": m.group(2),
                             "needed_for": "declared in dependencies.md"})
    return deps


# --- L0 dependency gate -----------------------------------------------------
# Runtime dependencies the L0 preflight HARD-CHECKS. A missing REQUIRED
# dependency STOPS the loop (preflight exits non-zero) -- it must NEVER be
# skipped. Project-specific deps are declared in 00_Preflight/dependencies.md
# and are checked the same way. Owned here (not in a command module) so every
# consumer -- common, templates, lifecycle, the standalone CLI -- resolves it by
# plain import instead of an engine.py monkey-patch.
REQUIRED_DEPENDENCIES = [
    {"kind": "python", "name": "yaml", "label": "PyYAML", "pip": "PyYAML",
     "needed_for": "manage_literature_db.py (growable literature DB; L1/L4/L8.5)"},
    {"kind": "port", "name": "zotero", "label": "Zotero", "addr": "127.0.0.1:23119",
     "attest_env": "RLR_ZOTERO",
     "needed_for": "reference manager / citation source for the literature DB"},
    {"kind": "env", "name": "obsidian", "label": "Obsidian vault", "env": "OBSIDIAN_VAULT",
     "check_path": True, "attest_env": "RLR_OBSIDIAN",
     "needed_for": "end-of-round human-readable sync (sync_to_obsidian.py)"},
]


def _check_dependencies(project_dir=None):
    """Check framework + project-declared dependencies. Returns (ok, missing),
    each a list of dep dicts with an added 'present' flag."""
    items = [dict(d) for d in REQUIRED_DEPENDENCIES]
    if project_dir:
        seen = {(d["kind"], d["name"]) for d in items}
        for d in _parse_declared_deps(project_dir):
            if (d["kind"], d["name"]) not in seen:
                items.append(d)
    ok, missing = [], []
    for d in items:
        d = dict(d)
        d["present"] = _dep_present(d)
        (ok if d["present"] else missing).append(d)
    return ok, missing


def _slug(s):
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"^_+|_+$", "", s) or "candidate"


def _next_seq(project_dir, prefix):
    d = Path(project_dir) / "05_Decision_Log"
    n = 0
    if d.exists():
        for f in d.glob(f"{prefix}[0-9]*.md"):
            m = re.match(rf"^{re.escape(prefix)}(\d+)", f.stem)
            if m:
                n = max(n, int(m.group(1)))
    return n + 1


def _require_status(fm, cand_id, expected):
    cur = fm.get("current_status", "?")
    if cur != expected:
        print(f"ERROR: {cand_id} is {cur}, expected {expected} for this command.",
              file=sys.stderr)
        return False
    return True


def _set_status(project_dir, cand_id, new_status, owner=None):
    cf = _candidate_file(project_dir, cand_id)
    _replace_field(cf, "current_status", new_status)
    if owner:
        _replace_field(cf, "current_owner", owner)
    _replace_field(cf, "updated_at", _now())


def _append_decision(project_dir, cand_id, frm, to, reason, route_to="",
                     agent="Oppenheimer", kind="decision"):
    # Import at use time: templates imports shared formatting helpers from this
    # module, so a module-level import would create a circular dependency.
    from research_loop.templates import _decision_log_template

    seq = _next_seq(project_dir, "D")
    body = _decision_log_template(seq, cand_id, frm, to, reason, route_to,
                                  agent=agent, kind=kind)
    f = Path(project_dir) / "05_Decision_Log" / f"D{seq:04d}_{cand_id}.md"
    f.write_text(body, encoding="utf-8")
    cf = _candidate_file(project_dir, cand_id)
    if cf.exists():
        line = f"- [{_now()}] ({kind}/{agent}) {frm} -> {to}: {reason}"
        if route_to:
            line += f" | next: {route_to}"
        text = cf.read_text(encoding="utf-8")
        text = text.replace("## Decision History\n",
                            "## Decision History\n" + line + "\n", 1)
        cf.write_text(text, encoding="utf-8")
    return seq


def _mkdirs(project_dir):
    """v0.4 directory layout (same structure as v0.2)."""
    p = Path(project_dir)
    for sub in ["00_Preflight", "01_Candidates", "03_Handoffs",
                "04_Analysis_Outputs", "05_Decision_Log",
                "06_Manuscript_Direction", "07_Obsidian_Sync",
                "08_Audit", "10_Pitfall_Ledger", "99_Archive"]:
        (p / sub).mkdir(parents=True, exist_ok=True)
    for agent in AGENTS:
        (p / "02_Agent_Notes" / agent).mkdir(parents=True, exist_ok=True)
    return p


def _fmt_list(lst):
    if not lst:
        return "_none_"
    if isinstance(lst, list):
        return ", ".join(str(x) for x in lst)
    return str(lst)


def _fmt_dict(d):
    if not d:
        return "_none_"
    if isinstance(d, dict):
        return "; ".join(f"{k}={v}" for k, v in d.items())
    return str(d)


def _empty_value_for_schema(v):
    """Create an empty default matching a delta schema field type."""
    if v is list:
        return []
    if v is dict:
        return {}
    if v is str:
        return ""
    if v is bool:
        return False
    if v is int:
        return 0
    if isinstance(v, list):
        return []
    if isinstance(v, dict):
        return {}
    return None


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_loop_memory(path):
    """Load + minimally validate a next_loop_memory.json seed. Raises on error."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"loop-memory seed not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"invalid loop-memory seed JSON: {e}")
    required = {"source_candidate_id", "next_round_hypothesis", "required_new_search_directions"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"loop-memory seed missing keys: {sorted(missing)}")
    return data


def _render_extra_front(extra_front):
    """Render additional frontmatter keys. Booleans emit lowercase true/false."""
    if not extra_front:
        return ""
    lines = []
    for k, v in extra_front.items():
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            lines.append(f"{k}: {_yaml_value(v)}")
    return "\n".join(lines) + "\n"
