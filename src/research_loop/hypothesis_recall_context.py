"""Native L1 context and receipt gates for historical hypothesis recall."""
from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from research_loop import research_seed
from research_loop.compatibility import get_profile
from research_loop.hypothesis_ledger import HypothesisLedger, LedgerError, canonical_json
from research_loop.hypothesis_recall import (
    create_recall,
    load_recall,
    recall_manifest_entry,
    recall_path,
    validate_recall,
)
from research_loop.paths import _sha256
from research_loop.yamlio import _load_yaml_front


_SECTION = "=== HISTORICAL HYPOTHESIS RECALL ==="
_AUTO_RECALL_ENV = "RLR_AUTO_HYPOTHESIS_RECALL"


def _native_l1_identity(args) -> tuple[HypothesisLedger, dict[str, Any], str] | None:
    if str(getattr(args, "node", "")) != "L1":
        return None
    project = Path(args.project_dir)
    binding = project / "00_Preflight" / "hypothesis_store_binding.json"
    if not binding.is_file():
        return None
    store = getattr(args, "knowledge_store", None) or os.environ.get(
        "RLR_HYPOTHESIS_STORE"
    )
    if not store:
        raise LedgerError(
            "hypothesis recall requires --knowledge-store or RLR_HYPOTHESIS_STORE"
        )
    ledger = HypothesisLedger(store)
    profile = get_profile(ledger.project_profile(project))
    if profile.delta_schema_version != "2.1":
        return None
    candidate = _load_yaml_front(
        project / "01_Candidates" / f"{args.cand_id}.md"
    )
    try:
        seed = research_seed.load_l1_research_seed(project, str(args.cand_id))
    except research_seed.ResearchSeedError as exc:
        raise LedgerError(f"canonical L1 research seed is invalid: {exc}") from exc
    round_id = str(seed["round_id"])
    return ledger, candidate, round_id


def _load_bound_recall(
    args,
    ledger: HypothesisLedger,
    candidate: dict[str, Any],
    round_id: str,
) -> dict[str, Any]:
    project = Path(args.project_dir)
    try:
        artifact = load_recall(project, str(args.cand_id), round_id)
    except LedgerError:
        if os.environ.get(_AUTO_RECALL_ENV) != "1":
            raise
        try:
            seed = research_seed.load_l1_research_seed(
                project, str(args.cand_id)
            )
        except research_seed.ResearchSeedError as exc:
            raise LedgerError(
                f"canonical L1 research seed is invalid: {exc}"
            ) from exc
        query_text = " ".join((
            str(seed["scientific_question"]),
            str(seed["hypothesis_seed"]),
        )).strip()
        artifact = create_recall(
            ledger,
            project,
            str(args.cand_id),
            round_id,
            query_text=query_text,
        )
    validate_recall(
        ledger,
        project,
        artifact,
        expected_candidate_id=str(args.cand_id),
        expected_round_id=round_id,
    )
    return artifact


def _concise_recall(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": artifact["schema_version"],
        "as_of_commit_seq": artifact["as_of_commit_seq"],
        "query": artifact["query"],
        "results": [
            {
                key: item.get(key)
                for key in (
                    "hypothesis_id",
                    "hypothesis_family_id",
                    "statement",
                    "epistemic_status",
                    "latest_workflow_status",
                    "reactivation_eligibility",
                    "reactivation_requirements",
                    "source_occurrence_id",
                    "unresolved_blocker_event_ids",
                )
            }
            for item in artifact.get("results", [])
        ],
    }


def _manifest_path(stderr_text: str) -> Path:
    prefix = "[audit] context manifest:"
    matches = [
        line[len(prefix):].strip()
        for line in stderr_text.splitlines()
        if line.startswith(prefix)
    ]
    if len(matches) != 1:
        raise LedgerError("assembled context did not report exactly one manifest")
    return Path(matches[0])


def _remove_generated_context(manifest_path: Path | None) -> None:
    if manifest_path is None:
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rendered = Path(str(manifest.get("rendered_context_path") or ""))
        if rendered.is_file():
            rendered.unlink()
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    manifest_path.unlink(missing_ok=True)


def _l1_evidence_binding_entry(args, manifest: dict[str, Any]) -> dict[str, Any]:
    project = Path(args.project_dir)
    try:
        seed = research_seed.load_l1_research_seed(project, str(args.cand_id))
    except research_seed.ResearchSeedError as exc:
        raise LedgerError(f"canonical L1 research seed is invalid: {exc}") from exc
    pre_research = manifest.get("pre_research")
    if not isinstance(pre_research, dict):
        raise LedgerError("native L1 context manifest requires exact pre-research evidence")
    run_id = str(pre_research.get("evidence_run_id") or "")
    if not run_id:
        raise LedgerError("native L1 context manifest requires exact evidence_run_id")
    try:
        return research_seed.evidence_binding_manifest_entry(
            project, seed, run_id
        )
    except research_seed.ResearchSeedError as exc:
        raise LedgerError(str(exc)) from exc


def _install_context_gate(context_module) -> None:
    original = context_module.cmd_assemble_context

    def cmd_assemble_context(args):
        # Preserve all existing gate precedence. Literature, divergence, and
        # upstream provenance failures must remain visible before recall is
        # required for an otherwise-valid L1 context.
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = original(args)
        original_stdout = stdout.getvalue()
        original_stderr = stderr.getvalue()
        if rc != 0:
            sys.stdout.write(original_stdout)
            sys.stderr.write(original_stderr)
            return rc

        try:
            identity = _native_l1_identity(args)
        except LedgerError as exc:
            print(f"ERROR: hypothesis recall gate -- {exc}", file=sys.stderr)
            return 2
        if identity is None:
            sys.stdout.write(original_stdout)
            sys.stderr.write(original_stderr)
            return 0
        ledger, candidate, round_id = identity

        manifest_path: Path | None = None
        rendered_path: Path | None = None
        try:
            manifest_path = _manifest_path(original_stderr)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            binding_entry = _l1_evidence_binding_entry(args, manifest)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError,
                LedgerError) as exc:
            _remove_generated_context(manifest_path)
            print(f"ERROR: L1 evidence binding gate -- {exc}", file=sys.stderr)
            return 3

        try:
            artifact = _load_bound_recall(
                args, ledger, candidate, round_id
            )
            rendered_path = Path(str(manifest["rendered_context_path"]))
            context_text = rendered_path.read_text(encoding="utf-8")
            recall_text = canonical_json(_concise_recall(artifact))
            context_text = context_text.rstrip() + "\n\n" + _SECTION + "\n" + recall_text
            budget = int(getattr(args, "context_token_budget", 8000) or 0)
            estimated = context_module._estimate_tokens(context_text)
            if budget and estimated > budget:
                raise LedgerError(
                    "context token budget exceeded after hypothesis recall "
                    f"(~{estimated} > {budget})"
                )
            rendered_path.write_text(context_text, encoding="utf-8")
            manifest["rendered_context_sha256"] = _sha256(rendered_path)
            manifest["research_seed_evidence_binding"] = binding_entry
            manifest["hypothesis_recall"] = recall_manifest_entry(
                args.project_dir, str(args.cand_id), round_id
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError,
                LedgerError) as exc:
            _remove_generated_context(manifest_path)
            print(f"ERROR: hypothesis recall gate -- {exc}", file=sys.stderr)
            return 2

        print(context_text)
        sys.stderr.write(original_stderr)
        return 0

    context_module.cmd_assemble_context = cmd_assemble_context


def _install_receipt_gate(ledger_commands_module) -> None:
    original = ledger_commands_module._validate_native_receipts

    def _validate_native_receipts(
        args,
        profile,
        *,
        source_file,
        project_id,
        round_id,
        ledger,
    ):
        provenance = original(
            args,
            profile,
            source_file=source_file,
            project_id=project_id,
            round_id=round_id,
            ledger=ledger,
        )
        if profile.delta_schema_version != "2.1" or str(args.node) != "L1":
            return provenance
        manifest_arg = (
            getattr(args, "context_manifest", None)
            or getattr(args, "receipt", None)
        )
        try:
            manifest = json.loads(Path(manifest_arg).read_text(encoding="utf-8"))
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            raise LedgerError(f"invalid context manifest: {exc}") from exc

        recorded_seed = manifest.get("research_seed")
        if not isinstance(recorded_seed, dict):
            raise LedgerError(
                "native L1 context manifest requires canonical research seed"
            )
        try:
            current_seed = research_seed.load_l1_research_seed(
                args.project_dir, str(args.cand_id)
            )
        except research_seed.ResearchSeedError as exc:
            raise LedgerError(
                f"native L1 canonical research seed is invalid: {exc}"
            ) from exc
        if str(current_seed["round_id"]) != str(round_id):
            raise LedgerError(
                "native L1 canonical research seed round does not match emission"
            )
        current_seed_entry = research_seed.manifest_entry(current_seed)
        if recorded_seed != current_seed_entry:
            raise LedgerError(
                "L1 canonical research seed changed since context assembly"
            )

        recorded_binding = manifest.get("research_seed_evidence_binding")
        if not isinstance(recorded_binding, dict):
            raise LedgerError(
                "native L1 context manifest requires research-seed evidence binding"
            )
        evidence_run_id = str(recorded_binding.get("evidence_run_id") or "")
        if not evidence_run_id:
            raise LedgerError(
                "native L1 research-seed evidence binding requires evidence_run_id"
            )
        try:
            current_binding = research_seed.evidence_binding_manifest_entry(
                args.project_dir, current_seed, evidence_run_id
            )
        except research_seed.ResearchSeedError as exc:
            raise LedgerError(
                f"native L1 research-seed evidence binding is invalid: {exc}"
            ) from exc
        if recorded_binding != current_binding:
            raise LedgerError(
                "L1 research-seed evidence binding changed since context assembly"
            )

        recorded = manifest.get("hypothesis_recall")
        if not isinstance(recorded, dict):
            raise LedgerError(
                "native L1 context manifest requires hypothesis recall"
            )
        expected_path = recall_path(
            args.project_dir, str(args.cand_id), str(round_id)
        ).resolve()
        recorded_path = Path(str(recorded.get("artifact_path") or "")).resolve()
        project = Path(args.project_dir).resolve()
        try:
            recorded_path.relative_to(project)
        except ValueError as exc:
            raise LedgerError("hypothesis recall path escapes the project") from exc
        if recorded_path != expected_path:
            raise LedgerError("hypothesis recall path does not match this L1 round")
        if not recorded_path.is_file() or _sha256(recorded_path) != recorded.get(
            "artifact_sha256"
        ):
            raise LedgerError("hypothesis recall file is missing or changed")
        artifact = load_recall(
            args.project_dir, str(args.cand_id), str(round_id)
        )
        validate_recall(
            ledger,
            args.project_dir,
            artifact,
            expected_candidate_id=str(args.cand_id),
            expected_round_id=str(round_id),
        )
        current = recall_manifest_entry(
            args.project_dir, str(args.cand_id), str(round_id)
        )
        if recorded != current:
            raise LedgerError(
                "hypothesis recall metadata changed since context assembly"
            )
        return {
            **provenance,
            "research_seed": current_seed_entry,
            "research_seed_evidence_binding": current_binding,
            "hypothesis_recall": current,
        }

    ledger_commands_module._validate_native_receipts = _validate_native_receipts


def install(context_module, ledger_commands_module) -> None:
    """Install additive gates before canonical CLI functions are imported."""
    if getattr(context_module, "_hypothesis_recall_context_installed", False):
        return
    _install_context_gate(context_module)
    _install_receipt_gate(ledger_commands_module)
    context_module._hypothesis_recall_context_installed = True
