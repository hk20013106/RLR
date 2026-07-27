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


@dataclass(frozen=True)
class CompatibilityProfile:
    profile_id: str
    delta_schema_version: str
    topology_version: str
    persona_catalog_version: str
    l9_parallel: bool


PROFILES = {
    PROFILE_V20: CompatibilityProfile(PROFILE_V20, "2.0", "2.0", "body-only-1", True),
    # The YAML catalog is intentionally deferred; v2.1 currently retains the
    # body-only renderer while changing only contract and topology behavior.
    PROFILE_V21: CompatibilityProfile(PROFILE_V21, "2.1", "2.1", "body-only-1", False),
}


def get_profile(profile_id: str) -> CompatibilityProfile:
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise CompatibilityError(f"unknown compatibility profile: {profile_id}") from exc


def profile_for_schema(schema_version: str) -> CompatibilityProfile:
    for profile in PROFILES.values():
        if profile.delta_schema_version == schema_version:
            return profile
    raise CompatibilityError(f"unsupported delta schema version: {schema_version}")
