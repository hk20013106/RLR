"""Compatibility aliases for the canonical ResearchSeed evidence binding.

The implementation lives in :mod:`research_loop.research_seed`. This module is
kept temporarily so older imports resolve while PR #38 migrates call sites; it
contains no independent persistence or validation logic.
"""
from __future__ import annotations

from research_loop import research_seed


SCHEMA_VERSION = research_seed.RESEARCH_EVIDENCE_BINDING_SCHEMA_VERSION
TARGET_NODE = research_seed.DEFAULT_RESEARCH_TARGET
ResearchEvidenceBindingError = research_seed.ResearchSeedError


def binding_path(project_dir, seed):
    return research_seed.research_evidence_binding_path(
        project_dir, seed, TARGET_NODE
    )


def write_binding(project_dir, seed, run_id):
    return research_seed.write_research_evidence_binding(
        project_dir, seed, run_id, TARGET_NODE
    )


def load_binding(project_dir, seed):
    return research_seed.load_research_evidence_binding(
        project_dir, seed, TARGET_NODE
    )


def manifest_entry(project_dir, seed):
    return research_seed.research_evidence_binding_manifest_entry(
        project_dir, seed, TARGET_NODE
    )


def run_id_for_seed(project_dir, seed):
    return research_seed.research_evidence_run_id(project_dir, seed, TARGET_NODE)


def binding_state(project_dir, seed):
    return research_seed.research_evidence_binding_state(
        project_dir, seed, TARGET_NODE
    )
