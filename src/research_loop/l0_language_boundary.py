"""Normalize user scientific prose once before canonical L0 is frozen."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from research_loop import l0_language_provider as provider
from research_loop.l0_language import L0LanguageError, normalize_semantic_fields


class L0LanguageBoundaryError(ValueError):
    """Raised when user input cannot become canonical English safely."""


def _semantic_fields(contract: dict) -> dict[str, str]:
    current = contract.get("current_round") or {}
    source = contract.get("source_input") or {}
    fields = {
        "scientific_question": str(contract.get("scientific_question") or "").strip(),
        "hypothesis": str(current.get("hypothesis") or "").strip(),
    }
    description = str(source.get("description") or "").strip()
    if description:
        fields["source_description"] = description
    return fields


def normalize_contract(project_dir, candidate_id, contract):
    """Translate once, validate once, and return the canonical English contract."""
    if not isinstance(contract, dict):
        raise L0LanguageBoundaryError("L0 contract must be a mapping")

    def translator(fields):
        return provider._translate(project_dir, candidate_id, fields)

    try:
        normalized, _receipt = normalize_semantic_fields(
            _semantic_fields(contract), translator=translator
        )
    except L0LanguageError as exc:
        raise L0LanguageBoundaryError(str(exc)) from exc

    result = copy.deepcopy(contract)
    result["scientific_question"] = normalized["scientific_question"]
    result.setdefault("current_round", {})["hypothesis"] = normalized["hypothesis"]
    if "source_description" in normalized and isinstance(result.get("source_input"), dict):
        result["source_input"]["description"] = normalized["source_description"]
    return result


def install(lifecycle_module):
    """Install normalization only where a canonical L0 contract is first created."""
    if getattr(lifecycle_module, "_l0_language_boundary_installed", False):
        return

    original_new_candidate = lifecycle_module.cmd_new_candidate

    def cmd_new_candidate(args):
        original_initial = lifecycle_module.l0_contract.build_initial_contract
        original_continuation = lifecycle_module.l0_contract.build_continuation_contract
        project_dir = Path(args.project_dir)

        def initial(cand_id, round_id, question, source_input, new_hypothesis):
            return normalize_contract(
                project_dir,
                cand_id,
                original_initial(cand_id, round_id, question, source_input, new_hypothesis),
            )

        def continuation(
            cand_id, round_id, parent_round_id, previous_candidate_id,
            question, source_input, previous_round, new_hypothesis,
        ):
            return normalize_contract(
                project_dir,
                cand_id,
                original_continuation(
                    cand_id, round_id, parent_round_id, previous_candidate_id,
                    question, source_input, previous_round, new_hypothesis,
                ),
            )

        lifecycle_module.l0_contract.build_initial_contract = initial
        lifecycle_module.l0_contract.build_continuation_contract = continuation
        try:
            return original_new_candidate(args)
        except L0LanguageBoundaryError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        finally:
            lifecycle_module.l0_contract.build_initial_contract = original_initial
            lifecycle_module.l0_contract.build_continuation_contract = original_continuation

    lifecycle_module.cmd_new_candidate = cmd_new_candidate

    original_normalize_command = lifecycle_module.cmd_normalize_l0_input

    def cmd_normalize_l0_input(args):
        original_normalize = lifecycle_module.l0_intake.normalize_request
        project_dir = Path(args.project)

        def normalize_request(*nargs, **nkwargs):
            result = original_normalize(*nargs, **nkwargs)
            contract = result.get("contract") if isinstance(result, dict) else None
            if not isinstance(contract, dict):
                return result
            updated = dict(result)
            candidate_id = str(contract.get("candidate_id") or "").strip()
            updated["contract"] = normalize_contract(project_dir, candidate_id, contract)
            return updated

        lifecycle_module.l0_intake.normalize_request = normalize_request
        try:
            return original_normalize_command(args)
        except L0LanguageBoundaryError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        finally:
            lifecycle_module.l0_intake.normalize_request = original_normalize

    lifecycle_module.cmd_normalize_l0_input = cmd_normalize_l0_input
    lifecycle_module._l0_language_boundary_installed = True
