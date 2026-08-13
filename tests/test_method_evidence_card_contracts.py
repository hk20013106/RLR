import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_loop.hypothesis_contracts import validate_submission


def _candidate(*, execution_required, cards=None, gaps=None):
    return {
        "method_id": "deseq2",
        "component_id": "differential_expression",
        "hypothesis_ids": ["H1"],
        "name": "DESeq2",
        "status": "eligible",
        "purpose": "Estimate differential expression.",
        "applicable_to": ["RNA-seq counts"],
        "implementation_steps": ["fit a negative-binomial model"],
        "assumptions": ["count input"],
        "expected_outputs": ["adjusted probabilities"],
        "strengths": ["auditable implementation"],
        "limitations": ["requires adequate replication"],
        "alternatives": ["edgeR"],
        "method_anchor_ids": [],
        "rejection_reasons": [],
        "missing_source": "",
        "execution_required": execution_required,
        "evidence_card_ids": list(cards or []),
        "evidence_gap_ids": list(gaps or []),
    }


def _delta(candidate):
    return {
        "schema_version": "2.1",
        "deep_research_run_id": "C1_L4_bundle",
        "strategies": [{
            "strategy_id": "S1",
            "hypothesis_ids": ["H1"],
            "name": "Differential-expression analysis",
            "steps": ["fit model"],
        }],
        "method_components": [{
            "component_id": "differential_expression",
            "name": "Differential-expression model",
            "required": True,
            "rationale": "Tests H1.",
        }],
        "method_candidates": [candidate],
    }


def test_execution_required_candidate_requires_evidence_card():
    errors = validate_submission(
        "L4",
        _delta(_candidate(execution_required=True, cards=[], gaps=["GAP1"])),
        schema_version="2.1",
    )

    assert any("evidence_card_ids" in error for error in errors)


def test_execution_required_candidate_accepts_evidence_card():
    errors = validate_submission(
        "L4",
        _delta(_candidate(execution_required=True, cards=["CARD1"])),
        schema_version="2.1",
    )

    assert errors == []


def test_optional_alternative_may_retain_only_evidence_gap():
    errors = validate_submission(
        "L4",
        _delta(_candidate(execution_required=False, cards=[], gaps=["GAP1"])),
        schema_version="2.1",
    )

    assert errors == []


def test_staged_candidate_fields_are_atomic():
    candidate = _candidate(execution_required=False, gaps=["GAP1"])
    candidate.pop("evidence_card_ids")

    errors = validate_submission(
        "L4", _delta(candidate), schema_version="2.1"
    )

    assert any("evidence_card_ids" in error for error in errors)
