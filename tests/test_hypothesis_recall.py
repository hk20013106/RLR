import json

import pytest

from research_loop.hypothesis_ledger import LedgerError
from research_loop.hypothesis_recall import (
    create_recall,
    load_recall,
    recall_path,
    validate_recall,
)
from tests.test_hypothesis_pool import _seed_rejected_hypothesis


def test_recall_returns_rejected_history_and_records_scores(tmp_path):
    project, ledger, rejected_id = _seed_rejected_hypothesis(tmp_path)

    artifact = create_recall(
        ledger,
        project,
        "C2",
        "2",
        query_text="declining extracellular matrix expression",
        limit=10,
    )

    assert artifact["schema_version"] == "HypothesisRecall/v1"
    assert artifact["results"][0]["hypothesis_id"] == rejected_id
    assert artifact["results"][0]["reactivation_eligibility"] == "ELIGIBLE_WITH_BASIS"
    assert artifact["results"][0]["scores"]["keyword"] > 0
    assert artifact["artifact_hash"]
    assert recall_path(project, "C2", "2").is_file()
    assert load_recall(project, "C2", "2") == artifact
    validate_recall(
        ledger,
        project,
        artifact,
        expected_candidate_id="C2",
        expected_round_id="2",
    )


def test_recall_zero_result_is_valid(tmp_path):
    project, ledger, _rejected_id = _seed_rejected_hypothesis(tmp_path)

    artifact = create_recall(
        ledger,
        project,
        "C3",
        "3",
        query_text="completely unrelated mars geology",
        limit=10,
    )

    assert artifact["results"] == []
    validate_recall(
        ledger,
        project,
        artifact,
        expected_candidate_id="C3",
        expected_round_id="3",
    )


def test_recall_detects_tampering(tmp_path):
    project, ledger, _rejected_id = _seed_rejected_hypothesis(tmp_path)
    artifact = create_recall(
        ledger,
        project,
        "C4",
        "4",
        query_text="extracellular matrix",
        limit=10,
    )
    path = recall_path(project, "C4", "4")
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["query"]["text"] = "changed"
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(LedgerError, match="hash mismatch"):
        load_recall(project, "C4", "4")
