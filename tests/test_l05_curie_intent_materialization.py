"""Regressions for scientific cognition before deterministic v2 materialization."""

import copy
import hashlib
import json

import pytest

from research_loop import research_seed
from research_loop.l05_curie import CurieContractError, query_planner


def _seed():
    return {
        "schema_version": "L1ResearchSeed/v1", "candidate_id": "C1", "round_id": "1",
        "scientific_question": "Does carbon dioxide alter yeast sensing?",
        "hypothesis_seed": "Rca1p regulates carbon dioxide sensing.",
    }


def _proposal():
    return {
        "status": "PLAN", "reason": "Test the question and initial mechanism",
        "plan": {
            "core_anchors": [
                {"source_field": "scientific_question", "text_snippet": "carbon dioxide"},
                {"source_field": "hypothesis_seed", "text_snippet": "Rca1p"},
            ],
            "optional_anchors": [
                {"source_field": "scientific_question", "text_snippet": "yeast"},
            ],
            "intents": [{"optional_anchor_indices": [0]}, {"optional_anchor_indices": []}],
        },
    }


def _response(seed, proposal, *, index=0, feedback=None):
    request = query_planner.prepare_scientific_query_plan_request(
        seed, reformulation_index=index, feedback=feedback,
    )
    return query_planner.validate_scientific_query_plan_response(
        seed, request=request, raw_response=json.dumps(proposal).encode(),
    )


def test_minimal_scientific_intent_materializes_valid_compilable_v2():
    seed, proposal = _seed(), _proposal()
    original = copy.deepcopy(proposal)
    result = _response(seed, proposal)
    plan = result["plan"]
    assert plan["schema_version"] == "L05ScientificQueryPlan/v2"
    assert plan["seed_sha256"] == research_seed.seed_sha256(seed)
    assert plan["target_question_sha256"] == hashlib.sha256(seed["scientific_question"].encode()).hexdigest()
    assert (plan["parent_plan_content_hash"], plan["feedback_sha256"], plan["feedback_gap_ids"]) == (None, None, [])
    assert plan["reformulation_index"] == 0
    assert [(a["source_type"], a["start"], a["end"], a["term"]) for a in plan["core_anchors"]] == [
        ("QUESTION", 5, 19, "carbon dioxide"), ("INITIAL_HYPOTHESIS", 0, 5, "rca1p"),
    ]
    for anchor in plan["core_anchors"] + plan["optional_concepts"]:
        assert anchor["source_hash"] == hashlib.sha256(seed[anchor["source_field"]].encode()).hexdigest()
        assert anchor["concept_id"]
    for intent in plan["intents"]:
        assert intent["core_concept_ids"] == [a["concept_id"] for a in plan["core_anchors"]]
        assert intent["intent_id"]
    assert plan["intents"][0]["optional_concept_ids"] == [plan["optional_concepts"][0]["concept_id"]]
    assert plan["intents"][1]["optional_concept_ids"] == []
    assert query_planner.validate_scientific_query_plan(plan, seed=seed) == plan
    compiled = query_planner.compile_scientific_query_plan(plan, seed=seed)
    assert {q["query"] for q in compiled} == {
        '("carbon dioxide") AND (rca1p)',
        '("carbon dioxide") AND (rca1p) AND (yeast)',
    }
    assert all(q["query_content_hash"] for q in compiled)
    assert _response(seed, proposal) == result
    assert proposal == original


@pytest.mark.parametrize("location,key", [
    ("root", "provenance"), ("plan", "seed_sha256"), ("plan", "plan_content_hash"),
    ("plan", "target_question_sha256"), ("plan", "parent_plan_content_hash"),
    ("plan", "feedback_sha256"), ("plan", "feedback_gap_ids"),
    ("core", "source_type"), ("core", "source_hash"), ("core", "start"),
    ("core", "end"), ("core", "concept_id"), ("optional", "term"),
    ("intent", "intent_id"), ("intent", "core_concept_ids"),
    ("intent", "optional_concept_ids"), ("intent", "query_content_hash"),
])
def test_host_cannot_supply_machine_fields(location, key):
    proposal = _proposal()
    target = {"root": proposal, "plan": proposal["plan"],
              "core": proposal["plan"]["core_anchors"][0],
              "optional": proposal["plan"]["optional_anchors"][0],
              "intent": proposal["plan"]["intents"][0]}[location]
    target[key] = "forged"
    with pytest.raises(CurieContractError, match="schema invalid"):
        _response(_seed(), proposal)


@pytest.mark.parametrize("snippet", ["Carbon dioxide", "invented mechanism", "carbon  dioxide"])
def test_non_exact_seed_span_is_rejected(snippet):
    proposal = _proposal()
    proposal["plan"]["core_anchors"][0]["text_snippet"] = snippet
    with pytest.raises(CurieContractError, match="exact.*span"):
        _response(_seed(), proposal)


def test_ambiguous_overlapping_seed_span_is_rejected():
    seed, proposal = _seed(), _proposal()
    seed["scientific_question"] = "aaa"
    proposal["plan"]["core_anchors"][0]["text_snippet"] = "aa"
    with pytest.raises(CurieContractError, match="unique.*span"):
        _response(seed, proposal)


@pytest.mark.parametrize("indices", [[True], [-1], [1], [0, 0]])
def test_optional_selection_must_reference_distinct_in_range_indices(indices):
    proposal = _proposal()
    proposal["plan"]["intents"][0]["optional_anchor_indices"] = indices
    with pytest.raises(CurieContractError):
        _response(_seed(), proposal)


def test_materialized_replan_uses_only_request_provenance():
    seed, proposal = _seed(), _proposal()
    proposal["plan"]["intents"] = proposal["plan"]["intents"][:1]
    previous = _response(seed, proposal)["plan"]
    feedback = {
        "previous_plan": previous,
        "executed_queries": query_planner.compile_scientific_query_plan(previous, seed=seed),
        "executed_plans": [{"plan_content_hash": previous["plan_content_hash"]}],
        "validated_coverage_gaps": [{"gap_id": "G1"}], "semantic_rejections": [],
        "attempt_outcome": {"type": "ZERO_DISCOVERY"},
    }
    proposal["plan"]["intents"] = [{"optional_anchor_indices": []}]
    plan = _response(seed, proposal, index=1, feedback=feedback)["plan"]
    assert plan["parent_plan_content_hash"] == previous["plan_content_hash"]
    canonical_feedback = json.dumps(feedback, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert plan["feedback_sha256"] == hashlib.sha256(canonical_feedback).hexdigest()
    assert plan["feedback_gap_ids"] == ["G1"]
    assert plan["reformulation_index"] == 1


def _duplicate_span_replan():
    seed, proposal = _seed(), _proposal()
    seed["scientific_question"] = "Does carbon dioxide alter yeast sensing and yeast growth?"
    proposal["plan"]["optional_anchors"] = []
    proposal["plan"]["intents"] = [{"optional_anchor_indices": []}]
    previous = _response(seed, proposal)["plan"]
    feedback = {
        "previous_plan": previous,
        "executed_queries": query_planner.compile_scientific_query_plan(previous, seed=seed),
        "executed_plans": [{"plan_content_hash": previous["plan_content_hash"]}],
        "validated_coverage_gaps": [{"gap_id": "G1", "topic": "yeast",
                                     "search_directions": ["yeast"]}],
        "semantic_rejections": [], "attempt_outcome": {"type": "COVERAGE_GAP"},
    }
    request = query_planner.prepare_scientific_query_plan_request(
        seed, reformulation_index=1, feedback=feedback,
    )
    decision = query_planner.validate_scientific_query_plan_response(
        seed, request=request, raw_response=json.dumps({
            "status": "NO_ADMISSIBLE_REPLAN", "reason": "Needs host choice", "plan": None,
        }).encode(),
    )
    return seed, request, decision


def test_duplicate_span_formal_candidate_is_selected_without_lossy_reprojection():
    seed, request, decision = _duplicate_span_replan()
    assert decision["status"] == "REPROPOSAL_REQUIRED"
    candidate = decision["candidates"][0]
    exact_plan = candidate["plan"]
    anchor = exact_plan["optional_concepts"][0]
    assert (anchor["text_snippet"], anchor["start"], anchor["end"]) == ("yeast", 26, 31)
    # This legitimate offset-bound formal candidate cannot be a minimal proposal.
    with pytest.raises(CurieContractError, match="unique.*span"):
        query_planner.materialize_scientific_query_plan(
            seed, request=request, proposal=query_planner._scientific_intent(exact_plan),
        )
    followup = decision["next_request"]
    result = query_planner.validate_scientific_query_plan_response(
        seed, request=followup, raw_response=json.dumps({
            "status": "SELECT_CANDIDATE", "reason": "Target the yeast gap",
            "candidate_id": candidate["candidate_id"],
        }).encode(),
    )
    assert result["status"] == "PLAN"
    assert result["plan"] == exact_plan
    assert result["plan"]["parent_plan_content_hash"] == request["previous_plan_content_hash"]
    assert result["plan"]["feedback_sha256"] == request["feedback_sha256"]
    assert result["plan"]["feedback_gap_ids"] == ["G1"]
    assert query_planner.validate_scientific_query_plan(result["plan"], seed=seed) == exact_plan
    assert result["compiled_queries"][0]["query"] == '("carbon dioxide") AND (rca1p) AND (yeast)'


@pytest.mark.parametrize("candidate_id", ["candidate-unknown", "candidate-" + "0" * 64])
def test_selection_rejects_unauthorized_candidate_id(candidate_id):
    seed, _request, decision = _duplicate_span_replan()
    with pytest.raises(CurieContractError, match="candidate_id.*not authorized"):
        query_planner.validate_scientific_query_plan_response(
            seed, request=decision["next_request"], raw_response=json.dumps({
                "status": "SELECT_CANDIDATE", "reason": "choose", "candidate_id": candidate_id,
            }).encode(),
        )


@pytest.mark.parametrize("key", ["anchors", "start", "candidate_sha256", "concept_id",
                                 "plan", "provenance", "query"])
def test_selection_rejects_host_candidate_reconstruction_fields(key):
    seed, _request, decision = _duplicate_span_replan()
    response = {"status": "SELECT_CANDIDATE", "reason": "choose",
                "candidate_id": decision["candidates"][0]["candidate_id"], key: "forged"}
    with pytest.raises(CurieContractError, match="schema invalid"):
        query_planner.validate_scientific_query_plan_response(
            seed, request=decision["next_request"], raw_response=json.dumps(response).encode(),
        )


@pytest.mark.parametrize("changed", ["candidate_hash", "candidate_plan", "feedback", "parent"])
def test_selection_rejects_changed_enumeration_even_with_rehashed_request(changed):
    seed, _request, decision = _duplicate_span_replan()
    followup = copy.deepcopy(decision["next_request"])
    if changed == "candidate_hash":
        followup["candidates"][0]["candidate_sha256"] = "0" * 64
    elif changed == "candidate_plan":
        plan = followup["candidates"][0]["plan"]
        anchor = plan["optional_concepts"][0]
        anchor.update(start=44, end=49)
        plan.pop("plan_content_hash")
        plan = query_planner.validate_scientific_query_plan(plan, seed=seed)
        followup["candidates"][0].update(
            plan=plan, candidate_sha256=query_planner._sha(plan),
            candidate_id="candidate-" + query_planner._sha(plan),
        )
    elif changed == "feedback":
        followup["feedback"]["validated_coverage_gaps"][0]["topic"] = "growth"
        followup["feedback_sha256"] = query_planner._sha(followup["feedback"])
    else:
        previous = followup["feedback"]["previous_plan"]
        previous["intents"][0]["intent_id"] = "changed-parent-identity"
        previous.pop("plan_content_hash")
        followup["feedback"]["previous_plan"] = query_planner.validate_scientific_query_plan(previous, seed=seed)
        followup["previous_plan_content_hash"] = followup["feedback"]["previous_plan"]["plan_content_hash"]
        followup["feedback_sha256"] = query_planner._sha(followup["feedback"])
    followup["candidate_set_sha256"] = query_planner._sha(followup["candidates"])
    followup["request_sha256"] = query_planner._planner_request_hash(followup)
    with pytest.raises(CurieContractError, match="enumeration/hash binding"):
        query_planner.validate_scientific_query_plan_response(
            seed, request=followup, raw_response=json.dumps({
                "status": "SELECT_CANDIDATE", "reason": "choose",
                "candidate_id": followup["candidates"][0]["candidate_id"],
            }).encode(),
        )
