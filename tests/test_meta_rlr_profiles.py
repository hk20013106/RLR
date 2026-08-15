import pytest

from rlr_maintenance.contracts import MaintenanceContractError, build_maintenance_event
from rlr_maintenance.profiles import (
    VERIFICATION_PROFILE_SCHEMA,
    all_profiles,
    get_profile,
    profile_for_event,
)


def test_l0_profile_protects_durable_architecture_not_historical_incident():
    profile = get_profile("l0_state_integrity")

    assert profile.schema_version == VERIFICATION_PROFILE_SCHEMA
    assert "l0_restore_fail_closed" in profile.protected_contracts
    assert "provider_after_restore_only" in profile.protected_contracts
    assert "round_manifest_hash_integrity" in profile.protected_contracts
    assert all("PR15" not in item for item in profile.protected_contracts)
    assert {
        "weaken_validator",
        "convert_fail_to_warn",
        "rewrite_expected_hash",
        "skip_required_test",
        "parallel_state_owner",
    } <= set(profile.forbidden_success_shortcuts)


def test_profiles_use_argv_not_shell_commands_and_include_full_regression():
    for profile in all_profiles():
        assert profile.required_validation
        assert any(step.step_id == "full_regression" for step in profile.required_validation)
        for step in profile.required_validation:
            assert isinstance(step.command, tuple)
            assert step.command
            assert all(isinstance(token, str) and token for token in step.command)
            assert not any(token in {"&&", "||", ";"} for token in step.command)


def test_protected_contract_ownership_is_globally_unique():
    owners = {}
    duplicates = []
    for profile in all_profiles():
        for contract in profile.protected_contracts:
            if contract in owners:
                duplicates.append((contract, owners[contract], profile.profile_id))
            owners[contract] = profile.profile_id

    assert duplicates == []


def test_unknown_profile_fails_closed():
    with pytest.raises(KeyError, match="unknown verification profile"):
        get_profile("does-not-exist")


def test_l4_and_l10c_profiles_are_separate_contract_families():
    l4 = get_profile("l4_frozen_corpus_integrity")
    l10c = get_profile("l10c_finalization_integrity")

    assert "l4b_frozen_corpus_only" in l4.protected_contracts
    assert "l10c_single_finalization_owner" not in l4.protected_contracts
    assert "l10c_single_finalization_owner" in l10c.protected_contracts
    assert "l4b_frozen_corpus_only" not in l10c.protected_contracts


def _event(expected_contract="runner_nonzero_propagation"):
    return build_maintenance_event(
        event_type="runtime_failure",
        component="root_entrypoint",
        severity="blocking",
        observed_at="2026-08-13T00:00:00Z",
        rlr_revision="a" * 40,
        observed={"command": ["python", "run_loop.py"], "exit_code": 0},
        expected_contract=expected_contract,
    )


def test_profile_routing_requires_a_valid_maintenance_event():
    event = _event()
    assert profile_for_event(event).profile_id == "l0_state_integrity"

    with pytest.raises(MaintenanceContractError):
        profile_for_event({"expected_contract": "runner_nonzero_propagation"})


def test_provider_runtime_profile_owns_only_execution_integrity():
    profile = get_profile("provider_runtime_integrity")

    assert profile.protected_contracts == ("provider_runtime_execution_integrity",)
    assert profile_for_event(
        _event("provider_runtime_execution_integrity")
    ).profile_id == "provider_runtime_integrity"
    assert any(step.step_id == "provider_runtime_regression" for step in profile.required_validation)


def test_unowned_expected_contract_fails_closed_without_second_registry():
    with pytest.raises(KeyError, match="maps to 0 verification profiles"):
        profile_for_event(_event("unowned_contract"))
