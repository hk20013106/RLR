"""EXTERNAL REUSE GATE — machine enforcement of the RLR architecture-change rule.

This tool is the single enforcement owner for the rule documented in
``docs/architecture/EXTERNAL_REUSE_GATE.md``: an architecture-level change must
carry a valid, structured external-reuse audit artifact in the same change set,
or the machine refuses to proceed.

Design constraints (see the spec doc):

* It reuses the existing CI change-scope entry point (``tools/ci_change_scope.py``
  and the ``scope`` job) rather than creating a second gate job.
* It reuses the structured, fail-closed report conventions established by
  ``research_loop.pre_e2e_closure`` (one owner, no second source of truth).
* It is dependency-free (stdlib only) so it can run on the bare CI runner before
  the project environment is created.
* It never runs a provider and never mutates scientific state.

CLI::

    python tools/external_reuse_gate.py check --repo-root . --changed <paths-file>
    python tools/external_reuse_gate.py validate <audit-artifact.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


AUDIT_SCHEMA_VERSION = "ExternalReuseAudit/v1"
REPORT_SCHEMA_VERSION = "ExternalReuseGateReport/v1"
AUDIT_DIR = "docs/architecture/external-reuse"

DECISIONS = ("REUSE", "ADAPT", "EXTEND", "REFACTOR", "CREATE")
DISPOSITIONS = ("REUSE", "ADAPT", "EXTEND", "REFACTOR", "REJECT")
SCOPES = ("internal", "external")

REQUIRED_FIELDS = (
    "EXISTING_IMPLEMENTATIONS_REVIEWED",
    "REUSABLE_COMPONENTS",
    "ADOPTED_PATTERN",
    "WHY_NEW_CODE_IS_NECESSARY",
)

# Prior evaluation dispositions that count as "reuse/adapt/extend was actually
# considered" when a change still concludes CREATE.
_PRIOR_EVALUATION = ("REUSE", "ADAPT", "EXTEND", "REFACTOR")

_WHY_MIN_LENGTH = 40
_WHY_MIN_LENGTH_CREATE = 80
_PLACEHOLDERS = {"", "n/a", "na", "none", "nil", "todo", "tbd", "fixme", "x", "-"}

# ---------------------------------------------------------------------------
# Architecture surface
# ---------------------------------------------------------------------------
# A change touching any of these owners is an architecture-level change and must
# carry a valid ExternalReuseAudit/v1 artifact in the same change. Tests, docs,
# and CI tooling never trigger the gate on their own.

ARCHITECTURE_PREFIXES = (
    "src/research_loop/",
    "src/rlr_maintenance/",
    "templates/",
    ".github/workflows/",
)

ARCHITECTURE_FILES = (
    "src/run_loop.py",
    "run_loop.py",
    "research_loop_v04.py",
    "environment.yml",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-specter2.txt",
)

# Self-watch: the gate's own owners are part of the architecture surface, so the
# rule cannot be relaxed without an external-reuse audit in the same change.
GOVERNANCE_FILES = (
    "AGENTS.md",
    "docs/architecture/EXTERNAL_REUSE_GATE.md",
    "tools/external_reuse_gate.py",
)

# Best-effort reporting label for a watched path. The gate decision does not
# depend on the label; it exists so the audit report names the affected area.
_AREA_KEYWORDS = (
    ("state/memory", (
        "hypothesis_ledger", "hypothesis_pool", "hypothesis_recall",
        "hypothesis_migration", "hypothesis_reactivation", "l0_state",
        "ranking", "research_seed",
    )),
    ("schema/contract", (
        "contract", "compatibility", "version", "constraint_validation",
    )),
    ("agent handoff", (
        "providers", "persona", "api", "engine",
    )),
    ("evidence provenance", (
        "deep_research", "authority", "evidence_bundle", "provenance",
        "l85", "source_payload_integrity", "method_evidence",
        "registry_projection",
    )),
    ("database/persistence", (
        "l4_pipeline", "delta", "ledger", "idempotency", "l45_ledger",
        "l0_data",
    )),
    ("validation/recovery", (
        "gates", "preflight", "pre_e2e_closure", "path_safety", "l0_intake",
    )),
    ("workflow/orchestration", (
        "topology", "run_loop", "conditional_routing", "node_skips",
        "context",
    )),
    ("skills/tools", (
        "templates", "specter2", "process_runner", "external_resilience",
    )),
)


def _normalize(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_architecture_path(path: str) -> bool:
    """Return True when ``path`` belongs to the architecture surface."""
    p = _normalize(path)
    if not p:
        return False
    if p in ARCHITECTURE_FILES or p in GOVERNANCE_FILES:
        return True
    return any(p.startswith(prefix) for prefix in ARCHITECTURE_PREFIXES)


def architecture_area(path: str) -> str:
    """Return the best-effort architecture area label for a watched path."""
    p = _normalize(path)
    if p in GOVERNANCE_FILES:
        return "governance"
    if p.startswith(".github/workflows/") or p in {
        "src/run_loop.py", "run_loop.py", "research_loop_v04.py",
    }:
        return "workflow/orchestration"
    if p.startswith("templates/"):
        return "skills/tools"
    if p in {
        "environment.yml", "requirements.txt", "requirements-dev.txt",
        "requirements-specter2.txt",
    }:
        return "skills/tools"
    stem = Path(p).name.lower()
    for area, keywords in _AREA_KEYWORDS:
        if any(keyword in stem for keyword in keywords):
            return area
    return "architecture"


def architecture_paths(paths) -> list[str]:
    """Filter a changed-path iterable to the architecture surface (stable order)."""
    seen: list[str] = []
    for raw in paths:
        p = _normalize(raw)
        if is_architecture_path(p) and p not in seen:
            seen.append(p)
    return seen


def _placeholder(value: str) -> bool:
    return value.strip().casefold() in _PLACEHOLDERS


def validate_audit_artifact(artifact) -> list[dict]:
    """Validate one ExternalReuseAudit/v1 object; return a list of violations."""
    violations: list[dict] = []

    def fail(code: str, detail: str) -> None:
        violations.append({"code": code, "detail": detail})

    if not isinstance(artifact, dict):
        fail("not_an_object", "audit artifact must be a JSON object")
        return violations

    if artifact.get("schema_version") != AUDIT_SCHEMA_VERSION:
        fail(
            "bad_schema_version",
            f"schema_version must be {AUDIT_SCHEMA_VERSION!r}",
        )

    change_id = artifact.get("change_id")
    if not isinstance(change_id, str) or _placeholder(change_id):
        fail("missing_change_id", "change_id must be a non-empty string")

    reviewed = artifact.get("EXISTING_IMPLEMENTATIONS_REVIEWED")
    if not isinstance(reviewed, list) or not reviewed:
        fail(
            "reviewed_empty",
            "EXISTING_IMPLEMENTATIONS_REVIEWED must be a non-empty array",
        )
    else:
        scopes_seen = set()
        for index, entry in enumerate(reviewed):
            if not isinstance(entry, dict):
                fail("reviewed_bad_entry", f"entry {index} must be an object")
                continue
            scope = str(entry.get("scope") or "")
            reference = str(entry.get("reference") or "")
            finding = str(entry.get("finding") or "")
            if scope not in SCOPES:
                fail(
                    "reviewed_bad_entry",
                    f"entry {index} scope must be one of {SCOPES}",
                )
            else:
                scopes_seen.add(scope)
            if not reference.strip() or _placeholder(reference):
                fail("reviewed_bad_entry", f"entry {index} needs a reference")
            if not finding.strip() or _placeholder(finding):
                fail("reviewed_bad_entry", f"entry {index} needs a finding")
        if "internal" not in scopes_seen:
            fail(
                "reviewed_missing_internal",
                "must review at least one RLR-internal implementation",
            )
        if "external" not in scopes_seen:
            fail(
                "reviewed_missing_external",
                "must review at least one external implementation or pattern",
            )

    reusable = artifact.get("REUSABLE_COMPONENTS")
    if not isinstance(reusable, list) or not reusable:
        fail("reusable_empty", "REUSABLE_COMPONENTS must be a non-empty array")
    else:
        for index, entry in enumerate(reusable):
            if not isinstance(entry, dict):
                fail("reusable_bad_entry", f"entry {index} must be an object")
                continue
            reference = str(entry.get("reference") or "")
            disposition = str(entry.get("disposition") or "")
            reason = str(entry.get("reason") or "")
            if not reference.strip() or _placeholder(reference):
                fail("reusable_bad_entry", f"entry {index} needs a reference")
            if disposition not in DISPOSITIONS:
                fail(
                    "reusable_bad_entry",
                    f"entry {index} disposition must be one of {DISPOSITIONS}",
                )
            if not reason.strip() or _placeholder(reason):
                fail("reusable_bad_entry", f"entry {index} needs a reason")

    adopted = str(artifact.get("ADOPTED_PATTERN") or "")
    if adopted not in DECISIONS:
        fail("bad_adopted_pattern", f"ADOPTED_PATTERN must be one of {DECISIONS}")

    why = artifact.get("WHY_NEW_CODE_IS_NECESSARY")
    if not isinstance(why, str) or not why.strip():
        fail("why_missing", "WHY_NEW_CODE_IS_NECESSARY must be a non-empty string")
    elif _placeholder(why):
        fail("why_placeholder", "WHY_NEW_CODE_IS_NECESSARY is a placeholder")
    else:
        min_length = _WHY_MIN_LENGTH_CREATE if adopted == "CREATE" else _WHY_MIN_LENGTH
        if len(why.strip()) < min_length:
            fail(
                "why_too_short",
                f"WHY_NEW_CODE_IS_NECESSARY must be >= {min_length} characters",
            )

    if adopted == "CREATE":
        dispositions = {
            str(entry.get("disposition") or "")
            for entry in (reusable or [])
            if isinstance(entry, dict)
        }
        if not (dispositions & set(_PRIOR_EVALUATION)):
            fail(
                "create_without_prior_evaluation",
                "CREATE requires at least one REUSABLE_COMPONENTS entry showing "
                "REUSE/ADAPT/EXTEND/REFACTOR was evaluated",
            )

    return violations


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except OSError as exc:
        return None, {"code": "read_error", "detail": str(exc)}
    except json.JSONDecodeError as exc:
        return None, {"code": "invalid_json", "detail": str(exc)}


def evaluate(repo_root, changed_paths, diff_known: bool = True) -> dict:
    """Evaluate the gate for one change set and return a fail-closed report.

    ``diff_known`` is the caller's proof that the change set is complete. When
    the base/head diff cannot be determined, an empty change set is NOT evidence
    that no architecture change occurred, so the gate fails closed instead of
    reporting ``NOT_APPLICABLE``.
    """
    if not diff_known:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "FAIL",
            "diff_known": False,
            "architecture_paths": [],
            "architecture_areas": [],
            "audit_artifacts": [],
            "valid_audit_artifacts": [],
            "required_fields": list(REQUIRED_FIELDS),
            "violations": [{
                "code": "unknown_diff",
                "detail": (
                    "the changed-path set could not be determined (unknown "
                    "base/head); the gate cannot prove the change is free of "
                    "architecture edits, so it fails closed"
                ),
            }],
            "allowed_to_proceed": False,
        }

    root = Path(repo_root)
    changed = [_normalize(path) for path in changed_paths if _normalize(path)]
    arch = architecture_paths(changed)
    areas = sorted({architecture_area(path) for path in arch})
    audit_paths = [
        path for path in changed
        if path.startswith(AUDIT_DIR + "/") and path.endswith(".json")
    ]

    violations: list[dict] = []
    valid_artifacts: list[str] = []

    for rel in audit_paths:
        artifact_path = root / rel
        if not artifact_path.is_file():
            violations.append({
                "code": "audit_artifact_missing_on_disk",
                "detail": rel,
            })
            continue
        artifact, error = _load_json(artifact_path)
        if error is not None:
            violations.append({**error, "detail": f"{rel}: {error['detail']}"})
            continue
        found = validate_audit_artifact(artifact)
        if found:
            for item in found:
                violations.append({
                    "code": item["code"],
                    "detail": f"{rel}: {item['detail']}",
                })
        else:
            valid_artifacts.append(rel)

    if not arch:
        status = "NOT_APPLICABLE"
        violations = []
    elif valid_artifacts:
        status = "PASS"
        violations = []
    else:
        status = "FAIL"
        if not audit_paths:
            violations.append({
                "code": "missing_audit_artifact",
                "detail": (
                    f"architecture change {arch} has no "
                    f"{AUDIT_DIR}/*.json artifact in the change set"
                ),
            })

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
        "diff_known": True,
        "architecture_paths": arch,
        "architecture_areas": areas,
        "audit_artifacts": audit_paths,
        "valid_audit_artifacts": valid_artifacts,
        "required_fields": list(REQUIRED_FIELDS),
        "violations": violations,
        "allowed_to_proceed": status in {"PASS", "NOT_APPLICABLE"},
    }


def _read_changed(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    paths = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Accept both "path" and "git diff --name-status" rows ("M\tpath").
        if "\t" in line:
            line = line.split("\t")[-1]
        elif line[:2] in {"A ", "M ", "D ", "R ", "C "}:
            line = line[2:]
        paths.append(line)
    return paths


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _fail_report(diff_known: bool, code: str, detail: str) -> dict:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "FAIL",
        "diff_known": diff_known,
        "architecture_paths": [],
        "architecture_areas": [],
        "audit_artifacts": [],
        "valid_audit_artifacts": [],
        "required_fields": list(REQUIRED_FIELDS),
        "violations": [{"code": code, "detail": detail}],
        "allowed_to_proceed": False,
    }


def _cmd_check(args) -> int:
    diff_known = _as_bool(args.diff_known)
    changed_file = Path(args.changed)
    if not changed_file.is_file():
        report = _fail_report(
            diff_known, "changed_list_missing",
            f"changed-path file not found: {changed_file}",
        )
    else:
        try:
            changed = _read_changed(changed_file)
        except OSError as exc:
            report = _fail_report(
                diff_known, "changed_list_unreadable", str(exc),
            )
        else:
            report = evaluate(args.repo_root, changed, diff_known=diff_known)

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["allowed_to_proceed"] else 1


def _cmd_validate(args) -> int:
    artifact_path = Path(args.artifact)
    artifact, error = _load_json(artifact_path)
    if error is not None:
        print(json.dumps(
            {"valid": False, "violations": [error]},
            ensure_ascii=False, indent=2, sort_keys=True,
        ))
        return 1
    violations = validate_audit_artifact(artifact)
    print(json.dumps(
        {"valid": not violations, "violations": violations},
        ensure_ascii=False, indent=2, sort_keys=True,
    ))
    return 0 if not violations else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="external_reuse_gate",
        description="Enforce the RLR external-reuse architecture-change gate.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check", help="evaluate a change set")
    check.add_argument("--repo-root", default=".")
    check.add_argument("--changed", required=True,
                       help="file listing changed paths (one per line)")
    check.add_argument(
        "--diff-known", default="true",
        help=("whether the change set is a complete, known diff; pass 'false' "
              "when CI cannot determine the base/head, which fails closed"),
    )
    check.set_defaults(func=_cmd_check)

    validate = sub.add_parser("validate", help="validate one audit artifact")
    validate.add_argument("artifact")
    validate.set_defaults(func=_cmd_validate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
