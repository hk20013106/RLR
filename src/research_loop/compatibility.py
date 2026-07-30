"""Immutable compatibility profiles for ledger-backed projects.

Profiles are deliberately small: they select persisted contract/topology
semantics without granting a persona or a caller any additional authority.
"""
from __future__ import annotations

from dataclasses import dataclass


class CompatibilityError(ValueError):
    """Raised when an artifact cannot be interpreted by a declared profile."""


PROFILE_V20 = "v2.0-legacy"
PROFILE_V21 = "v2.1"
PROFILE_V21_CATALOG_1 = "v2.1-catalog-1"
# New projects bind this profile explicitly in their ledger.  Existing v2.1
# projects retain their original profile, templates, and artifact names.
DEFAULT_NATIVE_PROFILE = PROFILE_V21_CATALOG_1


@dataclass(frozen=True)
class CompatibilityProfile:
    profile_id: str
    delta_schema_version: str
    topology_version: str
    persona_catalog_version: str
    artifact_naming_version: str
    l9_parallel: bool


PROFILES = {
    PROFILE_V20: CompatibilityProfile(PROFILE_V20, "2.0", "2.0", "body-only-1", "legacy-l8-curie-1", True),
    # The YAML catalog is intentionally deferred; v2.1 currently retains the
    # body-only renderer while changing only contract and topology behavior.
    PROFILE_V21: CompatibilityProfile(PROFILE_V21, "2.1", "2.1", "body-only-1", "legacy-l8-curie-1", False),
    PROFILE_V21_CATALOG_1: CompatibilityProfile(
        PROFILE_V21_CATALOG_1, "2.1", "2.1", "persona-catalog-1",
        "native-l8-tukey-1", False,
    ),
}


def get_profile(profile_id: str) -> CompatibilityProfile:
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise CompatibilityError(f"unknown compatibility profile: {profile_id}") from exc


def profiles_for_schema(schema_version: str) -> tuple[CompatibilityProfile, ...]:
    """Return every profile that can read a schema, in stable declaration order."""
    matches = tuple(p for p in PROFILES.values() if p.delta_schema_version == schema_version)
    if not matches:
        raise CompatibilityError(f"unsupported delta schema version: {schema_version}")
    return matches


def profile_for_schema(schema_version: str, *, profile_id: str | None = None) -> CompatibilityProfile:
    """Resolve a schema only when it maps unambiguously or a binding is supplied."""
    matches = profiles_for_schema(schema_version)
    if profile_id is not None:
        profile = get_profile(profile_id)
        if profile.delta_schema_version != schema_version:
            raise CompatibilityError(
                f"profile {profile_id} does not use delta schema {schema_version}"
            )
        return profile
    if len(matches) != 1:
        names = ", ".join(p.profile_id for p in matches)
        raise CompatibilityError(
            f"schema version {schema_version} is ambiguous across profiles: {names}; "
            "use the project profile binding"
        )
    return matches[0]
