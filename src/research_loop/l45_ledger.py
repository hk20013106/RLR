"""Transactional integration of the deterministic L4.5 commit gate."""
from __future__ import annotations

import contextvars
from pathlib import Path

from research_loop.l4_pipeline import (
    PIPELINE_SCHEMA_VERSION,
    commit_l45_method_projection,
)


_ACTIVE_L45_STATE = contextvars.ContextVar("rlr_active_l45_state", default=None)


def _remove_created_projection(state) -> None:
    if not state or not state.get("created") or state.get("path") is None:
        return
    try:
        Path(state["path"]).unlink(missing_ok=True)
    except OSError:
        pass


def install(ledger_module) -> None:
    """Install L4.5 inside the native ledger finalization transaction.

    The receipt wrapper runs L4.5 only for staged L4B evidence. The
    ``HypothesisLedger.commit_delta`` wrapper composes the existing filesystem
    cleanup with removal of a newly created L4.5 projection, so failures after
    the receipt write (including database finalization failures) cannot leave an
    orphan projection. Legacy evidence remains unchanged.
    """
    if getattr(ledger_module, "_l45_ledger_installed", False):
        return

    original_receipt = ledger_module._write_hypothesis_commit_receipt

    def write_hypothesis_commit_receipt(project_dir, receipt):
        if str(receipt.get("node") or "") != "L4":
            return original_receipt(project_dir, receipt)

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
            return original_receipt(project_dir, receipt)

        # Native ContextManifest/v2 records the exact evidence file set. Recheck
        # it here immediately before L4.5 so the projection cannot bind a newer
        # or otherwise different L4B run than Fisher actually consumed.
        if "files" in evidence_ref:
            current_evidence = ledger_module.deep_research.evidence_artifact_manifest(
                project_dir, candidate_id, "L4", run_id
            )
            if current_evidence != evidence_ref:
                error_type = getattr(
                    ledger_module.deep_research, "DeepResearchError", ValueError
                )
                raise error_type(
                    "L4B evidence artifacts changed since context assembly"
                )

        delta_path = ledger_module._v2_candidate_delta_file(
            Path(project_dir), "L4_fisher", candidate_id
        )
        if delta_path is None:
            raise ValueError("cannot resolve persisted L4C delta for L4.5")

        _, commit_path, created = commit_l45_method_projection(
            project_dir, candidate_id, evidence, delta_path
        )
        state = _ACTIVE_L45_STATE.get()
        if state is not None:
            state["path"] = commit_path
            state["created"] = bool(created)
        try:
            return original_receipt(project_dir, receipt)
        except Exception:
            if state is not None:
                _remove_created_projection(state)
                state["created"] = False
            elif created:
                try:
                    commit_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    ledger_module._l45_original_write_hypothesis_commit_receipt = original_receipt
    ledger_module._write_hypothesis_commit_receipt = write_hypothesis_commit_receipt

    ledger_class = getattr(ledger_module, "HypothesisLedger", None)
    if ledger_class is not None:
        original_commit_delta = ledger_class.commit_delta

        def commit_delta(self, *args, **kwargs):
            original_finalize = kwargs.get("_finalize_callback")
            node = str(kwargs.get("node") or "")
            if node != "L4" or original_finalize is None:
                return original_commit_delta(self, *args, **kwargs)

            def finalize_with_l45_cleanup(result):
                state = {"path": None, "created": False}
                token = _ACTIVE_L45_STATE.set(state)
                try:
                    artifact_sha, receipt_sha, cleanup = original_finalize(result)
                except Exception:
                    _remove_created_projection(state)
                    raise
                finally:
                    _ACTIVE_L45_STATE.reset(token)

                def cleanup_with_l45():
                    _remove_created_projection(state)
                    cleanup()

                return artifact_sha, receipt_sha, cleanup_with_l45

            forwarded = dict(kwargs)
            forwarded["_finalize_callback"] = finalize_with_l45_cleanup
            return original_commit_delta(self, *args, **forwarded)

        ledger_module._l45_original_commit_delta = original_commit_delta
        ledger_class.commit_delta = commit_delta

    ledger_module._l45_ledger_installed = True
