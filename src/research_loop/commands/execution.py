"""Execution CLI command family extracted from engine.py."""

import json
import os
import shutil
import sys
from pathlib import Path

from research_loop.commands.lifecycle import PREFLIGHT_FILES
from research_loop.common import _append_decision, _now, _set_status, _stamp
from research_loop.delta import _delta_for_candidate
from research_loop.paths import _candidate_file, _sha256
from research_loop.yamlio import _load_yaml_front, _yaml_value

def cmd_execution_gate(args):
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    pf = project_dir / "00_Preflight"
    missing = []
    if not (pf / "skill_use_plan.md").exists():
        missing.append("00_Preflight/skill_use_plan.md")
    if not (pf / "input_manifest.md").exists():
        missing.append("00_Preflight/input_manifest.md")
    fm = _load_yaml_front(cf)
    status = fm.get("current_status", "?")
    if status != "METHOD_APPROVED":
        missing.append(f"approved analysis plan (candidate is {status}, "
                       f"need METHOD_APPROVED)")
    if missing:
        print("EXECUTION GATE: REJECT")
        for m in missing:
            print(f"  missing: {m}")
        print("  Turing may NOT execute. Resolve the above (Linnaeus L0 / "
              "Oppenheimer L6) first.")
        return 1
    _append_decision(project_dir, args.cand_id, status, "NEEDS_EXECUTION",
                     "execution gate passed: preflight + approved plan present",
                     route_to="Turing", agent="Oppenheimer",
                     kind="execution_gate")
    _set_status(project_dir, args.cand_id, "NEEDS_EXECUTION", "Turing")
    print("EXECUTION GATE: PASS")
    print("  skill_use_plan.md ........ OK")
    print("  input_manifest.md ........ OK")
    print("  approved analysis plan ... OK (METHOD_APPROVED)")
    print(f"  {args.cand_id} -> NEEDS_EXECUTION (route: Turing)")
    return 0

def _registered_candidate_inputs(project_dir, cand_id):
    """Resolve only key files registered for this candidate's input aliases."""
    cf = _candidate_file(project_dir, cand_id)
    fm = _load_yaml_front(cf)
    aliases = {x.strip() for x in str(fm.get("input_alias", "")).split(",")
               if x.strip()}
    manifest = Path(project_dir) / "00_Preflight" / "input_manifest.md"
    resolved, missing = [], []
    if not manifest.exists():
        return resolved, ["missing required input manifest: 00_Preflight/input_manifest.md"]
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        columns = [x.strip().strip("`") for x in line.strip().strip("|").split("|")]
        if len(columns) < 3 or columns[0] not in aliases:
            continue
        alias, root, key_files = columns[:3]
        root_path = Path(root)
        for raw in key_files.split(";"):
            relative = raw.strip().strip("`")
            if not relative:
                continue
            src = root_path / Path(relative.replace("/", os.sep))
            if src.exists() and src.is_file():
                resolved.append((src, alias, relative))
            else:
                missing.append(
                    f"missing required input: {alias}/{relative} ({src})")
    found_aliases = {alias for _, alias, _ in resolved}
    for alias in sorted(aliases - found_aliases):
        if not any(f"{alias}/" in item for item in missing):
            missing.append(f"missing required input registration for alias: {alias}")
    return resolved, missing

def _approved_execution_scripts(project_dir, cand_id):
    """Resolve exact script names from the candidate-owned L6 analysis plan."""
    delta = _delta_for_candidate(project_dir, "L6_oppenheimer", cand_id)
    if not delta:
        return [], ["missing execution script plan: L6_oppenheimer delta"]
    try:
        data = json.loads(delta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], ["missing execution script plan: unreadable L6_oppenheimer delta"]
    plan = data.get("analysis_plan", [])
    if isinstance(plan, dict):
        names = plan.get("scripts", [])
    elif isinstance(plan, list):
        names = [name for item in plan if isinstance(item, dict)
                 for name in item.get("scripts", [])]
    else:
        names = []
    roots = [
        Path(project_dir) / "04_Analysis_Outputs",
        Path(project_dir) / "02_Agent_Notes" / "Turing",
    ]
    resolved, missing = [], []
    for name in names:
        script_name = Path(str(name)).name
        matches = []
        for root in roots:
            if root.is_dir():
                matches.extend(p for p in root.rglob(script_name)
                               if p.is_file() and "_turing_workspace_" not in str(p))
        matches = sorted(set(matches))
        if len(matches) == 1:
            resolved.append(matches[0])
        elif not matches:
            missing.append(f"missing execution script: {script_name}")
        else:
            missing.append(
                f"ambiguous execution script: {script_name} ({len(matches)} matches)")
    return resolved, missing

def cmd_prepare_turing_workspace(args):
    """Path A: build an isolated execution workspace for Turing (L7).

    Copies the deltas Turing is allowed to see (L0, L6), the preflight files,
    and any explicitly allowlisted input data files into a fresh
    PROJECT_DIR/_turing_workspace_<ts>/ tree (same disk, shutil.copy2, never
    hard links). Turing runs scripts in scripts/, writes to results/, and reads
    only from inputs/; the project tree and raw inputs stay untouched.
    """
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    fm = _load_yaml_front(cf)
    status = fm.get("current_status", "?")
    if status != "NEEDS_EXECUTION":
        print(f"ERROR: {args.cand_id} is {status}; Turing workspace requires "
              f"NEEDS_EXECUTION (run execution-gate first).", file=sys.stderr)
        return 1

    if args.clean:
        for old in sorted(project_dir.glob("_turing_workspace_*")):
            if old.is_dir():
                shutil.rmtree(old, ignore_errors=True)

    ws = project_dir / f"_turing_workspace_{args.cand_id}_{_stamp()}"
    inputs = ws / "inputs"
    for sub in (inputs, ws / "scripts", ws / "results"):
        sub.mkdir(parents=True, exist_ok=True)

    copied, missing, staged_files = [], [], []

    def stage(src, dest, reason):
        src = Path(src)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(str(dest.relative_to(ws)).replace("\\", "/"))
        staged_files.append({
            "original_path": str(src.resolve()),
            "workspace_path": str(dest.resolve()),
            "sha256": _sha256(dest),
            "reason": reason,
            "candidate_id": args.cand_id,
            "node": "L7",
        })

    # Deltas Turing is allowed to see per the DAG (L6 approved plan, L0 skills).
    for delta_key in ("L0_linnaeus", "L6_oppenheimer"):
        df = _delta_for_candidate(project_dir, delta_key, args.cand_id)
        if df and df.exists():
            stage(df, inputs / df.name, f"DAG-allowed {delta_key} delta")
        else:
            missing.append(f"{delta_key} delta")

    # Preflight files (skill plan, manifests, forbidden shortcuts).
    pf = project_dir / "00_Preflight"
    for fname in PREFLIGHT_FILES:
        src = pf / fname
        if src.exists():
            stage(src, inputs / fname, f"L0 preflight allowlist: {fname}")
        else:
            missing.append(f"00_Preflight/{fname}")

    # Candidate-declared inputs: only registered key files enter the workspace.
    registered, input_missing = _registered_candidate_inputs(
        project_dir, args.cand_id)
    missing.extend(input_missing)
    for src, alias, relative in registered:
        dest = inputs / alias / Path(relative.replace("/", os.sep))
        stage(src, dest, f"registered candidate input: {alias}/{relative}")

    # Explicit CLI files remain a narrow additive allowlist.
    for raw in (args.file or []):
        src = Path(raw)
        if src.exists() and src.is_file():
            stage(src, inputs / "explicit" / src.name,
                  "explicit --file allowlist")
        else:
            missing.append(f"allowlisted file not found: {raw}")

    # Candidate-owned L6 plan: stage exact existing script names only.
    approved_scripts, script_missing = _approved_execution_scripts(
        project_dir, args.cand_id)
    missing.extend(script_missing)
    for src in approved_scripts:
        stage(src, ws / "scripts" / src.name,
              "exact script approved by candidate L6 analysis_plan")

    json_manifest = {
        "workspace": str(ws.resolve()),
        "candidate_id": args.cand_id,
        "node": "L7",
        "created_at": _now(),
        "status_at_creation": status,
        "staged_files": staged_files,
        "missing": missing,
    }
    (ws / "WORKSPACE_MANIFEST.json").write_text(
        json.dumps(json_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    manifest = [
        "---",
        f"workspace: {_yaml_value(ws.name)}",
        f"candidate_id: {_yaml_value(args.cand_id)}",
        f"created_at: {_yaml_value(_now())}",
        f"status_at_creation: {_yaml_value(status)}",
        "---",
        "",
        f"# Turing Workspace (Path A) - {args.cand_id}",
        "",
        "Isolated execution workspace. Turing runs scripts in `scripts/`, writes",
        "outputs to `results/`, and reads only the files in `inputs/`. The project",
        "tree and the raw inputs are NOT modified from here.",
        "",
        "## Copied in",
        "",
    ]
    manifest += ([f"- {c}" for c in copied] or ["- _none_"])
    if missing:
        manifest += ["", "## Missing (not copied)", ""]
        manifest += [f"- {m}" for m in missing]
    (ws / "WORKSPACE_MANIFEST.md").write_text("\n".join(manifest) + "\n",
                                              encoding="utf-8")

    print(f"Turing workspace ready: {ws}")
    print(f"  inputs/ ... {len(copied)} file(s) copied")
    print("  scripts/ .. (Turing writes modular scripts here)")
    print("  results/ .. (Turing writes outputs here)")
    if missing:
        print(f"  WARN: {len(missing)} expected item(s) missing:", file=sys.stderr)
        for m in missing:
            print(f"    - {m}", file=sys.stderr)
        return 1
    return 0
