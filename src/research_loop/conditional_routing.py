"""Conditional L1→L3 routing with auditable L2 skip receipts."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

from research_loop.node_skips import (
    NodeSkipError,
    ensure_l2_skip_receipt,
    l2_skip_decision,
    validate_l2_skip_receipt,
)


def _l1_path(module, project: Path, candidate_id: str) -> Path | None:
    path = module._delta_for_candidate(project, "L1_einstein", candidate_id)
    return Path(path) if path and Path(path).is_file() else None


def _hypothesis_count(l1_path: Path) -> int:
    try:
        delta = json.loads(l1_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    hypotheses = delta.get("hypotheses")
    if not isinstance(hypotheses, list):
        return 0
    ids = [
        str(item.get("hypothesis_id") or "").strip()
        for item in hypotheses if isinstance(item, dict)
    ]
    if len(ids) != len(hypotheses) or not all(ids) or len(ids) != len(set(ids)):
        return 0
    return len(ids)


def _skip_block(receipt: dict) -> str:
    return "\n".join([
        "=== NODE SKIP: L2 ===",
        f"reason: {receipt['reason']}",
        f"hypothesis_count: {receipt['hypothesis_count']}",
        f"threshold: {receipt['threshold']}",
        f"l1_delta_sha256: {receipt['l1_delta_sha256']}",
        "No Feynman attack occurred. The small hypothesis set bypassed L2 for efficiency;",
        "L3 must still independently assess testability, redundancy, feasibility, novelty,",
        "impact, and the predeclared falsification criteria.",
    ])


def install(lifecycle_module, context_module) -> None:
    """Patch the CLI-bound functions before :mod:`research_loop.cli` imports them."""
    lifecycle = lifecycle_module
    context = context_module
    if getattr(lifecycle, "_CONDITIONAL_L2_ROUTING_INSTALLED", False):
        return

    original_next_step = lifecycle.cmd_next_step
    original_assemble_context = context.cmd_assemble_context

    def cmd_next_step(args):
        project = Path(args.project_dir)
        candidate_file = lifecycle._candidate_file(project, args.cand_id)
        if not candidate_file.is_file():
            return original_next_step(args)
        try:
            status = lifecycle._load_yaml_front(candidate_file).get("current_status", "NEW")
        except Exception:
            return original_next_step(args)
        if status != "IDEA_PROPOSED":
            return original_next_step(args)
        l1_path = _l1_path(lifecycle, project, args.cand_id)
        if l1_path is None:
            return original_next_step(args)
        # Existing completed attacks always win over a later skip policy.
        l2_path = lifecycle._delta_for_candidate(project, "L2_feynman", args.cand_id)
        if l2_path and Path(l2_path).is_file():
            return original_next_step(args)
        count = _hypothesis_count(l1_path)
        decision = l2_skip_decision(count)
        if decision == "run":
            return original_next_step(args)
        if decision == "invalid":
            print(json.dumps({
                "error": "committed L1 contains no valid unique hypotheses; cannot route to L2 or L3"
            }))
            return 1
        try:
            receipt = ensure_l2_skip_receipt(project, args.cand_id, l1_path)
        except NodeSkipError as exc:
            print(json.dumps({"error": f"cannot create L2 skip receipt: {exc}"}))
            return 1

        original_belongs = lifecycle._delta_belongs_to_candidate

        def belongs(project_dir, delta_key, candidate_id):
            if delta_key == "L2_feynman" and str(candidate_id) == str(args.cand_id):
                return True
            return original_belongs(project_dir, delta_key, candidate_id)

        lifecycle._delta_belongs_to_candidate = belongs
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                rc = original_next_step(args)
        finally:
            lifecycle._delta_belongs_to_candidate = original_belongs
        raw = buffer.getvalue()
        if rc != 0:
            print(raw, end="")
            return rc
        try:
            packet = json.loads(raw)
        except json.JSONDecodeError:
            print(raw, end="")
            return rc
        if packet.get("node") != "L3":
            print(raw, end="")
            return rc
        packet["skipped_nodes"] = [{
            "node": "L2",
            "reason": receipt["reason"],
            "hypothesis_count": receipt["hypothesis_count"],
        }]
        print(json.dumps(packet, indent=2))
        return rc

    def cmd_assemble_context(args):
        if getattr(args, "node", None) != "L3":
            return original_assemble_context(args)
        project = Path(args.project_dir)
        l1_path = _l1_path(context, project, args.cand_id)
        if l1_path is None:
            return original_assemble_context(args)
        l2_path = context._delta_for_candidate(project, "L2_feynman", args.cand_id)
        if l2_path and Path(l2_path).is_file():
            return original_assemble_context(args)
        receipt_path = project / "08_Audit" / "node_skips" / f"{args.cand_id}_L2.json"
        if not receipt_path.is_file():
            return original_assemble_context(args)
        ok, detail = validate_l2_skip_receipt(project, args.cand_id, l1_path)
        if not ok:
            print(f"ERROR: L2 skip receipt is invalid: {detail}", file=sys.stderr)
            return 3
        receipt = detail
        audit_dir = project / "08_Audit"
        before = set(audit_dir.glob("context_manifest_L3_*.json")) if audit_dir.is_dir() else set()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = original_assemble_context(args)
        raw = buffer.getvalue()
        if rc != 0:
            print(raw, end="")
            return rc
        placeholder = "=== DELTA: L2 (not yet emitted) ==="
        if placeholder not in raw:
            print(raw, end="")
            return rc
        rendered = raw.replace(placeholder, _skip_block(receipt), 1)
        after = set(audit_dir.glob("context_manifest_L3_*.json"))
        created = sorted(after - before, key=lambda path: path.stat().st_mtime_ns)
        if not created:
            print("ERROR: L3 skip context has no new context manifest", file=sys.stderr)
            return 3
        manifest_path = created[-1]
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            rendered_path = Path(manifest["rendered_context_path"])
            rendered_path.write_text(rendered.rstrip("\n"), encoding="utf-8")
            manifest["rendered_context_sha256"] = hashlib.sha256(
                rendered_path.read_bytes()
            ).hexdigest()
            manifest["node_skips"] = [{
                "node": "L2",
                "reason": receipt["reason"],
                "hypothesis_count": receipt["hypothesis_count"],
                "receipt_path": receipt_path.relative_to(project).as_posix(),
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            }]
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            print(f"ERROR: cannot bind L2 skip into L3 context manifest: {exc}",
                  file=sys.stderr)
            return 3
        print(rendered, end="")
        return rc

    lifecycle.cmd_next_step = cmd_next_step
    context.cmd_assemble_context = cmd_assemble_context
    lifecycle._CONDITIONAL_L2_ROUTING_INSTALLED = True
