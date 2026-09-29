import hashlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop.compatibility import PROFILE_V21
from research_loop import hypothesis_ledger as ledger_module
from research_loop.hypothesis_ledger import HypothesisLedger, LedgerError


def test_l1_retry_returns_original_receipt_after_clock_advances(tmp_path, monkeypatch):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "ledger.sqlite")
    ledger.bind_project(project, profile_id=PROFILE_V21)
    delta = {
        "schema_version": "2.1",
        "hypotheses": [
            {
                "proposal_key": "p1",
                "statement": "A testable hypothesis",
                "operationalization": "Measure the first outcome.",
                "falsification_criteria": ["The first outcome is absent."],
                "rationale": "Deterministic retry fixture.",
            },
        ],
        "primary_proposal_key": "p1",
        "key_uncertainty": "effect size",
    }
    delta_path = project / "02_Agent_Notes" / "Einstein" / "C1_L1.json"

    first = ledger.commit_delta(
        project_dir=project,
        candidate_id="C1",
        round_id="1",
        node="L1",
        persona="Einstein",
        delta=delta,
        delta_path=delta_path,
    )
    monkeypatch.setattr(
        ledger_module,
        "_now",
        lambda: "2099-01-01T00:00:00+00:00",
    )
    second = ledger.commit_delta(
        project_dir=project,
        candidate_id="C1",
        round_id="1",
        node="L1",
        persona="Einstein",
        delta=delta,
        delta_path=delta_path,
    )

    assert second.receipt == first.receipt
    assert second.receipt["created_at"] != "2099-01-01T00:00:00+00:00"


def test_finalized_emission_retry_keeps_the_original_host_receipt_binding(tmp_path):
    project = tmp_path / "P"
    project.mkdir()
    ledger = HypothesisLedger(tmp_path / "ledger.sqlite")
    ledger.bind_project(project, profile_id=PROFILE_V21)
    delta = {
        "schema_version": "2.1",
        "hypotheses": [{
            "proposal_key": "p1",
            "statement": "A host-bound testable hypothesis",
            "operationalization": "Measure the first outcome.",
            "falsification_criteria": ["The first outcome is absent."],
            "rationale": "Host receipt retry fixture.",
        }],
        "primary_proposal_key": "p1",
        "key_uncertainty": "effect size",
    }
    delta_path = project / "02_Agent_Notes" / "Einstein" / "C1_L1.json"

    def finalize_for(raw_host_receipt):
        receipt_hash = hashlib.sha256(raw_host_receipt).hexdigest()

        def finalize(result):
            return result.delta_hash, receipt_hash, None

        return finalize

    first = ledger.commit_delta(
        project_dir=project,
        candidate_id="C1",
        round_id="1",
        node="L1",
        persona="Einstein",
        delta=delta,
        delta_path=delta_path,
        _finalize_callback=finalize_for(b'{"host_receipt":"original"}\n'),
    )
    retry = ledger.commit_delta(
        project_dir=project,
        candidate_id="C1",
        round_id="1",
        node="L1",
        persona="Einstein",
        delta=delta,
        delta_path=delta_path,
        _finalize_callback=finalize_for(b'{"host_receipt":"original"}\n'),
    )

    assert retry.receipt == first.receipt
    with pytest.raises(LedgerError, match="finalization conflicts with immutable marker"):
        ledger.commit_delta(
            project_dir=project,
            candidate_id="C1",
            round_id="1",
            node="L1",
            persona="Einstein",
            delta=delta,
            delta_path=delta_path,
            _finalize_callback=finalize_for(b'{"host_receipt":"changed"}\n'),
        )
