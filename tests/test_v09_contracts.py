"""Focused v0.9 contract tests.

These tests protect the new native profile boundary without reinterpreting
existing v2.1 projects or their body-only persona templates.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research_loop.compatibility import (
    CompatibilityError,
    DEFAULT_NATIVE_PROFILE,
    PROFILE_V20,
    PROFILE_V21,
    PROFILE_V21_CATALOG_1,
    get_profile,
    profile_for_schema,
    profiles_for_schema,
)
from research_loop.delta import artifact_for_node
from research_loop.persona_catalog import PersonaCatalogError, resolve_persona_template
from research_loop.providers.base import RunReceipt
from research_loop.topology import topology_for_profile


def test_native_default_is_new_catalog_profile_without_reinterpreting_v21():
    assert DEFAULT_NATIVE_PROFILE == PROFILE_V21_CATALOG_1
    assert get_profile(PROFILE_V21).persona_catalog_version == "body-only-1"
    assert get_profile(PROFILE_V21_CATALOG_1).persona_catalog_version == "persona-catalog-1"
    assert get_profile(PROFILE_V21_CATALOG_1).artifact_naming_version == "native-l8-tukey-1"


def test_schema_only_resolution_is_rejected_when_v21_profiles_are_ambiguous():
    assert profile_for_schema("2.0").profile_id == PROFILE_V20
    assert profiles_for_schema("2.1") == (
        get_profile(PROFILE_V21), get_profile(PROFILE_V21_CATALOG_1),
    )
    with pytest.raises(CompatibilityError, match="ambiguous"):
        profile_for_schema("2.1")
    assert profile_for_schema("2.1", profile_id=PROFILE_V21_CATALOG_1).profile_id == PROFILE_V21_CATALOG_1


def test_artifact_resolver_keeps_existing_v21_key_and_new_profile_uses_tukey():
    legacy_v21 = artifact_for_node(get_profile(PROFILE_V21), "L8")
    catalog_v21 = artifact_for_node(get_profile(PROFILE_V21_CATALOG_1), "L8")
    assert (legacy_v21.storage_key, legacy_v21.display_persona) == ("L8_curie", "Tukey")
    assert (catalog_v21.storage_key, catalog_v21.display_persona) == ("L8_tukey", "Tukey")
    _, catalog_nodes, catalog_sequence = topology_for_profile(PROFILE_V21_CATALOG_1)
    assert catalog_nodes["L9b"]["context_inputs"][-1] == "L9a"
    assert catalog_sequence[catalog_sequence.index("L9a") + 1] == "L9b"


def test_catalog_resolution_hashes_body_only_and_rejects_unknown_persona():
    resolved = resolve_persona_template(get_profile(PROFILE_V21_CATALOG_1), "Tukey")
    assert resolved.catalog_version == "persona-catalog-1"
    assert resolved.markdown_body.startswith("# Tukey")
    assert resolved.catalog_sha256 and resolved.entry_sha256 and resolved.template_sha256
    with pytest.raises(PersonaCatalogError, match="unknown persona"):
        resolve_persona_template(get_profile(PROFILE_V21_CATALOG_1), "Unknown")


def test_run_receipt_is_serializable_and_validates_required_identity(tmp_path: Path):
    receipt = RunReceipt(
        node="L8", persona="Tukey", provider="manual", timestamp="2026-07-30T00:00:00Z",
        context_hash="a" * 64, project_id="P1", candidate_id="C1", round_id="1", profile_id=PROFILE_V21_CATALOG_1,
        context_manifest_path="manifest.json", context_manifest_hash="b" * 64,
        rendered_context_path="context.txt", rendered_context_hash="a" * 64,
        prompt_file="prompt.txt", prompt_hash="c" * 64,
        provider_delta_path="delta.json", provider_delta_hash="d" * 64,
    )
    path = tmp_path / "receipt.json"
    receipt.write(path)
    loaded = RunReceipt.read(path)
    assert loaded.candidate_id == "C1"
    with pytest.raises(ValueError, match="candidate_id"):
        RunReceipt(node="L8", persona="Tukey", provider="p", timestamp="t", context_hash="a" * 64,
                   project_id="P1").validate()
