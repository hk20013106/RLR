"""Test-only migration adapter for native v2.1 L1 Curie authority."""
from __future__ import annotations

import json
from pathlib import Path

from research_loop import l05_curie, research_seed


def install(native_helpers) -> None:
    """Wrap native provider fixtures so L1 owns a real native Curie binding."""
    if getattr(native_helpers, "_native_curie_support_installed", False):
        return
    original = native_helpers.write_native_emission_receipts

    def write_native_emission_receipts(
        project_dir,
        candidate_id,
        node,
        persona,
        source_file,
        *,
        store_path=None,
        **kwargs,
    ):
        manifest_path, receipt_path = original(
            project_dir,
            candidate_id,
            node,
            persona,
            source_file,
            store_path=store_path,
            **kwargs,
        )
        if node != "L1":
            return manifest_path, receipt_path

        project = Path(project_dir)
        seed = research_seed.load_l1_research_seed(project, candidate_id)
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        run_id = str(
            (manifest.get("pre_research") or {}).get("evidence_run_id") or ""
        )
        if not run_id:
            raise AssertionError("synthetic native L1 fixture has no exact evidence run")

        existing = research_seed.unique_l1_native_evidence_run_id(project, seed)
        if existing is None:
            pack_manifest = l05_curie.freeze_l1_deep_research_run(
                project,
                candidate_id=str(seed["candidate_id"]),
                round_id=str(seed["round_id"]),
                seed_sha256=research_seed.seed_sha256(seed),
                run_id=run_id,
            )
            research_seed.write_l1_native_evidence_binding(
                project, seed, pack_manifest, run_id
            )
        elif str(existing) != run_id:
            raise AssertionError(
                "synthetic native L1 fixture has conflicting evidence runs"
            )
        return manifest_path, receipt_path

    native_helpers.write_native_emission_receipts = write_native_emission_receipts
    native_helpers.write_catalog_emission_receipts = write_native_emission_receipts
    native_helpers._native_curie_support_installed = True
