"""Native L4 contract closure: provider guarantees satisfy binder preconditions.

Regression matrix for the real Fisher incident (cold-start-e2e-20260923):
a provider-valid payload omitted execution_required / evidence_card_handles /
evidence_gap_handles and died in the L4C binder. The v2.1-catalog-1 provider
projection now requires those fields, so structurally incomplete payloads fail
at validate_provider_submission() before the binder ever runs.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from research_loop import deep_research as dr
from research_loop import l4_closed_corpus as cc
from research_loop import l4_evidence_bundle as bundle
from research_loop.compatibility import (
    PROFILE_V21,
    PROFILE_V21_CATALOG_1,
)
from research_loop.hypothesis_contracts import (
    SCHEMA_REGISTRY,
    provider_schema_for_profile,
    validate_provider_submission,
    validate_submission,
)
from research_loop.method_contracts import validate_input_requirements
from research_loop.pre_e2e_closure import (
    _native_l4_producer_consumer_closure,
    audit_static_closure,
)
from research_loop.providers.base import _compose_auto_prompt

HERE = Path(__file__).resolve().parent
FIXTURE_DIR = HERE / "fixtures" / "native_l4_fisher_regression"
FISHER_DELTA = FIXTURE_DIR / "L4_Fisher_delta.json"
FISHER_SHA256 = "4dbc8faadac4c2e42ab27aba021b7587db294f6e732c27ea37ad22d365347521"

NATIVE = PROFILE_V21_CATALOG_1


def _live_candidate_required():
    schema = provider_schema_for_profile(NATIVE, "L4", "2.1")
    return list(
        schema["properties"]["method_candidates"]["items"]["required"]
    )


def _valid_candidate(**overrides):
    """Minimal scientifically-blocked candidate carrying every required field."""
    candidate = {
        "method_id": "M1",
        "component_id": "MC1",
        "hypothesis_ids": ["H1"],
        "name": "diagnostic",
        "status": "needs_user_source",
        "purpose": "test",
        "applicable_to": ["sample metadata"],
        "implementation_steps": ["inspect design matrix"],
        "assumptions": [],
        "expected_outputs": ["diagnostic report"],
        "strengths": [],
        "limitations": [],
        "alternatives": [],
        "method_anchor_handles": [],
        "rejection_reasons": [],
        "missing_source": "exact method evidence",
        "required_inputs": ["sample metadata"],
        "optional_diagnostics": [],
        "missing_inputs": [],
        "execution_required": False,
        "evidence_card_handles": [],
        "evidence_gap_handles": [],
    }
    candidate.update(overrides)
    return candidate


def _valid_delta(candidate):
    return {
        "schema_version": "2.1",
        "candidate_id": "C1",
        "deep_research_run_id": "RUN1",
        "strategies": [{
            "strategy_id": "S1",
            "hypothesis_ids": ["H1"],
            "name": "strategy",
            "steps": ["run"],
        }],
        "method_components": [{
            "component_id": "MC1",
            "name": "diagnostic",
            "required": True,
            "rationale": "required",
        }],
        "method_candidates": [candidate],
    }


def _evidence_artifact():
    return {
        "run_id": "RUN1",
        "evidence_cards": [{
            "evidence_card_id": "CARD1",
            "method_id": "M1",
            "anchor_id": "ANCHOR1",
            "status": "accepted",
        }],
        "evidence_gaps": [],
    }


def _provider_errors(delta):
    return validate_provider_submission(
        "L4", delta, schema_version="2.1", profile_id=NATIVE
    )


# --- 8.1 provider-schema omission failures (before binder) --------------------


@pytest.mark.parametrize("field", [
    "execution_required",
    "evidence_card_handles",
    "evidence_gap_handles",
])
def test_omitted_staged_field_fails_at_provider_validation(field):
    candidate = _valid_candidate()
    del candidate[field]
    errors = _provider_errors(_valid_delta(candidate))
    assert errors, f"omitted {field} must fail provider validation"
    assert any(field in error for error in errors)


@pytest.mark.parametrize("field", [
    "deep_research_run_id",
    "method_components",
    "method_candidates",
])
def test_omitted_top_level_field_fails_at_provider_validation(field):
    delta = _valid_delta(_valid_candidate())
    del delta[field]
    errors = _provider_errors(delta)
    assert errors, f"omitted {field} must fail provider validation"
    assert any(field in error for error in errors)


# --- 8.2 missing / null / empty semantics -------------------------------------


@pytest.mark.parametrize("field", [
    "execution_required",
    "evidence_card_handles",
    "evidence_gap_handles",
])
def test_null_staged_field_fails_at_provider_validation(field):
    candidate = _valid_candidate(**{field: None})
    errors = _provider_errors(_valid_delta(candidate))
    assert errors, f"null {field} must fail provider validation"


def test_explicit_empty_handles_are_structurally_valid_where_allowed():
    assert _provider_errors(_valid_delta(_valid_candidate())) == []


# --- 8.3 legitimate blocked candidate remains expressible ---------------------


def test_legitimate_blocked_candidate_passes_provider_schema():
    candidate = _valid_candidate(
        status="needs_user_source",
        execution_required=False,
        evidence_card_handles=[],
        evidence_gap_handles=[],
        missing_source="exact method evidence PDF is not in context",
    )
    assert _provider_errors(_valid_delta(candidate)) == []


# --- 8.4 needs_user_data alignment --------------------------------------------


def test_needs_user_data_passes_provider_and_input_validation():
    candidate = _valid_candidate(
        status="needs_user_data",
        missing_inputs=["transcript-level abundance data"],
        missing_source="",
    )
    assert _provider_errors(_valid_delta(candidate)) == []
    validate_input_requirements(candidate)


# --- 8.5 historical canonical compatibility -----------------------------------


def _historical_canonical_delta():
    candidate = {
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
        "method_anchor_ids": ["ANCHOR1"],
        "rejection_reasons": [],
        "missing_source": "",
    }
    return {
        "schema_version": "2.1",
        "deep_research_run_id": "RUN0",
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


def test_historical_canonical_delta_without_staged_fields_remains_valid():
    assert validate_submission(
        "L4", _historical_canonical_delta(), schema_version="2.1"
    ) == []
    # Profiles without a provider projection retain the canonical wire shape.
    assert validate_provider_submission(
        "L4", _historical_canonical_delta(),
        schema_version="2.1", profile_id=PROFILE_V21,
    ) == []


# --- 8.6 real-provider regression ---------------------------------------------


def _load_fisher_fixture():
    raw = FISHER_DELTA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FISHER_SHA256
    return json.loads(raw.decode("utf-8"))


def test_real_fisher_payload_fails_at_provider_before_binder():
    delta = _load_fisher_fixture()
    errors = _provider_errors(delta)
    assert errors, "exact failing Fisher payload must now fail provider validation"
    joined = " ".join(errors)
    for field in (
        "execution_required",
        "evidence_card_handles",
        "evidence_gap_handles",
    ):
        assert field in joined
    assert any("required property" in error for error in errors)


def test_real_fisher_payload_reproduces_binder_failure_mode():
    delta = _load_fisher_fixture()
    with pytest.raises(dr.DeepResearchError, match="evidence_card_handles"):
        bundle.resolve_l4c_reference_handles(_evidence_artifact(), delta)


# --- 8.7 unknown handle stays a binder responsibility --------------------------


def test_unknown_handle_passes_provider_but_fails_binder():
    candidate = _valid_candidate(
        status="eligible",
        execution_required=True,
        evidence_card_handles=["E999"],
        method_anchor_handles=[],
    )
    assert _provider_errors(_valid_delta(candidate)) == []
    with pytest.raises(dr.DeepResearchError, match="[Uu]nknown"):
        bundle.resolve_l4c_reference_handles(
            _evidence_artifact(), _valid_delta(candidate)
        )


def test_known_handles_bind_deterministically():
    candidate = _valid_candidate(
        status="eligible",
        execution_required=True,
        evidence_card_handles=["E1"],
        method_anchor_handles=["A1"],
    )
    assert _provider_errors(_valid_delta(candidate)) == []
    resolved, binding = bundle.resolve_l4c_reference_handles(
        _evidence_artifact(), _valid_delta(candidate)
    )
    bound = resolved["method_candidates"][0]
    assert bound["evidence_card_ids"] == ["CARD1"]
    assert bound["method_anchor_ids"] == ["ANCHOR1"]
    assert "evidence_card_handles" not in bound


# --- 8.8 / 8.9 closure sensitivity (isolated copies only) ----------------------


def _live_provider_l4():
    return provider_schema_for_profile(NATIVE, "L4", "2.1")


def test_static_closure_is_closed_for_native_profile():
    report = _native_l4_producer_consumer_closure()
    assert report["overall"] == "CLOSED"
    assert report["checks"]["binder_required_subset_of_provider"] is True
    assert report["checks"]["consumer_status_subset_of_provider"] is True


def test_closure_detects_requiredness_drift_on_isolated_copy():
    live = _live_provider_l4()
    before = json.dumps(live, sort_keys=True)
    mutated = copy.deepcopy(live)
    mutated["properties"]["method_candidates"]["items"]["required"].remove(
        "evidence_card_handles"
    )
    report = _native_l4_producer_consumer_closure(mutated)
    assert report["overall"] == "CONTRACT_MISMATCH"
    assert report["checks"]["binder_required_subset_of_provider"] is False
    assert json.dumps(live, sort_keys=True) == before


def test_closure_detects_enum_drift_on_isolated_copy():
    live = _live_provider_l4()
    before = json.dumps(live, sort_keys=True)
    mutated = copy.deepcopy(live)
    mutated["properties"]["method_candidates"]["items"]["properties"]["status"]["enum"].remove(
        "needs_user_data"
    )
    report = _native_l4_producer_consumer_closure(mutated)
    assert report["overall"] == "CONTRACT_MISMATCH"
    assert report["checks"]["no_dangling_status_rules"] is False
    assert json.dumps(live, sort_keys=True) == before


def test_full_static_audit_remains_closed_for_native_profile():
    report = audit_static_closure(NATIVE)
    assert report["e2e_start_allowed"] is True
    assert report["l4_producer_consumer"]["overall"] == "CLOSED"


# --- 8.10 strategies non-regression -------------------------------------------


def test_strategies_contract_unchanged_by_this_repair():
    provider_l4 = _live_provider_l4()
    assert {"schema_version", "strategies"} <= set(provider_l4.get("required", []))
    strategy = provider_l4["properties"]["strategies"]["items"]
    assert strategy["required"] == [
        "strategy_id", "hypothesis_ids", "name", "steps",
    ]
    assert "strategies" in provider_l4["properties"]
    canonical_l4 = SCHEMA_REGISTRY["2.1"]["L4"]
    assert canonical_l4["required"] == ["schema_version", "strategies"]


# --- 9. test-helper discipline -------------------------------------------------


def test_helper_covers_live_provider_required_fields():
    live_required = set(_live_candidate_required())
    assert live_required <= set(_valid_candidate())
    assert {
        "execution_required",
        "evidence_card_handles",
        "evidence_gap_handles",
        "method_anchor_handles",
    } <= live_required


# --- 5. legacy validator isolation locks ---------------------------------------


def _legacy_shaped_payload():
    return {
        "schema_version": "1.0",
        "queries": ["legacy L4"],
        "papers": [{
            "doi": "10.1186/s13059-014-0550-8",
            "title": "Legacy method paper",
            "source_database": "PubMed",
            "source_metadata_response": {"id": "25516281"},
            "extracts": [],
        }],
        "review_search": {
            "status": "not_retained",
            "receipt": "synthetic",
        },
        "method_components": [{
            "component_id": "MC1",
            "name": "diagnostic",
            "required": True,
            "rationale": "required",
        }],
        "method_candidates": [{
            "method_id": "M1",
            "component_id": "MC1",
            "name": "diagnostic",
            "status": "needs_user_data",
            "purpose": "test",
            "applicable_to": ["sample metadata"],
            "implementation_steps": ["inspect"],
            "assumptions": [],
            "expected_outputs": ["report"],
            "strengths": [],
            "limitations": [],
            "alternatives": [],
            "rejection_reasons": [],
            "method_anchor_ids": [],
            "missing_source": "",
        }],
    }


def _receipt():
    return dr.skill_receipt("codex", ["codex", "exec"], "synthetic", "test")


def test_native_profile_bypasses_legacy_semantic_validation(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    artifact = dr.persist_run(
        project, "C1", "L4", _legacy_shaped_payload(), _receipt(),
        project_id="P1", round_id="1", profile_id=NATIVE,
    )
    assert artifact["node"] == "L4"
    assert artifact["method_candidates"][0]["status"] == "needs_user_data"


def test_historical_profile_keeps_legacy_semantic_validation(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(dr.DeepResearchError, match="status is invalid"):
        dr.persist_run(
            project, "C1", "L4", _legacy_shaped_payload(), _receipt(),
            project_id="P1", round_id="1", profile_id=PROFILE_V21,
        )


# --- 6. closed-corpus scope lock ------------------------------------------------


def test_enrich_leaves_stage_bound_l4c_delta_untouched():
    payload = _valid_delta(_valid_candidate())
    payload["papers"] = []
    snapshot = copy.deepcopy(payload)
    state = {
        "contracts": [],
        "resolutions": [{
            "status": "resolved",
            "contract": {"paper_id": "A1"},
            "source_payload": "x" * 600,
            "content_type": "text/plain",
            "open_access": True,
            "methods_section": {
                "section": "Methods",
                "text": "y" * 600,
                "locator": "Methods 1",
                "parser": "test",
            },
        }],
    }
    cc.enrich_provider_payload(payload, state)
    assert payload == snapshot


# --- Addendum E: dynamic schema delivery ---------------------------------------


def test_native_fisher_prompt_receives_live_provider_schema():
    schema = provider_schema_for_profile(NATIVE, "L4", "2.1")
    prompt = _compose_auto_prompt(
        "L4", "Fisher", "context", output_schema=schema
    )
    assert "# JSON delta schema:" in prompt
    assert '"evidence_card_handles"' in prompt
    assert '"needs_user_data"' in prompt
    assert '"execution_required"' in prompt


def test_l4_template_covers_all_provider_statuses():
    template = (
        HERE.parent / "templates" / "layers" / "L4_method_brainstorm.md"
    ).read_text(encoding="utf-8")
    provider_enum = provider_schema_for_profile(
        NATIVE, "L4", "2.1"
    )["properties"]["method_candidates"]["items"]["properties"]["status"]["enum"]
    for status in provider_enum:
        assert status in template, f"template omits provider status {status}"
