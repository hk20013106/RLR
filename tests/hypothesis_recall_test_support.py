"""Test-only adapter that binds synthetic L1 receipts to recall artifacts."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

from research_loop import research_seed
from research_loop.hypothesis_ledger import HypothesisLedger
from research_loop.hypothesis_recall import create_recall, recall_manifest_entry
from research_loop.providers.base import RunReceipt


def install(native_helpers) -> None:
    if getattr(native_helpers, "_hypothesis_recall_support_installed", False):
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
        include_recall=True,
    ):
        manifest_path, receipt_path = original(
            project_dir,
            candidate_id,
            node,
            persona,
            source_file,
            store_path=store_path,
        )
        project = Path(project_dir)
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

        # The synthetic helper creates the immutable evidence pack directly.
        # Context assembly also requires its canonical pre-research alias.
        evidence = (manifest.get("pre_research") or {}).get("evidence_artifacts")
        if evidence:
            summary = next(
                (
                    item for item in evidence.get("files", [])
                    if item.get("kind") == "summary"
                ),
                None,
            )
            if summary:
                source_summary = project / str(summary["path"])
                canonical_summary = (
                    project / "02_Agent_Notes" / "_pre_research"
                    / f"{node}_research.md"
                )
                canonical_summary.parent.mkdir(parents=True, exist_ok=True)
                canonical_summary.write_bytes(source_summary.read_bytes())

        if node != "L1" or not include_recall:
            return manifest_path, receipt_path

        ledger = HypothesisLedger(
            store_path or os.environ["RLR_HYPOTHESIS_STORE"]
        )
        seed = research_seed.load_l1_research_seed(project, candidate_id)
        round_id = str(seed["round_id"])
        query_text = " ".join((
            str(seed["scientific_question"]),
            str(seed["hypothesis_seed"]),
        )).strip()
        create_recall(
            ledger,
            project,
            candidate_id,
            round_id,
            query_text=query_text,
        )

        manifest["hypothesis_recall"] = recall_manifest_entry(
            project, candidate_id, round_id
        )
        Path(manifest_path).write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )
        receipt = RunReceipt.read(receipt_path)
        replace(
            receipt,
            context_manifest_hash=hashlib.sha256(
                Path(manifest_path).read_bytes()
            ).hexdigest(),
        ).write(receipt_path)
        return manifest_path, receipt_path

    native_helpers.write_native_emission_receipts = write_native_emission_receipts
    native_helpers.write_catalog_emission_receipts = write_native_emission_receipts
    native_helpers._hypothesis_recall_support_installed = True