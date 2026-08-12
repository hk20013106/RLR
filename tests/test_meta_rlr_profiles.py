import pytest

from rlr_maintenance.profiles import (
    VERIFICATION_PROFILE_SCHEMA,
    all_profiles,
    get_profile,
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
