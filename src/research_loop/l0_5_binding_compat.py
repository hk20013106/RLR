"""Compatibility bridge from legacy L1 binding lookup to canonical L0.5 binding.

New native runs are owned by research_evidence_binding. Historical L1 evidence
bindings remain readable through the original research_seed API.
"""
from __future__ import annotations


def install(research_seed_module, research_evidence_binding_module) -> None:
    rs = research_seed_module
    reb = research_evidence_binding_module
    if getattr(rs, "_L0_5_BINDING_COMPAT_INSTALLED", False):
        return
    original_manifest_entry = rs.evidence_binding_manifest_entry

    def evidence_binding_manifest_entry(project_dir, seed, run_id):
        path = reb.binding_path(project_dir, seed)
        if path.is_file():
            try:
                entry = reb.manifest_entry(project_dir, seed)
            except reb.ResearchEvidenceBindingError as exc:
                raise rs.ResearchSeedError(str(exc)) from exc
            if str(entry.get("evidence_run_id") or "") == str(run_id):
                return entry
        return original_manifest_entry(project_dir, seed, run_id)

    rs.evidence_binding_manifest_entry = evidence_binding_manifest_entry
    rs._L0_5_BINDING_COMPAT_INSTALLED = True
