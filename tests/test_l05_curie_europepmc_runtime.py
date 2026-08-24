import hashlib
import json
from pathlib import Path

from research_loop import l0_contract, research_seed
from research_loop.l05_curie import load_frozen_evidence_pack
from research_loop.l05_curie.europepmc_runtime import run_europepmc_acquisition
from research_loop import cli


XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<article><body>
<sec><title>Results</title><p>Rca1p was required for the transcriptional response to carbon dioxide.</p></sec>
<sec><title>Discussion</title><p>These results identify Rca1p as a central regulator of carbon dioxide sensing.</p></sec>
<sec><title>Conclusion</title><p>Rca1p links carbon dioxide exposure to downstream transcriptional regulation.</p></sec>
</body></article>'''


def _project(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    candidate_dir = project / "01_Candidates"
    candidate_dir.mkdir()
    source_input = l0_contract.build_source_input(
        input_type="inline",
        description="synthetic Europe PMC runtime fixture",
        fmt="text",
    )
    contract = l0_contract.promote_to_current_schema(
        l0_contract.build_initial_contract(
            "C001",
            "1",
            "How is carbon dioxide sensed by yeast?",
            source_input,
            "Rca1p regulates the carbon dioxide transcriptional response.",
        )
    )
    contract_path, contract_hash = l0_contract.write_contract(project, "C001", contract)
    (candidate_dir / "C001.md").write_text(
        "---\n"
        "candidate_id: C001\n"
        "title: Europe PMC runtime fixture\n"
        "question: duplicated frontmatter question is not authoritative\n"
        "claim: duplicated frontmatter claim is not authoritative\n"
        "round_type: initial\n"
        "round_id: 1\n"
        f"schema_version: {contract['schema_version']}\n"
        f"input_contract_path: {contract_path.relative_to(project).as_posix()}\n"
        f"input_contract_hash: {contract_hash}\n"
        "---\n",
        encoding="utf-8",
    )
    return project, research_seed.load_l1_research_seed(project, "C001")


def _search_payload(*, open_access=True):
    result = {
        "id": "22253597",
        "source": "MED",
        "pmid": "22253597",
        "pmcid": "PMC3257301" if open_access else "",
        "doi": "10.1371/journal.ppat.1002485",
        "title": "The bZIP Transcription Factor Rca1p Is a Central Regulator of a Novel CO2 Sensing Pathway in Yeast",
        "authorString": "Cottier F, et al.",
        "pubYear": "2012",
        "journalTitle": "PLoS Pathog",
        "isOpenAccess": "Y" if open_access else "N",
        "inEPMC": "Y" if open_access else "N",
        "abstractText": "Rca1p regulates the response to carbon dioxide.",
        "pubTypeList": {"pubType": ["research-article"]},
    }
    return json.dumps(
        {"hitCount": 1, "resultList": {"result": [result]}}, sort_keys=True
    ).encode("utf-8")


def test_runtime_freezes_end_to_end_europepmc_evidence_pack(tmp_path):
    project, seed = _project(tmp_path)
    search = _search_payload()
    calls = []

    def http_get(url, timeout):
        calls.append(url)
        if "/search?" in url:
            return search
        if url.endswith("/PMC3257301/fullTextXML"):
            return XML
        raise AssertionError(url)

    result = run_europepmc_acquisition(
        project,
        "C001",
        explicit_queries=["EXT_ID:22253597 AND SRC:MED"],
        max_papers=1,
        page_size=5,
        run_id="RUN001",
        http_get=http_get,
        timeout=7,
    )

    assert result["status"] == "FROZEN"
    assert result["run_id"] == "RUN001"
    assert result["coverage"]["verdict"] == "PASS"
    assert len(calls) == 2
    assert any("/search?" in url for url in calls)
    assert any(url.endswith("/PMC3257301/fullTextXML") for url in calls)

    manifest = result["evidence_pack"]
    frozen = load_frozen_evidence_pack(
        project,
        manifest,
        candidate_id="C001",
        round_id="1",
        seed_sha256=research_seed.seed_sha256(seed),
    )
    assert frozen["source_run_id"] == "RUN001"
    assert frozen["discovery_receipts"][0]["provider"] == "europe-pmc"
    assert frozen["selected_papers"][0]["identifiers"]["pmcid"] == "PMC3257301"
    assert {item["section"] for item in frozen["evidence"]} == {
        "Results", "Discussion", "Conclusion"
    }
    assert all(item["verification_status"] == "LOCATED" for item in frozen["evidence"])

    audit_path = project / result["acquisition_manifest_path"]
    assert hashlib.sha256(audit_path.read_bytes()).hexdigest() == result["acquisition_manifest_sha256"]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["selection"]["decisions"][0]["decision"] == "INCLUDE"
    assert len(audit["source_snapshots"]) == 1
    assert audit["coverage"]["verdict"] == "PASS"
    assert audit["evidence_pack"]["artifact_sha256"] == manifest["artifact_sha256"]


def test_runtime_does_not_freeze_when_no_oa_full_text_is_available(tmp_path):
    project, _seed = _project(tmp_path)

    result = run_europepmc_acquisition(
        project,
        "C001",
        explicit_queries=["EXT_ID:22253597 AND SRC:MED"],
        max_papers=1,
        run_id="RUN_NO_OA",
        http_get=lambda _url, _timeout: _search_payload(open_access=False),
    )

    assert result["status"] == "INSUFFICIENT_RETRY"
    assert result["evidence_pack"] is None
    assert result["coverage"]["verdict"] == "INSUFFICIENT_RETRY"
    assert result["coverage"]["gaps"][0]["gap_id"] == "NO_VERIFIED_FULL_TEXT"
    assert not list((project / "09_Literature_Database" / "evidence_packs" / "l05").rglob("*.json"))


def test_cli_registers_thin_europepmc_acquisition_command(tmp_path, monkeypatch, capsys):
    project, _seed = _project(tmp_path)
    parser = cli.build_parser()
    args = parser.parse_args([
        "l05-acquire-europepmc",
        str(project),
        "C001",
        "--query", "EXT_ID:22253597 AND SRC:MED",
        "--max-papers", "1",
        "--page-size", "5",
        "--timeout", "7",
        "--run-id", "CLI001",
    ])

    seen = {}

    def fake_run(project_dir, cand_id, **kwargs):
        seen.update({"project_dir": project_dir, "cand_id": cand_id, **kwargs})
        return {"schema_version": "L05EuropePmcAcquisitionResult/v1", "status": "FROZEN"}

    import research_loop.l05_curie_cli as extension
    monkeypatch.setattr(extension, "run_europepmc_acquisition", fake_run)
    assert args.func(args) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["status"] == "FROZEN"
    assert seen["cand_id"] == "C001"
    assert seen["explicit_queries"] == ["EXT_ID:22253597 AND SRC:MED"]
    assert seen["run_id"] == "CLI001"
