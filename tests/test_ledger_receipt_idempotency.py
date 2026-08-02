import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop.compatibility import PROFILE_V21
from research_loop import hypothesis_ledger as ledger_module
from research_loop.hypothesis_ledger import HypothesisLedger


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
