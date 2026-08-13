"""Verification metadata for bounded RLR software repairs.

Profiles name existing RLR invariants and repository-native validation surfaces.
They are not replacement validators and they never mutate research state.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import validate_maintenance_event


VERIFICATION_PROFILE_SCHEMA = "RLRVerificationProfile/v1"


@dataclass(frozen=True)
class VerificationStep:
    step_id: str
    command: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True)
class VerificationProfile:
    schema_version: str
    profile_id: str
    risk_class: str
    protected_contracts: tuple[str, ...]
    required_validation: tuple[VerificationStep, ...]
    forbidden_success_shortcuts: tuple[str, ...]


_FORBIDDEN_SHORTCUTS = (
    "weaken_validator",
    "convert_fail_to_warn",
    "rewrite_expected_hash",
    "skip_required_test",
    "parallel_state_owner",
    "swallow_fail_closed_exception",
    "unrelated_refactor",
)


def _pytest_step(step_id: str, *args: str) -> VerificationStep:
    return VerificationStep(
        step_id=step_id,
        command=(sys.executable, "-m", "pytest", *args),
    )


_PROFILES = {
    "l0_state_integrity": VerificationProfile(
        schema_version=VERIFICATION_PROFILE_SCHEMA,
        profile_id="l0_state_integrity",
        risk_class="high",
        protected_contracts=(
            "l0_restore_fail_closed",
            "provider_after_restore_only",
            "round_manifest_hash_integrity",
            "continuation_manifest_binding_integrity",
            "runner_nonzero_propagation",
        ),
        required_validation=(
            _pytest_step(
                "meta_contract",
                "tests/test_meta_rlr_contracts.py",
                "tests/test_meta_rlr_observer.py",
                "-q",
            ),
            _pytest_step(
                "root_entrypoint_regression",
                "tests/test_root_run_loop_entrypoint.py",
                "-q",
            ),
            _pytest_step(
                "l0_contract_regression",
                "-q",
                "-k",
                "l0_state or l0_input_contract or cross_round",
            ),
            _pytest_step("full_regression", "-q"),
        ),
        forbidden_success_shortcuts=_FORBIDDEN_SHORTCUTS,
    ),
    "l4_frozen_corpus_integrity": VerificationProfile(
        schema_version=VERIFICATION_PROFILE_SCHEMA,
        profile_id="l4_frozen_corpus_integrity",
        risk_class="high",
        protected_contracts=(
            "l4a_frozen_handoff",
            "l4b_frozen_corpus_only",
            "l4b_no_new_search_or_citation",
            "l45_exact_lineage_binding",
        ),
        required_validation=(
            _pytest_step(
                "meta_contract",
                "tests/test_meta_rlr_contracts.py",
                "tests/test_meta_rlr_observer.py",
                "-q",
            ),
            _pytest_step(
                "l4_contract_regression",
                "-q",
                "-k",
                "l4b or l4_pipeline or l45 or frozen_corpus",
            ),
            _pytest_step("full_regression", "-q"),
        ),
        forbidden_success_shortcuts=_FORBIDDEN_SHORTCUTS,
    ),
    "l10c_finalization_integrity": VerificationProfile(
        schema_version=VERIFICATION_PROFILE_SCHEMA,
        profile_id="l10c_finalization_integrity",
        risk_class="high",
        protected_contracts=(
            "l10c_single_finalization_owner",
            "obsidian_before_manifest_freeze",
            "emit_loop_memory_requires_finalized_manifest",
        ),
        required_validation=(
            _pytest_step(
                "meta_contract",
                "tests/test_meta_rlr_contracts.py",
                "tests/test_meta_rlr_observer.py",
                "-q",
            ),
            _pytest_step(
                "l10c_contract_regression",
                "-q",
                "-k",
                "aggregate_report or loop_memory or obsidian or round_manifest",
            ),
            _pytest_step("full_regression", "-q"),
        ),
        forbidden_success_shortcuts=_FORBIDDEN_SHORTCUTS,
    ),
}


def get_profile(profile_id: str) -> VerificationProfile:
    try:
        return _PROFILES[profile_id]
    except KeyError as exc:
        raise KeyError(f"unknown verification profile: {profile_id}") from exc


def all_profiles() -> tuple[VerificationProfile, ...]:
    return tuple(_PROFILES[key] for key in sorted(_PROFILES))


def profile_for_event(event: Mapping[str, Any]) -> VerificationProfile:
    """Route one validated event through the profile-owned contract catalog.

    ``protected_contracts`` is the sole contract-to-profile registry.  Invalid,
    unowned, or ambiguously owned events fail closed before verification work.
    """
    normalized = validate_maintenance_event(event)
    contract = normalized["expected_contract"]
    matches = [
        profile
        for profile in all_profiles()
        if contract in profile.protected_contracts
    ]
    if len(matches) != 1:
        raise KeyError(
            f"expected contract {contract!r} maps to {len(matches)} verification profiles"
        )
    return matches[0]
