"""Hypothesis-ledger CLI commands extracted from the runtime engine."""

import json
import os
import sys
from pathlib import Path

import pitfall_ledger as pl

from research_loop import deep_research, hypothesis_migration, research_seed
from research_loop import l4_evidence_bundle
from research_loop.common import _append_decision, _now, _set_status, _stamp
from research_loop.delta import (
    DELTA_PERSONA,
    artifact_for_node,
    artifact_key_for,
    DELTA_SCHEMAS,
    _candidate_delta_file,
    _delta_for_candidate,
    _validate_delta,
    _v2_candidate_delta_file,
)
from research_loop.gates import (
    _audit_l0_contract,
    _audit_l0_memory,
    _audit_l10_evidence,
    _audit_l10_traceability,
    _audit_l4_methods,
    _audit_l6_traceability,
    _audit_l7_manifest,
)
from research_loop.hypothesis_contracts import DELTA_SCHEMA_VERSION, SUPPORTED_DELTA_SCHEMA_VERSIONS
from research_loop.hypothesis_ledger import (
    HypothesisLedger,
    LedgerError,
    binding_path,
    canonical_json,
)
from research_loop.compatibility import PROFILE_V20, get_profile
from research_loop.persona_catalog import PersonaCatalogError, resolve_persona_template
from research_loop.providers.base import RunReceipt
from research_loop.paths import (
    _audit_dir,
    _candidate_file,
    _pre_research_file,
    _sha256,
)
from research_loop.preresearch import (
    _merge_query_family_cache,
    _parse_pre_research_provenance,
    _query_family_key,
)
from research_loop.topology import DECISION_TRANSITIONS
from research_loop.yamlio import _load_yaml_front, _replace_field


FINAL_STATUSES = {"KEEP", "REVISE", "DOWNGRADE", "DROP", "ARCHIVED"}

def _ledger_for(project_dir, configured_path=None, *, require_binding=True):
    """Construct the configured ledger without permitting a silent fallback."""
    store_path = configured_path or os.environ.get("RLR_HYPOTHESIS_STORE")
    if not store_path:
        raise LedgerError("hypothesis ledger requires --knowledge-store or RLR_HYPOTHESIS_STORE")
    if require_binding and not Path(store_path).is_file():
        raise LedgerError(f"configured hypothesis ledger does not exist: {store_path}")
    ledger = HypothesisLedger(store_path)
    if require_binding:
        ledger.require_activated_project(project_dir)
    return ledger


def _write_hypothesis_commit_receipt(project_dir, receipt):
    directory = Path(project_dir) / "08_Audit" / "hypothesis_commits"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (f"H{int(receipt['commit_seq']):08d}_"
                          f"{receipt['candidate_id']}_{receipt['node']}.json")
    raw = canonical_json(receipt)
    if target.exists():
        if target.read_text(encoding="utf-8") != raw:
            raise LedgerError(f"hypothesis commit receipt collision: {target}")
        return target
    with target.open("x", encoding="utf-8") as handle:
        handle.write(raw)
    return target


def _select_v2_delta_path(canonical_path: Path, content: str | None = None,
                          *, retry_index: int | None = None) -> Path:
    """Keep repeated emissions append-only while preserving first-write paths."""
    canonical = Path(canonical_path)
    suffix = "".join(canonical.suffixes)
    base_name = canonical.name[:-len(suffix)] if suffix else canonical.name

    def retry_path(index: int) -> Path:
        return canonical.with_name(f"{base_name}_retry{index}{suffix}")

    if retry_index is not None and int(retry_index) > 1:
        index = int(retry_index)
        while True:
            candidate = retry_path(index)
            if not candidate.exists():
                return candidate
            if content is None or candidate.read_text(encoding="utf-8") == content:
                return candidate
            index += 1
    if not canonical.exists() or content is None:
        return canonical
    if canonical.read_text(encoding="utf-8") == content:
        return canonical
    index = 2
    while True:
        candidate = retry_path(index)
        if not candidate.exists():
            return candidate
        if candidate.read_text(encoding="utf-8") == content:
            return candidate
        index += 1


def _validate_native_receipts(
    args,
    profile,
    *,
    source_file: Path,
    project_id: str,
    round_id: str,
    ledger: HypothesisLedger,
) -> dict:
    """Validate context/provider provenance before every native v2.1 write."""
    if profile.delta_schema_version != "2.1":
        return {}
    if (
        not getattr(args, "context_manifest", None)
        and getattr(args, "receipt", None)
    ):
        print(
            "WARNING: --receipt is deprecated; use --context-manifest.",
            file=sys.stderr,
        )
    manifest_arg = (getattr(args, "context_manifest", None)
                    or getattr(args, "receipt", None))
    provider_arg = getattr(args, "provider_receipt", None)
    if not manifest_arg or not provider_arg:
        raise LedgerError(
            "native v2.1 emission requires --context-manifest and --provider-receipt"
        )
    manifest_path = Path(manifest_arg)
    receipt_path = Path(provider_arg)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"invalid context manifest: {exc}") from exc
    if manifest.get("schema_version") != "ContextManifest/v2":
        raise LedgerError("context manifest must use ContextManifest/v2")
    expected = {
        "project_id": project_id,
        "candidate_id": str(args.cand_id),
        "round_id": str(round_id),
        "node": str(args.node),
        "persona": str(args.persona),
        "profile_id": profile.profile_id,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise LedgerError(f"context manifest {field} does not match emission")
    rendered_path = Path(str(manifest.get("rendered_context_path") or ""))
    rendered_hash = str(manifest.get("rendered_context_sha256") or "")
    if not rendered_path.is_file() or _sha256(rendered_path) != rendered_hash:
        raise LedgerError("rendered context is missing or changed since assemble-context")
    try:
        resolved = resolve_persona_template(profile, str(args.persona))
    except PersonaCatalogError as exc:
        raise LedgerError(f"persona catalog validation failed: {exc}") from exc
    for field, value in {
        "persona_catalog_sha256": resolved.catalog_sha256,
        "persona_catalog_entry_sha256": resolved.entry_sha256,
        "persona_template_sha256": resolved.template_sha256,
        "persona_body_sha256": resolved.body_sha256,
    }.items():
        if manifest.get(field) != value:
            raise LedgerError(f"context manifest {field} changed since assemble-context")
    for injected in manifest.get("injected_deltas") or []:
        injected_path = Path(str(injected.get("path") or ""))
        expected_hash = str(injected.get("sha256") or "")
        try:
            injected_path.resolve().relative_to(Path(args.project_dir).resolve())
        except ValueError as exc:
            raise LedgerError(
                "context manifest injected delta path escapes the project"
            ) from exc
        if not injected_path.is_file() or _sha256(injected_path) != expected_hash:
            raise LedgerError(
                "context manifest injected delta is missing or changed"
            )
    authorization = manifest.get("hypothesis_authorization")
    if not isinstance(authorization, dict):
        raise LedgerError(
            "native v2.1 context manifest requires hypothesis authorization"
        )
    snapshot = ledger.load_authorized_context(
        args.project_dir, str(authorization.get("authorization_id") or "")
    )
    authorization_expected = {
        "candidate_id": str(args.cand_id),
        "round_id": str(round_id),
        "node": str(args.node),
        "as_of_commit_seq": authorization.get("as_of_commit_seq"),
        "projection_hash": authorization.get("projection_hash"),
        "artifact_hash": authorization.get("artifact_hash"),
        "event_ids": authorization.get("event_ids"),
    }
    for field, value in authorization_expected.items():
        if snapshot.get(field) != value:
            raise LedgerError(
                f"context authorization {field} does not match its snapshot"
            )
    if (
        args.node == "L9b"
        and not profile.l9_parallel
        and not any(event.get("node") == "L9a" for event in snapshot.get("events", []))
    ):
        raise LedgerError(
            "native L9b receipt requires finalized L9a in the authorized snapshot"
        )
    pre_research = manifest.get("pre_research") or {}
    native_binding = pre_research.get("native_evidence_binding")
    recorded_evidence = pre_research.get("evidence_artifacts")
    if native_binding is not None:
        if not isinstance(native_binding, dict) or args.node != "L1":
            raise LedgerError("native evidence binding is invalid for this emission")
        run_id = str(pre_research.get("evidence_run_id") or "")
        if not run_id:
            raise LedgerError("native L1 context has no exact evidence_run_id")
        try:
            seed = research_seed.load_l1_research_seed(
                args.project_dir, str(args.cand_id)
            )
            current_binding = research_seed.native_evidence_binding_manifest_entry(
                args.project_dir, seed, run_id
            )
        except (
            research_seed.ResearchSeedError,
            OSError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            raise LedgerError(f"exact native evidence binding is invalid: {exc}") from exc
        if current_binding != native_binding:
            raise LedgerError("native evidence binding changed since context assembly")
        if str(native_binding.get("evidence_run_id") or "") != run_id:
            raise LedgerError("native evidence binding run does not match context")
        recorded_evidence = None
    elif recorded_evidence:
        run_id = str(recorded_evidence.get("run_id") or "")
        try:
            current_evidence = deep_research.evidence_artifact_manifest(
                args.project_dir, str(args.cand_id), str(args.node), run_id
            )
        except deep_research.DeepResearchError as exc:
            raise LedgerError(f"exact evidence run is invalid: {exc}") from exc
        if current_evidence != recorded_evidence:
            raise LedgerError(
                "evidence artifacts changed since context assembly"
            )
        ok, reason = deep_research.audit_evidence_pack(
            args.project_dir, str(args.cand_id), str(args.node), run_id=run_id
        )
        if not ok:
            raise LedgerError(f"exact evidence run failed revalidation: {reason}")
    elif args.node in {"L1", "L4", "L8.5"}:
        raise LedgerError(
            f"native {args.node} emission requires exact evidence artifact hashes"
        )
    try:
        provider = RunReceipt.read(receipt_path)
    except ValueError as exc:
        raise LedgerError(f"invalid provider receipt: {exc}") from exc
    for field, value in expected.items():
        if getattr(provider, field) != value:
            raise LedgerError(f"provider receipt {field} does not match emission")
    if (provider.context_manifest_hash != _sha256(manifest_path)
            or provider.rendered_context_hash != rendered_hash
            or provider.context_hash != rendered_hash):
        raise LedgerError("provider receipt does not bind the exact context manifest and rendered context")
    source_hash = _sha256(source_file)
    provider_delta_path = Path(str(provider.provider_delta_path or ""))
    if (
        not provider_delta_path.is_file()
        or provider_delta_path.resolve() != source_file.resolve()
        or provider.provider_delta_hash != source_hash
        or _sha256(provider_delta_path) != provider.provider_delta_hash
    ):
        raise LedgerError("provider receipt delta hash does not match emitted source file")
    raw_provider_delta_path = Path(str(provider.raw_provider_delta_path or ""))
    if provider.schema_version == "RunReceipt/v2":
        if (
            not raw_provider_delta_path.is_file()
            or _sha256(raw_provider_delta_path) != provider.raw_provider_delta_hash
        ):
            raise LedgerError("provider receipt raw delta is missing or changed")
        if raw_provider_delta_path.resolve() != provider_delta_path.resolve():
            transformation_path = Path(str(provider.transformation_receipt_path or ""))
            if (
                not transformation_path.is_file()
                or _sha256(transformation_path) != provider.transformation_receipt_hash
            ):
                raise LedgerError("provider transformation receipt is missing or changed")
            try:
                transformation = json.loads(
                    transformation_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise LedgerError(f"invalid provider transformation receipt: {exc}") from exc
            expected_edge = {
                "raw_provider_delta_path": str(raw_provider_delta_path),
                "raw_provider_delta_sha256": provider.raw_provider_delta_hash,
                "bound_delta_path": str(provider_delta_path),
                "bound_delta_sha256": provider.provider_delta_hash,
            }
            for field, value in expected_edge.items():
                if transformation.get(field) != value:
                    raise LedgerError(
                        f"provider transformation receipt {field} does not match emitted artifacts"
                    )
    prompt_path = Path(str(provider.prompt_file or ""))
    if not prompt_path.is_file() or _sha256(prompt_path) != provider.prompt_hash:
        raise LedgerError("provider receipt prompt file is missing or changed")
    return {
        "context_manifest_path": str(manifest_path),
        "context_manifest_sha256": _sha256(manifest_path),
        "provider_receipt_path": str(receipt_path),
        "provider_receipt_sha256": _sha256(receipt_path),
        "rendered_context_sha256": rendered_hash,
        "provider_prompt_sha256": provider.prompt_hash,
        "provider_delta_sha256": provider.provider_delta_hash,
        "raw_provider_delta_sha256": provider.raw_provider_delta_hash,
        "transformation_receipt_sha256": provider.transformation_receipt_hash,
        "code_state": ({
            "git_head": provider.git_head,
            "git_dirty": provider.git_dirty,
            "working_tree_diff_sha256": provider.working_tree_diff_sha256,
            "config_sha256": provider.config_sha256,
            "code_state_id": provider.code_state_id,
        } if provider.schema_version == "RunReceipt/v2" else None),
        "evidence_artifacts": recorded_evidence,
        "native_evidence_binding": native_binding,
        "authorization_id": snapshot["authorization_id"],
        "authorization_artifact_sha256": snapshot["artifact_hash"],
    }


def _bind_l4_delta_for_commit(args, data, source_file):
    """Resolve L4C model handles at the single canonical commit boundary.

    The provider-owned file remains the raw source artifact.  This function
    only performs the deterministic semantic-to-canonical binding in memory;
    the caller persists the resulting delta once, at the ledger artifact
    boundary, and records the raw-to-bound edge there.
    """
    manifest_arg = (getattr(args, "context_manifest", None)
                    or getattr(args, "receipt", None))
    if not manifest_arg:
        raise LedgerError("L4 handle binding requires a context manifest")
    try:
        manifest = json.loads(Path(manifest_arg).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"invalid L4 context manifest for handle binding: {exc}") from exc
    pre_research = manifest.get("pre_research") or {}
    evidence_ref = pre_research.get("evidence_artifacts") or {}
    run_id = str(evidence_ref.get("run_id") or "")
    if not run_id:
        raise LedgerError("L4 context manifest lacks the frozen evidence run ID")
    evidence = deep_research._artifact(
        args.project_dir, args.cand_id, "L4", run_id=run_id
    )
    if not evidence or evidence.get("evidence_bundle_schema") != l4_evidence_bundle.EVIDENCE_BUNDLE_SCHEMA:
        candidates = data.get("method_candidates") or []
        uses_handles = any(
            isinstance(candidate, dict)
            and any(
                candidate.get(field)
                for field in (
                    "evidence_card_handles",
                    "evidence_gap_handles",
                    "method_anchor_handles",
                )
            )
            for candidate in candidates
        )
        if uses_handles:
            raise LedgerError("L4 handle binding requires a staged L4B evidence bundle")
        # Historical v2.1 L4 deltas with no L4C method-candidate handles do
        # not participate in the staged bundle contract.  They retain their
        # existing strategy-only validation path.
        return data, None
    try:
        resolved, binding = l4_evidence_bundle.resolve_l4c_reference_handles(
            evidence, data
        )
    except (deep_research.DeepResearchError, TypeError, ValueError) as exc:
        raise LedgerError(f"L4 reference binding rejected: {exc}") from exc
    raw_path = Path(source_file)
    if not raw_path.is_file():
        raise LedgerError(f"raw L4 provider delta is missing: {raw_path}")
    binding = {
        **binding,
        "raw_provider_delta_path": str(raw_path),
        "raw_provider_delta_sha256": _sha256(raw_path),
    }
    return resolved, binding


def _emit_delta_v2(args, data):
    """Persist a v2 delta and its ledger events as one fail-closed boundary."""
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    l4_binding = None
    try:
        ledger = _ledger_for(project_dir, getattr(args, "knowledge_store", None))
        project_id = str(ledger.require_binding(project_dir)["project_id"])
        profile_id = ledger.project_profile(project_dir)
        if profile_id == PROFILE_V20:
            raise LedgerError(
                "v2.0-legacy projects are read-only; public emit-delta is disabled"
            )
        descriptor = artifact_for_node(get_profile(profile_id), args.node)
        if args.persona != descriptor.display_persona:
            raise LedgerError(
                f"{args.node} persona {args.persona} conflicts with profile {profile_id}; "
                f"expected {descriptor.display_persona}"
            )
        delta_key = descriptor.storage_key
        fm = _load_yaml_front(cf)
        round_id = str(fm.get("round_id") or "1")
        provenance = _validate_native_receipts(
            args, get_profile(profile_id), source_file=Path(args.file),
            project_id=project_id, round_id=round_id, ledger=ledger,
        )
        if args.node == "L4":
            data, l4_binding = _bind_l4_delta_for_commit(
                args, data, Path(args.file)
            )
    except LedgerError as exc:
        print(f"DELTA V2 VALIDATION: REJECT\n  {exc}", file=sys.stderr)
        return 1
    if delta_key not in DELTA_PERSONA:
        print(f"ERROR: no schema for profile artifact {delta_key}", file=sys.stderr)
        return 2
    out_file = _v2_candidate_delta_file(project_dir, delta_key, args.cand_id)
    if out_file is None:
        print(f"ERROR: cannot resolve v2 artifact path for {delta_key}", file=sys.stderr)
        return 2
    native_pack_version = (
        (provenance.get("native_evidence_binding") or {}).get(
            "evidence_pack_version"
        )
        if isinstance(provenance, dict)
        else None
    )
    out_file = _select_v2_delta_path(
        out_file,
        retry_index=(int(native_pack_version)
                     if native_pack_version not in (None, "") else None),
    )
    receipt_path = None

    def persist_finalized_artifacts(result):
        nonlocal receipt_path
        created = []
        temporary = out_file.with_suffix(out_file.suffix + ".tmp")
        transformation_path = None

        def cleanup():
            for path in reversed(created):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

        try:
            raw = canonical_json(result.normalized_delta)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            if out_file.exists() and out_file.read_text(encoding="utf-8") != raw:
                raise LedgerError(
                    f"refusing to overwrite a different v2 delta: {out_file}"
                )
            if not out_file.exists():
                temporary.write_text(raw, encoding="utf-8")
                os.replace(temporary, out_file)
                created.append(out_file)
            actual = _sha256(out_file)
            if actual != result.delta_hash:
                raise LedgerError(
                    "persisted v2 delta hash differs from ledger emission hash"
                )
            if l4_binding is not None:
                edge = {
                    **l4_binding,
                    "bound_delta_path": str(out_file),
                    "bound_delta_sha256": actual,
                }
                transformation_path = (
                    project_dir / "08_Audit" / "artifact_transformations"
                    / f"{args.cand_id}_{args.node}_{actual}.json"
                )
                edge_raw = canonical_json(edge)
                if transformation_path.exists():
                    if transformation_path.read_text(encoding="utf-8") != edge_raw:
                        raise LedgerError(
                            "L4 transformation receipt collision: "
                            f"{transformation_path}"
                        )
                else:
                    transformation_path.parent.mkdir(parents=True, exist_ok=True)
                    transformation_path.write_text(edge_raw, encoding="utf-8")
                    created.append(transformation_path)
                provenance["native_artifact_binding"] = edge
                provenance["transformation_receipt_path"] = str(
                    transformation_path
                )
                provenance["transformation_receipt_sha256"] = _sha256(
                    transformation_path
                )
            expected_receipt = (
                project_dir / "08_Audit" / "hypothesis_commits"
                / f"H{int(result.receipt['commit_seq']):08d}_"
                  f"{result.receipt['candidate_id']}_{result.receipt['node']}.json"
            )
            receipt_existed = expected_receipt.exists()
            receipt_path = _write_hypothesis_commit_receipt(
                project_dir, {**result.receipt, "provenance": provenance}
            )
            if not receipt_existed:
                created.append(receipt_path)
            return actual, _sha256(receipt_path), cleanup
        except Exception as exc:
            cleanup()
            if isinstance(exc, LedgerError):
                raise
            raise LedgerError(
                f"atomic artifact persistence failed: {exc}"
            ) from exc

    try:
        # Filesystem/provider checks remain at their actual use boundary, but
        # must complete before the ledger persistence transaction.  Pure
        # cross-delta rules live in constraint_validation inside that
        # transaction.
        _errors = []
        if args.node == "L4":
            ok_m, m_reason = _audit_l4_methods(
                project_dir, args.cand_id, data)
            if not ok_m:
                _errors.append(m_reason)
        if args.node == "L6":
            ok_l6, l6_reason = _audit_l6_traceability(
                project_dir, args.cand_id, data)
            if not ok_l6:
                _errors.append(l6_reason)
        if args.node == "L7":
            ok_l7, l7_reason = _audit_l7_manifest(
                project_dir, args.cand_id, data)
            if not ok_l7:
                _errors.append(l7_reason)
        if args.node == "L10b":
            ok_l10, l10_reason = _audit_l10_traceability(
                project_dir, args.cand_id, data)
            if not ok_l10:
                _errors.append(l10_reason)
            ok_evidence, evidence_reason = _audit_l10_evidence(
                project_dir, args.cand_id, data)
            if not ok_evidence:
                _errors.append(evidence_reason)
        if _errors:
            print("DELTA V2 VALIDATION: REJECT", file=sys.stderr)
            for e in _errors:
                print(f"  {e}", file=sys.stderr)
            return 1
        result = ledger.commit_delta(project_dir=project_dir, candidate_id=args.cand_id,
                                     round_id=round_id, node=args.node,
                                     persona=args.persona, delta=data,
                                     delta_path=out_file,
                                     _finalize_callback=persist_finalized_artifacts)
        if args.node == "L7":
            try:
                _write_exec_manifest(project_dir, args.cand_id, data)
            except Exception:
                pass
    except LedgerError as exc:
        print(f"DELTA V2 VALIDATION: REJECT\n  {exc}", file=sys.stderr)
        return 1
    print("DELTA V2 VALIDATION: PASS")
    print(f"  schema: {delta_key}@{result.normalized_delta['schema_version']}")
    print(f"  written: {out_file}")
    print(f"  hypothesis commit: {receipt_path}")
    return 0


def cmd_emit_delta(args):
    """Validate delta JSON against schema and write to 02_Agent_Notes/."""
    project_dir = Path(args.project_dir)
    src = Path(args.file)
    if not src.exists():
        print(f"ERROR: delta file not found: {src}", file=sys.stderr)
        return 2

    delta_key = artifact_key_for(args.node, args.persona)
    schema = DELTA_SCHEMAS.get(delta_key)
    if schema is None:
        print(f"ERROR: no schema for {delta_key}", file=sys.stderr)
        return 2

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {e}", file=sys.stderr)
        return 2

    if data.get("schema_version") in SUPPORTED_DELTA_SCHEMA_VERSIONS:
        return _emit_delta_v2(args, data)
    if binding_path(project_dir).exists():
        print("ERROR: activated projects accept only committed delta v2 artifacts; "
              "use hypothesis-migrate for v1 input", file=sys.stderr)
        return 2

    # Recursive structural validation against the (possibly nested) schema:
    # enforces container types AND the required keys of objects inside lists and
    # dicts (so hypotheses=[{"foo":1}] -- element missing id/text -- is rejected,
    # not just hypotheses="str").
    errors = _validate_delta(schema, data)

    # L0 dependency checks
    if args.node == "L0":
        dep_errors = []

        # L0 input_verified completeness check:
        # Each entry must be a dict with path/files/format/classification/verified/notes.
        # Bare strings like "valid" are rejected — Linnaeus must record full info.
        iv = data.get("input_verified", {})
        if not isinstance(iv, dict) or not iv:
            errors.append("L0 input_verified is empty or not a dict. "
                          "Register every input alias from source_input.")
        else:
            required_iv_keys = {"path", "files", "format",
                                "classification", "verified", "notes"}
            valid_classes = {"primary", "fallback", "reference-only", "forbidden"}
            for alias, entry in iv.items():
                if not isinstance(entry, dict):
                    errors.append(
                        f"input_verified['{alias}'] is a bare "
                        f"{type(entry).__name__} ('{entry}'), not a dict. "
                        f"Must contain: {required_iv_keys}")
                    continue
                missing = required_iv_keys - set(entry.keys())
                if missing:
                    errors.append(
                        f"input_verified['{alias}'] missing keys: {missing}")
                if not entry.get("verified", True):
                    cls = entry.get("classification", "primary")
                    if cls in ("primary", "fallback"):
                        errors.append(
                            f"input_verified['{alias}'].verified is false — "
                            f"primary/fallback input must be confirmed")
                cls = entry.get("classification", "")
                if cls and cls not in valid_classes:
                    errors.append(
                        f"input_verified['{alias}'].classification='{cls}', "
                        f"must be one of {valid_classes}")
                if not entry.get("path"):
                    errors.append(
                        f"input_verified['{alias}'].path is empty")
                if not entry.get("files"):
                    cls = entry.get("classification", "primary")
                    if cls in ("primary", "fallback"):
                        errors.append(
                            f"input_verified['{alias}'].files is empty — "
                            f"primary/fallback input must list key filenames")
        # 1. Check Obsidian Vault
        vault = os.environ.get("OBSIDIAN_VAULT")
        if not vault:
            dep_errors.append("Obsidian Vault path is not set in environment variable $OBSIDIAN_VAULT.")
        else:
            expanded_vault = Path(os.path.expandvars(vault)).expanduser()
            if not expanded_vault.is_dir():
                dep_errors.append(f"Obsidian Vault directory does not exist: {vault}")
            elif not (expanded_vault / ".obsidian").is_dir():
                dep_errors.append(
                    f"Obsidian Vault is not a vault root (missing .obsidian): "
                    f"{expanded_vault}")
        # 2. Check Zotero
        zotero_env = os.environ.get("ZOTERO_API_KEY") or os.environ.get("ZOTERO_USER_ID")
        zotero_dirs = [
            os.path.expandvars(r"%PROGRAMFILES%\Zotero\zotero.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Zotero\zotero.exe"),
            os.path.expanduser(r"~\AppData\Local\Zotero"),
        ]
        zotero_found = bool(zotero_env) or any(os.path.exists(d) for d in zotero_dirs)
        if not zotero_found:
            dep_errors.append("Zotero is not installed or Zotero API credentials ($ZOTERO_API_KEY / $ZOTERO_USER_ID) are missing.")
        # 3. Check Academic Research Suite / Skill
        skills = data.get("skills_found", [])
        has_academic = any("academic" in s.lower() for s in skills)
        custom_dirs = [
            Path(r"C:\Users\hk200\.gemini\config\plugins\custom-skills\skills\academic-research-suite"),
            Path(r"C:\Users\hk200\.codex\skills\academic-research-suite"),
            Path(project_dir) / ".agents" / "skills" / "academic-research-suite",
        ]
        if not has_academic and not any(d.exists() for d in custom_dirs):
            dep_errors.append("academic-research-suite skill is not found in skills catalog or plugins directory.")
        if dep_errors:
            errors.extend(dep_errors)

        # v0.6: cross-loop memory gate (no-op for legacy candidates)
        ok_mem, mem_reason = _audit_l0_memory(project_dir, args.cand_id, data)
        if not ok_mem:
            errors.append(f"prior_loop_memory gate: {mem_reason}")

        # strict L0 input-contract gate: the SAME validator as assemble-context
        # L0 (no receipt/echo). A malformed/absent contract rejects the delta
        # (rc=1) at persist time too.
        ok_c, c_reason = _audit_l0_contract(project_dir, args.cand_id)
        if not ok_c:
            errors.append(f"L0 input-contract gate: {c_reason}")

    # v0.6: L4 method-card grounding gate (no-op for legacy candidates)
    if args.node == "L4":
        ok_m, m_reason = _audit_l4_methods(project_dir, args.cand_id, data)
        if not ok_m:
            errors.append(m_reason)

    # v0.6: L6 script-grounding traceability gate (no-op for legacy candidates)
    if args.node == "L6":
        ok_l6, l6_reason = _audit_l6_traceability(project_dir, args.cand_id, data)
        if not ok_l6:
            errors.append(l6_reason)

    # v0.6: L7 execution-traceability gate (no-op for legacy candidates)
    if args.node == "L7":
        ok_l7, l7_reason = _audit_l7_manifest(project_dir, args.cand_id, data)
        if not ok_l7:
            errors.append(l7_reason)

    # v0.6: L10b decision-traceability gate (no-op for legacy candidates)
    if args.node == "L10b":
        ok_l10, l10_reason = _audit_l10_traceability(project_dir, args.cand_id, data)
        if not ok_l10:
            errors.append(l10_reason)
        ok_evidence, evidence_reason = _audit_l10_evidence(project_dir, args.cand_id, data)
        if not ok_evidence:
            errors.append(evidence_reason)

    declared_candidate = data.get("candidate_id")
    if (declared_candidate is not None
            and str(declared_candidate) != str(args.cand_id)):
        errors.append(
            f"candidate_id mismatch: delta declares '{declared_candidate}', "
            f"command targets '{args.cand_id}'")
    data["candidate_id"] = args.cand_id

    # Check for extra keys (candidate_id is universal ownership metadata).
    extra = set(data.keys()) - set(schema.keys()) - {"candidate_id"}
    if extra:
        print(f"WARNING: extra keys (allowed): {extra}", file=sys.stderr)

    if errors:
        print("DELTA VALIDATION: REJECT", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)

        # Issue 6: Auto-correction instructions
        schema_keys = list(schema.keys())
        print("\n=== AI AUTO-CORRECTION INSTRUCTIONS ===", file=sys.stdout)
        print("Your previous delta JSON validation failed. Please review the errors above and correct the file:\n", file=sys.stdout)
        for e in errors:
            print(f"- ERROR: {e}", file=sys.stdout)
        print(f"\nRequired schema keys for {delta_key}: {schema_keys}", file=sys.stdout)
        print("Expected JSON structure:", file=sys.stdout)
        print(json.dumps(schema, indent=2, default=lambda x: x.__name__), file=sys.stdout)
        print("========================================\n", file=sys.stdout)
        return 1

    # Receipt verification (problem 5). Policy A (optional but verified): if a
    # context_manifest is supplied, confirm the upstream deltas this node
    # consumed still hash to what the manifest recorded -- catches an upstream
    # delta being re-emitted/changed between assemble-context and emit-delta.
    # No receipt -> skip; receipt + mismatch -> reject.
    manifest_id = None
    manifest = {}
    verification = "skipped (no receipt)"
    mismatches = []
    if args.receipt:
        rp = Path(args.receipt)
        if not rp.exists():
            print(f"ERROR: receipt not found: {rp}", file=sys.stderr)
            return 2
        try:
            manifest = json.loads(rp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"ERROR: invalid receipt JSON: {e}", file=sys.stderr)
            return 2
        manifest_id = manifest.get("manifest_id")
        for inj in manifest.get("injected_deltas", []):
            injected_path = inj.get("path")
            cur = _sha256(injected_path) if injected_path else None
            if cur != inj.get("sha256"):
                mismatches.append(inj.get("delta_key"))
        verification = "pass" if not mismatches else "FAIL"
        if mismatches:
            print("DELTA VALIDATION: REJECT (receipt hash mismatch)",
                  file=sys.stderr)
            print(f"  upstream deltas changed since assemble-context: "
                  f"{', '.join(str(m) for m in mismatches)}", file=sys.stderr)
            return 1

    # New outputs are candidate-owned; canonical legacy files remain untouched.
    out_file = _candidate_delta_file(project_dir, delta_key, args.cand_id)
    if out_file is None:
        out_dir = Path(project_dir) / "02_Agent_Notes" / args.persona
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{args.cand_id}_{delta_key}_delta.json"
    else:
        out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    # Run receipt (problem 5): record what was produced + the verification
    # outcome, referencing the context_manifest. Keeps the delta itself pure.
    receipt_id = _stamp()
    run_receipt = {
        "receipt_id": receipt_id,
        "candidate_id": args.cand_id,
        "node": args.node,
        "persona": args.persona,
        "delta_key": delta_key,
        "emitted_at": _now(),
        "output_delta_path": str(out_file),
        "output_delta_sha256": _sha256(out_file),
        "context_manifest_id": manifest_id,
        "upstream_verification": verification,
        "mismatches": mismatches,
        "caveman_mode": manifest.get("caveman_mode"),
        "original_est_tokens": manifest.get("original_est_tokens"),
        "compressed_est_tokens": manifest.get("compressed_est_tokens"),
        "compression_applied": manifest.get("compression_applied"),
        "required_fields_preserved": manifest.get(
            "required_fields_preserved"),
        "pre_research": manifest.get("pre_research"),
    }
    rr = _audit_dir(project_dir) / f"run_receipt_{args.node}_{receipt_id}.json"
    rr.write_text(json.dumps(run_receipt, indent=2, ensure_ascii=False),
                  encoding="utf-8")

    print(f"DELTA VALIDATION: PASS")
    print(f"  schema: {delta_key}")
    print(f"  written: {out_file}")
    print(f"  run receipt: {rr} (upstream: {verification})")

    # v0.6: after a valid L7 delta, write the execution-traceability manifest.
    if args.node == "L7":
        try:
            _write_exec_manifest(project_dir, args.cand_id, data)
        except Exception:
            pass

    # v0.6: after a valid L1 delta, register this round's query families in the
    # cross-loop cache so a later divergent loop can prove it searched new ground.
    if args.node == "L1":
        try:
            _prf = _pre_research_file(project_dir, "L1")
            if _prf.exists():
                _prov = _parse_pre_research_provenance(_prf.read_text(encoding="utf-8"))
                _fams = {_query_family_key(q) for q in _prov.get("query_log", []) if q.strip()}
                if _fams:
                    _merge_query_family_cache(project_dir, _fams)
        except Exception:
            pass

    # Auto-record L7 pitfalls: extract failures and warnings from delta,
    # record as draft pitfalls so pitfall-scan picks them up next round.
    if args.node == "L7":
        for f_text in data.get("failures", []):
            failure = str(f_text)[:200]
            pl.record_pitfall(project_dir, args.cand_id, args.node,
                              "execution_failure", failure,
                              failure, "", severity="hard_stop",
                              error_class="system")
            pl.record_pitfall(
                project_dir, args.cand_id, "L0", "preflight_gate_candidate",
                f"Previous L7 execution failure: {failure}"[:200],
                failure,
                "Resolve or explicitly waive the previous L7 execution "
                f"failure before passing L0: {failure}",
                severity="hard_stop", error_class="system",
                promoted_to="preflight_gate")
        for w_text in data.get("warnings", []):
            pl.record_pitfall(project_dir, args.cand_id, args.node,
                              "execution_failure", str(w_text)[:200],
                              str(w_text)[:200], "", severity="warn",
                              error_class="agent")
    return 0


def cmd_finalize_candidate(args):
    """Apply the L10b v2 candidate decision after its ledger commit."""
    project_dir = Path(args.project_dir)
    cf = _candidate_file(project_dir, args.cand_id)
    if not cf.exists():
        print(f"ERROR: no candidate {args.cand_id}", file=sys.stderr)
        return 2
    delta_path = _delta_for_candidate(project_dir, "L10b_oppenheimer", args.cand_id)
    if not delta_path or not str(delta_path).endswith(".v2.json"):
        print("ERROR: finalize-candidate requires a committed L10b v2 delta", file=sys.stderr)
        return 1
    try:
        data = json.loads(delta_path.read_text(encoding="utf-8"))
        decision, reason = data["decision"], data["reason"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: invalid committed L10b v2 delta: {exc}", file=sys.stderr)
        return 1
    fm = _load_yaml_front(cf)
    frm = fm.get("current_status")
    if decision not in FINAL_STATUSES or decision not in DECISION_TRANSITIONS.get(frm, set()):
        print(f"ERROR: illegal final transition {frm} -> {decision}", file=sys.stderr)
        return 1
    seq = _append_decision(project_dir, args.cand_id, frm, decision, reason,
                           route_to="Oppenheimer", agent="Oppenheimer", kind="final_decision")
    _set_status(project_dir, args.cand_id, decision, "Oppenheimer")
    _replace_field(cf, "final_decision", f"{decision}: {reason}")
    print(f"D{seq:04d}: {frm} -> {decision}")
    return 0


def _ledger_cli(args):
    try:
        return _ledger_for(args.project_dir, args.knowledge_store)
    except LedgerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return None


def cmd_hypothesis_show(args):
    ledger = _ledger_cli(args)
    if ledger is None:
        return 2
    try:
        graph = ledger.graph(args.hypothesis_id, as_of=args.as_of)
    except LedgerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(graph, indent=2, ensure_ascii=False))
    return 0


def cmd_hypothesis_history(args):
    ledger = _ledger_cli(args)
    if ledger is None:
        return 2
    try:
        history = ledger.history(args.hypothesis_id, after=args.after, limit=args.limit)
    except LedgerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(history, indent=2, ensure_ascii=False))
    return 0


def cmd_hypothesis_search(args):
    ledger = _ledger_cli(args)
    if ledger is None:
        return 2
    print(json.dumps(ledger.search(args.text or "", args.limit), indent=2, ensure_ascii=False))
    return 0


def cmd_hypothesis_verify(args):
    ledger = _ledger_cli(args)
    if ledger is None:
        return 2
    problems = ledger.verify(rebuild=args.rebuild)
    if problems:
        print("HYPOTHESIS LEDGER: REJECT", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print("HYPOTHESIS LEDGER: PASS")
    return 0


def cmd_hypothesis_migrate(args):
    try:
        if not Path(args.knowledge_store).is_file():
            raise LedgerError(
                "hypothesis-migrate requires an existing shared knowledge store"
            )
        target_profile = getattr(args, "target_profile", None)
        if target_profile and args.dry_run:
            ledger = HypothesisLedger.open_readonly(args.knowledge_store)
        else:
            ledger = _ledger_for(args.project_dir, args.knowledge_store,
                                 require_binding=False)
        if target_profile:
            if args.dry_run:
                report = hypothesis_migration.dry_run_profile_upgrade(
                    args.project_dir, ledger
                )
                print(json.dumps(report, ensure_ascii=False))
                return 0
            if not args.resolution or not args.resolved_by:
                raise LedgerError(
                    "profile migration commit requires --resolution and --resolved-by"
                )
            receipt = hypothesis_migration.upgrade_profile(
                args.project_dir,
                ledger,
                resolution_path=args.resolution,
                resolved_by=args.resolved_by,
            )
            print(json.dumps(receipt, ensure_ascii=False))
            return 0
        if args.dry_run:
            report, path = hypothesis_migration.dry_run(args.project_dir, ledger)
            print(json.dumps({**report, "report_path": str(path)},
                             ensure_ascii=False))
            return 0
        if not args.resolution or not args.resolved_by:
            raise LedgerError(
                "migration commit requires --resolution and --resolved-by"
            )
        manifest = hypothesis_migration.commit(
            args.project_dir, ledger, args.resolution, args.resolved_by
        )
        print(json.dumps(manifest, ensure_ascii=False))
        return 0
    except (LedgerError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: hypothesis migration failed: {exc}", file=sys.stderr)
        return 2


def cmd_hypothesis_authorize_context(args):
    ledger = _ledger_cli(args)
    if ledger is None:
        return 2
    try:
        results = [ledger.materialize_authorized_context(
            args.project_dir, args.cand_id, args.round_id, node,
            as_of=args.as_of,
        ) for node in args.node]
    except LedgerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(results, ensure_ascii=False))
    return 0
