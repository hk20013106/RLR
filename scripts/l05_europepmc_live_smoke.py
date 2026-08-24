"""Controlled live smoke for the L0.5 Europe PMC vertical slice.

This is intentionally outside pytest. It exercises the public Europe PMC
search and fullTextXML endpoints against one known OA article, with bounded
retries to distinguish transient transport failures from contract regressions.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from research_loop import l0_contract, research_seed
from research_loop.l05_curie import load_frozen_evidence_pack
from research_loop.l05_curie.europepmc_runtime import run_europepmc_acquisition

QUERY = "EXT_ID:22253597 AND SRC:MED"
EXPECTED_PMID = "22253597"
EXPECTED_PMCID = "PMC3257301"


def _make_project(root: Path) -> tuple[Path, dict]:
    project = root / "project"
    project.mkdir()
    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir()
    source_input = l0_contract.build_source_input(
        input_type="inline",
        description="controlled Europe PMC live smoke",
        fmt="text",
    )
    contract = l0_contract.promote_to_current_schema(
        l0_contract.build_initial_contract(
            "C_EPMC_LIVE",
            "1",
            "How is carbon dioxide sensed by yeast?",
            source_input,
            "Rca1p regulates the carbon dioxide transcriptional response.",
        )
    )
    contract_path, contract_hash = l0_contract.write_contract(
        project, "C_EPMC_LIVE", contract
    )
    (candidate_dir / "C_EPMC_LIVE.md").write_text(
        "---\n"
        "candidate_id: C_EPMC_LIVE\n"
        "title: Controlled Europe PMC live smoke\n"
        "question: non-authoritative duplicate\n"
        "claim: non-authoritative duplicate\n"
        "round_type: initial\n"
        "round_id: 1\n"
        f"schema_version: {contract['schema_version']}\n"
        f"input_contract_path: {contract_path.relative_to(project).as_posix()}\n"
        f"input_contract_hash: {contract_hash}\n"
        "---\n",
        encoding="utf-8",
    )
    return project, research_seed.load_l1_research_seed(project, "C_EPMC_LIVE")


def _run_once(attempt: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="rlr-europepmc-live-") as tmp:
        project, seed = _make_project(Path(tmp))
        result = run_europepmc_acquisition(
            project,
            "C_EPMC_LIVE",
            explicit_queries=[QUERY],
            max_papers=1,
            page_size=5,
            run_id=f"LIVE_{attempt:02d}",
            timeout=30,
        )
        if result["status"] != "FROZEN":
            raise RuntimeError(
                f"live acquisition did not freeze: {json.dumps(result, sort_keys=True)}"
            )
        frozen = load_frozen_evidence_pack(
            project,
            result["evidence_pack"],
            candidate_id="C_EPMC_LIVE",
            round_id="1",
            seed_sha256=research_seed.seed_sha256(seed),
        )
        selected = frozen["selected_papers"]
        if len(selected) != 1:
            raise RuntimeError(f"expected one selected paper, got {len(selected)}")
        identifiers = selected[0]["identifiers"]
        if identifiers.get("pmid") != EXPECTED_PMID:
            raise RuntimeError(f"unexpected PMID: {identifiers.get('pmid')}")
        if identifiers.get("pmcid") != EXPECTED_PMCID:
            raise RuntimeError(f"unexpected PMCID: {identifiers.get('pmcid')}")
        if not frozen["evidence"]:
            raise RuntimeError("frozen live EvidencePack contains no verified evidence")
        if not all(item["verification_status"] == "LOCATED" for item in frozen["evidence"]):
            raise RuntimeError("live EvidencePack contains non-LOCATED evidence")
        return {
            "status": result["status"],
            "run_id": result["run_id"],
            "paper_id": selected[0]["paper_id"],
            "pmid": identifiers["pmid"],
            "pmcid": identifiers["pmcid"],
            "verified_evidence_count": len(frozen["evidence"]),
            "coverage": result["coverage"],
        }


def main() -> int:
    errors: list[str] = []
    for attempt in range(1, 4):
        try:
            summary = _run_once(attempt)
        except Exception as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            if attempt < 3:
                time.sleep(2 * attempt)
            continue
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    raise SystemExit("Europe PMC live smoke failed after 3 attempts:\n" + "\n".join(errors))


if __name__ == "__main__":
    raise SystemExit(main())
