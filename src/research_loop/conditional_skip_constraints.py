"""Ledger-side authorization for the existing verified L2 skip receipt."""
from __future__ import annotations

import contextvars
from pathlib import Path

from research_loop.compatibility import get_profile
from research_loop.delta import artifact_for_node, _v2_candidate_delta_file
from research_loop.node_skips import validate_l2_skip_receipt


_SKIP_CONTEXT: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "rlr_verified_l2_skip", default=False
)


def _validate_l3_after_skip(
    constraint_module,
    *,
    con,
    delta,
    project_id: str,
    candidate_id: str,
    round_id: str,
) -> None:
    finalized_l1 = constraint_module._finalized_hypothesis_ids(
        con,
        project_id=project_id,
        candidate_id=candidate_id,
        round_id=round_id,
        node="L1",
    )
    submitted = [str(item["hypothesis_id"]) for item in delta["triage"]]
    if (
        not finalized_l1
        or len(submitted) != len(set(submitted))
        or set(submitted) != finalized_l1
    ):
        raise constraint_module.ConstraintViolation(
            "L3 triage must cover every finalized L1 hypothesis exactly once"
        )
    selected = [
        item for item in delta["triage"]
        if item["disposition"] == "SELECTED"
    ]
    if len(selected) > 4:
        raise constraint_module.ConstraintViolation(
            "L3 permits at most four SELECTED hypotheses"
        )


def install(ledger_module, constraint_module) -> None:
    """Accept L3 without L2 only when the exact L1-bound skip receipt verifies."""
    if getattr(ledger_module, "_CONDITIONAL_SKIP_CONSTRAINTS_INSTALLED", False):
        return

    original_validate = ledger_module.validate_finalized_upstream
    original_commit = ledger_module.HypothesisLedger.commit_delta

    def validate_finalized_upstream(**kwargs):
        try:
            return original_validate(**kwargs)
        except constraint_module.ConstraintViolation as exc:
            if (
                _SKIP_CONTEXT.get()
                and kwargs.get("node") == "L3"
                and str(exc) == "L3 requires a finalized L2 emission"
            ):
                return _validate_l3_after_skip(
                    constraint_module,
                    con=kwargs["con"],
                    delta=kwargs["delta"],
                    project_id=str(kwargs["project_id"]),
                    candidate_id=str(kwargs["candidate_id"]),
                    round_id=str(kwargs["round_id"]),
                )
            raise

    def commit_delta(self, *args, **kwargs):
        delta = kwargs.get("delta")
        allow_skip = False
        if (
            str(kwargs.get("node") or "") == "L3"
            and isinstance(delta, dict)
            and str(delta.get("schema_version") or "") == "2.1"
        ):
            project = Path(kwargs["project_dir"])
            candidate_id = str(kwargs["candidate_id"])
            profile = get_profile(self.project_profile(project))
            key = artifact_for_node(profile, "L1").storage_key
            l1_path = _v2_candidate_delta_file(project, key, candidate_id)
            if l1_path is not None and l1_path.is_file():
                allow_skip, _detail = validate_l2_skip_receipt(
                    project, candidate_id, l1_path
                )
        token = _SKIP_CONTEXT.set(bool(allow_skip))
        try:
            return original_commit(self, *args, **kwargs)
        finally:
            _SKIP_CONTEXT.reset(token)

    ledger_module.validate_finalized_upstream = validate_finalized_upstream
    ledger_module.HypothesisLedger.commit_delta = commit_delta
    ledger_module._CONDITIONAL_SKIP_CONSTRAINTS_INSTALLED = True
