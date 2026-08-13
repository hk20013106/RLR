"""Execution CLI command family extracted from engine.py."""

import json
import re
import shutil
import sys
from pathlib import Path

from research_loop.commands.lifecycle import PREFLIGHT_FILES
from research_loop.common import _append_decision, _now, _set_status, _stamp
from research_loop.delta import (
    _delta_for_candidate,
    l6_analysis_plan_scripts,
    l6_script_name,
)
from research_loop.l0_data import (
    L0DataError,
    current_round_data_binding_path,
    verify_current_round_data_binding,
)
from research_loop.l0_state import _resolve_registered_path
from research_loop.paths import _candidate_file, _sha256
from research_loop.yamlio import _load_yaml_front, _yaml_value


def _workspace_role(value):
    """Return a deterministic safe directory segment for one declared data role."""
    role = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "data")).strip("._")
    return role or "data"


def _bound_local_inputs(project_dir, cand_id):
    """Revalidate and resolve the sole current-round scientific data authority."""
    binding = verify_current_round_data_binding(project_dir, cand_id)
    project = Path(project_dir)
    resolved = []
    for item in binding.get("authorized_inputs") or []:
        src = _resolve_registered_path(project, str(item.get("path") or ""))
        if not src.is_file():
            raise L0DataError(
                "L0_DATA_EXECUTION_INPUT_NOT_FILE",
                f"L7 can stage regular files only: {item.get('path')}",
            )
        resolved.append((src, item))
    return binding, resolved


def cmd_execution_gate(args):
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2

    missing = []
    pf = project_dir / "00_Preflight"
    if not (pf / "skill_use_plan.md").exists():
        missing.append("00_Preflight/skill_use_plan.md")

    try:
        binding, local_inputs = _bound_local_inputs(project_dir, args.cand_id)
    except L0DataError as exc:
        missing.append(f"current-round data binding invalid: {exc.code}: {exc.detail}")
        binding, local_inputs = None, []
    if binding is not None and not local_inputs:
        non_files = binding.get("non_file_inputs") or []
        if non_files:
            missing.append(
                "current-round data has no local files for L7 staging; "
                "materialize/register the declared dataset before execution"
            )
        else:
            missing.append("current-round data binding authorizes no local execution input")

    fm = _load_yaml_front(cf)
    status = fm.get("current_status", "?")
    if status != "METHOD_APPROVED":
        missing.append(f"approved analysis plan (candidate is {status}, "
                       f"need METHOD_APPROVED)")
    if missing:
        print("EXECUTION GATE: REJECT")
        for item in missing:
            print(f"  missing: {item}")
        print("  Turing may NOT execute. Resolve the above (Linnaeus L0 / "
              "Oppenheimer L6) first.")
        return 1

    _append_decision(project_dir, args.cand_id, status, "NEEDS_EXECUTION",
                     "execution gate passed: authorized round data + approved plan present",
                     route_to="Turing", agent="Oppenheimer",
                     kind="execution_gate")
    _set_status(project_dir, args.cand_id, "NEEDS_EXECUTION", "Turing")
    print("EXECUTION GATE: PASS")
    print("  skill_use_plan.md ........ OK")
    print(f"  round data binding ....... OK ({len(local_inputs)} local input(s) authorized)")
    print("  approved analysis plan ... OK (METHOD_APPROVED)")
    print(f"  {args.cand_id} -> NEEDS_EXECUTION (route: Turing)")
    return 0


def _approved_execution_scripts(project_dir, cand_id):
    """Resolve exact script names from the candidate-owned L6 analysis plan."""
    delta = _delta_for_candidate(project_dir, "L6_oppenheimer", cand_id)
    if not delta:
        return [], ["missing execution script plan: L6_oppenheimer delta"]
    try:
        data = json.loads(delta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], ["missing execution script plan: unreadable L6_oppenheimer delta"]
    scripts = l6_analysis_plan_scripts(data)
    roots = [
        Path(project_dir) / "04_Analysis_Outputs",
        Path(project_dir) / "02_Agent_Notes" / "Turing",
    ]
    resolved, missing = [], []
    for script in scripts:
        declared_name = l6_script_name(script)
        if not declared_name:
            missing.append("invalid execution script declaration: missing string `name`")
            continue
        script_name = Path(declared_name).name
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

    Scientific data enter this workspace only through the immutable
    CurrentRoundDataBinding written by the shared L0 gate.  The historical
    input_manifest.md may still exist as a human-facing projection, but it has
    no authority here.  Turing runs scripts in scripts/, writes to results/,
    and reads only from inputs/; project/raw sources remain untouched.
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

    # Fail before creating any workspace if the exact L0-authorized data state
    # has changed.  This is the execution-use revalidation boundary.
    try:
        data_binding, authorized_inputs = _bound_local_inputs(
            project_dir, args.cand_id)
    except L0DataError as exc:
        print(f"ERROR: current-round data binding -- {exc.code}: {exc.detail}",
              file=sys.stderr)
        return 1

    if not authorized_inputs:
        print("ERROR: current-round data binding has no local files that L7 can stage",
              file=sys.stderr)
        return 1

    # --file is retained only as a compatibility spelling for an already-bound
    # input.  It can never expand the scientific-data authority.
    authorized_paths = {src.resolve() for src, _item in authorized_inputs}
    for raw in (getattr(args, "file", None) or []):
        src = Path(raw).expanduser().resolve()
        if src not in authorized_paths:
            print(
                f"ERROR: --file is not authorized by CurrentRoundDataBinding: {raw}; "
                "register it through L0 instead",
                file=sys.stderr,
            )
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

    def stage(src, dest, reason, *, data_meta=None):
        src = Path(src)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.read_bytes() != src.read_bytes():
            missing.append(f"workspace destination collision: {dest.relative_to(ws)}")
            return
        shutil.copy2(src, dest)
        copied.append(str(dest.relative_to(ws)).replace("\\", "/"))
        record = {
            "original_path": str(src.resolve()),
            "workspace_path": str(dest.resolve()),
            "sha256": _sha256(dest),
            "reason": reason,
            "candidate_id": args.cand_id,
            "node": "L7",
        }
        if data_meta:
            record.update({
                "data_origin": data_meta.get("origin"),
                "data_role": data_meta.get("role"),
                "data_artifact_id": data_meta.get("artifact_id", ""),
            })
        staged_files.append(record)

    # Exact data-authorization receipt enters the workspace with the files it
    # governs.  This is metadata, not a second source of truth.
    binding_path = current_round_data_binding_path(project_dir, args.cand_id)
    stage(binding_path, inputs / "current_round_data_binding.json",
          "L0-authorized current-round data binding")

    # Deltas Turing is allowed to see per the DAG (L6 approved plan, L0 facts).
    for delta_key in ("L0_linnaeus", "L6_oppenheimer"):
        df = _delta_for_candidate(project_dir, delta_key, args.cand_id)
        if df and df.exists():
            stage(df, inputs / df.name, f"DAG-allowed {delta_key} delta")
        else:
            missing.append(f"{delta_key} delta")

    # Preflight support files remain available, but the historical
    # input_manifest.md is intentionally neither required nor staged: exposing
    # it would reintroduce an unauthorized list of scientific paths.
    pf = project_dir / "00_Preflight"
    for fname in PREFLIGHT_FILES:
        if fname == "input_manifest.md":
            continue
        src = pf / fname
        if src.exists():
            stage(src, inputs / fname, f"L0 preflight support: {fname}")
        else:
            missing.append(f"00_Preflight/{fname}")

    # Sole scientific input path: exact binding records, revalidated above.
    destinations = {}
    for src, item in authorized_inputs:
        role = _workspace_role(item.get("role"))
        dest = inputs / role / src.name
        previous = destinations.get(dest)
        if previous is not None and previous.resolve() != src.resolve():
            missing.append(
                f"workspace data role/name collision: role={role} name={src.name}; "
                "assign distinct roles in the L0 contract"
            )
            continue
        destinations[dest] = src
        stage(
            src,
            dest,
            f"CurrentRoundDataBinding: {item.get('origin')}:{item.get('role')}",
            data_meta=item,
        )

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
        "data_binding": {
            "path": str(binding_path.resolve()),
            "sha256": _sha256(binding_path),
            "schema_version": data_binding.get("schema_version"),
            "authorized_input_count": len(authorized_inputs),
        },
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
        "Isolated execution workspace. Scientific data are staged only from the",
        "current-round data binding. Turing runs scripts in `scripts/`, writes",
        "outputs to `results/`, and reads only from `inputs/`.",
        "",
        "## Copied in",
        "",
    ]
    manifest += ([f"- {item}" for item in copied] or ["- _none_"])
    if missing:
        manifest += ["", "## Missing (not copied)", ""]
        manifest += [f"- {item}" for item in missing]
    (ws / "WORKSPACE_MANIFEST.md").write_text("\n".join(manifest) + "\n",
                                              encoding="utf-8")

    print(f"Turing workspace ready: {ws}")
    print(f"  inputs/ ... {len(copied)} file(s) copied")
    print(f"  round data  {len(authorized_inputs)} authorized scientific file(s)")
    print("  scripts/ .. (approved scripts only)")
    print("  results/ .. (Turing writes outputs here)")
    if missing:
        print(f"  WARN: {len(missing)} expected item(s) missing:", file=sys.stderr)
        for item in missing:
            print(f"    - {item}", file=sys.stderr)
        return 1
    return 0
