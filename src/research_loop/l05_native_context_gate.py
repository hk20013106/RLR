"""Native v2.1 L1 acquisition gate replacement.

The historical ContextAssembler owns the legacy Deep Research pre-research gate.
For native v2.1 L1, this wrapper validates the active frozen Curie binding first,
then suppresses only the legacy L1 pre-research stage for that call. Historical
v2.0 and all non-L1 nodes retain their original behavior.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from research_loop import research_seed
from research_loop.compatibility import CompatibilityError, get_profile
from research_loop.gates import (
    DIVERGENCE_MIN_NEW_QUERY_FAMILIES,
    _audit_branch_coverage,
)
from research_loop.hypothesis_ledger import binding_path
from research_loop.paths import _candidate_file
from research_loop.preresearch import (
    PRE_RESEARCH_MAP,
    _load_query_family_cache,
    _query_family_key,
)
from research_loop.yamlio import _load_yaml_front

_NATIVE_BINDING_ROOT = Path("08_Audit") / "research_seed_bindings" / "native"


class NativeL1EvidenceGateError(ValueError):
    """Raised when native L1 lacks one exact validated Curie binding."""


def _has_native_l1_binding(args) -> bool:
    project = Path(args.project_dir)
    candidate_id = str(getattr(args, "cand_id", "") or "").strip()
    if not candidate_id:
        return False
    native_root = project / _NATIVE_BINDING_ROOT / candidate_id
    return native_root.is_dir() and any(native_root.glob("*/L1_native_*.json"))


def _is_native_l1(args) -> bool:
    if str(getattr(args, "node", "")) != "L1":
        return False
    if _has_native_l1_binding(args):
        # A native receipt must reach the native gate even if the optional
        # hypothesis-ledger profile sidecar is absent or corrupt.  The gate
        # then validates the exact binding and fails closed rather than
        # falling through to legacy L1 acquisition.
        return True
    project = Path(args.project_dir)
    path = binding_path(project)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        profile = get_profile(str(payload.get("profile_id") or ""))
    except (OSError, json.JSONDecodeError, CompatibilityError):
        return False
    return profile.delta_schema_version == "2.1"


def _require_native_l1_profile(project: Path) -> None:
    """Reject a malformed or non-native profile before legacy assembly runs."""
    path = binding_path(project)
    if not path.is_file():
        raise NativeL1EvidenceGateError(
            "native L1 requires a native v2.1 hypothesis ledger profile binding"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        profile = get_profile(str(payload.get("profile_id") or ""))
    except (OSError, json.JSONDecodeError, CompatibilityError) as exc:
        raise NativeL1EvidenceGateError(
            "native L1 hypothesis ledger profile binding is invalid"
        ) from exc
    if profile.delta_schema_version != "2.1":
        raise NativeL1EvidenceGateError(
            "native L1 requires a v2.1 hypothesis ledger profile binding"
        )


def _selected_run_id(project: Path, seed: dict, args) -> str:
    explicit = str(getattr(args, "evidence_run_id", "") or "").strip()
    if explicit:
        return explicit
    active = research_seed.active_l1_native_evidence_run_id(project, seed)
    if active:
        return str(active)
    unique = research_seed.unique_l1_native_evidence_run_id(project, seed)
    if unique:
        return str(unique)
    raise NativeL1EvidenceGateError(
        "native L1 evidence binding is missing or ambiguous; select one exact Curie acquisition run"
    )


def _audit_native_divergence(project: Path, seed: dict, binding: dict,
                             cand_id: str) -> tuple[bool, str]:
    """Apply the cross-round divergence gate to native Curie QueryPlans.

    Native v2.1 must not depend on ``L1_research.md`` merely to preserve the
    historical divergence policy.  The authoritative search queries are the
    QueryPlans frozen inside the active EvidencePack, so compare those query
    families against the existing cross-round cache instead.
    """
    cf = _candidate_file(project, cand_id)
    fm = _load_yaml_front(cf) if cf and cf.exists() else {}
    if not fm.get("from_memory"):
        return True, ""
    if fm.get("loop_type") != "divergent":
        return True, ""

    from research_loop import l05_curie

    try:
        pack = l05_curie.load_frozen_evidence_pack(
            project,
            binding["evidence_pack"],
            candidate_id=str(seed["candidate_id"]),
            round_id=str(seed["round_id"]),
            seed_sha256=research_seed.seed_sha256(seed),
        )
    except (KeyError, l05_curie.CurieContractError) as exc:
        return False, f"divergence gate: active frozen EvidencePack is invalid: {exc}"

    queries: list[str] = []
    for plan in pack.get("query_plans", []):
        if not isinstance(plan, dict):
            continue
        for item in plan.get("queries", []):
            if not isinstance(item, dict):
                continue
            query = str(item.get("query") or "").strip()
            if query:
                queries.append(query)

    fams = {_query_family_key(query) for query in queries if query.strip()}
    cache = {_query_family_key(query) for query in _load_query_family_cache(project)}
    new = {family for family in fams if family and family not in cache}
    need = DIVERGENCE_MIN_NEW_QUERY_FAMILIES
    if len(new) < need:
        return False, (
            f"divergence gate: only {len(new)} new query families "
            f"(need >= {need}); reused={sorted(fams & cache)}"
        )
    return True, ""


def install(context_module) -> None:
    """Install the native evidence authority gate once."""
    if getattr(context_module, "_l05_native_context_gate_installed", False):
        return
    original = context_module.cmd_assemble_context

    def cmd_assemble_context(args):
        if not _is_native_l1(args):
            return original(args)

        project = Path(args.project_dir)
        try:
            _require_native_l1_profile(project)
            seed = research_seed.load_l1_research_seed(project, str(args.cand_id))
            run_id = _selected_run_id(project, seed, args)
            binding = research_seed.load_l1_native_evidence_binding(
                project, seed, run_id
            )
            binding_entry = research_seed.native_evidence_binding_manifest_entry(
                project, seed, run_id
            )
        except (research_seed.ResearchSeedError, NativeL1EvidenceGateError) as exc:
            print(f"ERROR: native L1 evidence binding gate -- {exc}", file=sys.stderr)
            return 3

        # The historical L1 pre-research block also enforced cross-round
        # divergence and branch-coverage constraints.  Preserve those policies
        # before suppressing only the legacy acquisition gate.  Divergence now
        # reads the authoritative native QueryPlans, not legacy summary text.
        dok, dreason = _audit_native_divergence(
            project, seed, binding, str(args.cand_id)
        )
        if not dok:
            print(f"ERROR: {dreason}", file=sys.stderr)
            return 3
        bok, breason = _audit_branch_coverage(project, str(args.cand_id))
        if not bok:
            print(f"ERROR: {breason}", file=sys.stderr)
            return 3

        legacy_l1_config = PRE_RESEARCH_MAP.pop("L1", None)
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = original(args)
        finally:
            if legacy_l1_config is not None:
                PRE_RESEARCH_MAP["L1"] = legacy_l1_config

        original_stdout = stdout.getvalue()
        original_stderr = stderr.getvalue()
        if rc != 0:
            sys.stdout.write(original_stdout)
            sys.stderr.write(original_stderr)
            return rc

        prefix = "[audit] context manifest:"
        paths = [
            Path(line[len(prefix):].strip())
            for line in original_stderr.splitlines()
            if line.startswith(prefix)
        ]
        if len(paths) != 1:
            sys.stderr.write(original_stderr)
            print(
                "ERROR: native L1 evidence binding gate -- canonical context did not report exactly one manifest",
                file=sys.stderr,
            )
            return 3
        manifest_path = paths[0]
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if str(manifest.get("delta_schema_version") or "") != "2.1":
                raise NativeL1EvidenceGateError(
                    "native L1 context manifest is not schema 2.1"
                )
            manifest["pre_research"] = {
                "type": "curie_frozen_evidence",
                "present": True,
                "evidence_run_id": run_id,
                "native_evidence_binding": binding_entry,
                "evidence_pack": binding["evidence_pack"],
                "legacy_summary_injected": False,
            }
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except (
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            NativeL1EvidenceGateError,
        ) as exc:
            print(f"ERROR: native L1 evidence binding gate -- {exc}", file=sys.stderr)
            return 3

        sys.stdout.write(original_stdout)
        sys.stderr.write(original_stderr)
        return 0

    context_module.cmd_assemble_context = cmd_assemble_context
    context_module._l05_native_context_gate_installed = True
