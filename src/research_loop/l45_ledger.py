"""Transactional integration of the deterministic L4.5 commit gate."""
from __future__ import annotations

from pathlib import Path

from research_loop.l4_pipeline import (
    PIPELINE_SCHEMA_VERSION,
    commit_l45_method_projection,
)


def install(ledger_module) -> None:
    """Run L4.5 before the native L4 hypothesis receipt is persisted.

    The wrapper sits inside the existing ledger finalize callback because that
    callback calls ``_write_hypothesis_commit_receipt``. Raising here aborts the
    ledger transaction and lets its existing cleanup remove a newly written L4C
    delta. Legacy, non-staged L4 evidence remains unchanged.
    """
    if getattr(ledger_module, "_l45_ledger_installed", False):
        return
    original = ledger_module._write_hypothesis_commit_receipt

    def write_hypothesis_commit_receipt(project_dir, receipt):
        if str(receipt.get("node") or "") != "L4":
            return original(project_dir, receipt)

        provenance = receipt.get("provenance") or {}
        evidence_ref = provenance.get("evidence_artifacts") or {}
        run_id = str(evidence_ref.get("run_id") or "")
        candidate_id = str(receipt.get("candidate_id") or "")
        evidence = (
            ledger_module.deep_research._artifact(
                project_dir, candidate_id, "L4", run_id=run_id
            )
            if run_id
            else None
        )
        if not evidence or evidence.get("pipeline_schema") != PIPELINE_SCHEMA_VERSION:
            return original(project_dir, receipt)

        delta_path = ledger_module._v2_candidate_delta_file(
            Path(project_dir), "L4_fisher", candidate_id
        )
        if delta_path is None:
            raise ValueError("cannot resolve persisted L4C delta for L4.5")

        _, commit_path, created = commit_l45_method_projection(
            project_dir, candidate_id, evidence, delta_path
        )
        try:
            return original(project_dir, receipt)
        except Exception:
            if created:
                try:
                    commit_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    ledger_module._l45_original_write_hypothesis_commit_receipt = original
    ledger_module._write_hypothesis_commit_receipt = write_hypothesis_commit_receipt
    ledger_module._l45_ledger_installed = True
