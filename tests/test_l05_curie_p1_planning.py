"""P1 contract tests for the existing Curie planner owner."""

import hashlib
import copy
import json
from itertools import combinations

import pytest

from research_loop import research_seed
from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie.query_planner import (
    compile_scientific_query_plan,
    propose_scientific_query_plan,
    validate_scientific_query_plan,
)
from research_loop.l05_curie.multisource import build_multisource_query_plan
from research_loop import structured_execution
from research_loop.l05_curie import query_planner


def _seed():
    return {
        "schema_version": "L1ResearchSeed/v1",
        "candidate_id": "C1",
        "round_id": "1",
        "scientific_question": "Does carbon dioxide alter yeast sensing?",
        "hypothesis_seed": "Rca1p regulates carbon dioxide sensing.",
    }


def _anchor(seed, field, snippet, concept_id):
    value = seed[field]
    start = value.index(snippet)
    return {
        "concept_id": concept_id,
        "term": snippet,
        "source_type": "QUESTION" if field == "scientific_question" else "INITIAL_HYPOTHESIS",
        "source_field": field,
        "text_snippet": snippet,
        "source_hash": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "start": start,
        "end": start + len(snippet),
    }


def _plan(seed):
    return {
        "schema_version": "L05ScientificQueryPlan/v2",
        "planner": "scientific-query-planner/v2",
        "seed_sha256": research_seed.seed_sha256(seed),
        "target_question_sha256": hashlib.sha256(seed["scientific_question"].encode()).hexdigest(),
        "parent_plan_content_hash": None,
        "feedback_sha256": None,
        "feedback_gap_ids": [],
        "reformulation_index": 0,
        "core_anchors": [
            _anchor(seed, "scientific_question", "carbon dioxide", "carbon-dioxide"),
            _anchor(seed, "hypothesis_seed", "Rca1p", "rca1p"),
        ],
        "optional_concepts": [],
        "unresolved_entities": ["Sk"],
        "advisory_search_constraints": [],
        "intents": [{
            "intent_id": "target-evidence",
            "core_concept_ids": ["carbon-dioxide", "rca1p"],
            "optional_concept_ids": [],
        }],
    }


def _composite_replan_fixture(*, execute_last_singleton=False):
    seed = _seed()
    seed["scientific_question"] = (
        "Does carbon dioxide (CO2) alter yeast sensing under nutrient limitation?"
    )
    previous = _plan(seed)
    synonym = _anchor(seed, "scientific_question", "CO2", "unused")
    synonym.pop("concept_id")
    evidence = "carbon dioxide (CO2)"
    synonym.update({
        "mapping_source": "authorized_seed_parenthetical",
        "mapping_version": "v1",
        "mapping_evidence": evidence,
        "mapping_evidence_start": seed["scientific_question"].index(evidence),
        "mapping_key": hashlib.sha256(evidence.encode()).hexdigest(),
    })
    previous["core_anchors"][0]["synonyms"] = [synonym]
    optional_ids = ("yeast", "sensing", "nutrient")
    previous["optional_concepts"] = [
        _anchor(seed, "scientific_question", term, term) for term in optional_ids
    ]
    previous["intents"][0]["optional_concept_ids"] = list(optional_ids)
    previous = validate_scientific_query_plan(previous, seed=seed)
    executed = []
    for size in range(4):
        for subset in combinations(optional_ids, size):
            if subset == ("nutrient",) and not execute_last_singleton:
                continue
            variant = copy.deepcopy(previous)
            variant.pop("plan_content_hash")
            variant["intents"][0]["optional_concept_ids"] = list(subset)
            executed.extend(compile_scientific_query_plan(variant, seed=seed))
    feedback = {
        "previous_plan": previous,
        "executed_queries": executed,
        "executed_plans": [{"plan_content_hash": previous["plan_content_hash"]}],
        "validated_coverage_gaps": [{"gap_id": "G1"}],
        "semantic_rejections": [],
        "attempt_outcome": {"type": "COVERAGE_GAP"},
    }
    return seed, previous, feedback


def test_v2_compiler_uses_authorized_core_and_stable_boolean_groups():
    seed = _seed()
    plan = validate_scientific_query_plan(_plan(seed), seed=seed)
    queries = compile_scientific_query_plan(plan, seed=seed)
    assert len(queries) == 1
    assert queries[0]["query"] == '("carbon dioxide") AND (rca1p)'
    assert compile_scientific_query_plan(plan, seed=seed) == queries


@pytest.mark.parametrize("change", [
    {"source_type": "DERIVED_HYPOTHESIS"},
    {"text_snippet": "invented mechanism"},
    {"source_hash": "0" * 64},
    {"start": 0},
])
def test_v2_rejects_unverified_core_source(change):
    seed = _seed()
    plan = _plan(seed)
    plan["core_anchors"][0].update(change)
    with pytest.raises(CurieContractError):
        validate_scientific_query_plan(plan, seed=seed)


def test_v2_rejects_negative_exclusion_and_unverified_synonym():
    seed = _seed()
    plan = _plan(seed)
    plan["reformulation_index"] = 1
    plan["parent_plan_content_hash"] = "a" * 64
    plan["feedback_sha256"] = "b" * 64
    plan["feedback_gap_ids"] = ["G1"]
    plan["advisory_search_constraints"] = [{
        "text": "NOT mouse", "source_attempt": 1, "evidence_ids": ["E1"],
    }]
    assert "NOT" not in compile_scientific_query_plan(
        validate_scientific_query_plan(plan, seed=seed), seed=seed
    )[0]["query"]
    plan = _plan(seed)
    plan["core_anchors"][0]["synonyms"] = [{"term": "CO2"}]
    with pytest.raises(CurieContractError):
        validate_scientific_query_plan(plan, seed=seed)


def test_v2_accepts_only_seed_parenthetical_synonym_with_exact_provenance():
    seed = _seed()
    seed["scientific_question"] = "Does carbon dioxide (CO2) alter yeast sensing?"
    plan = _plan(seed)
    evidence = "carbon dioxide (CO2)"
    alternative = _anchor(seed, "scientific_question", "CO2", "unused")
    alternative.pop("concept_id")
    alternative.update({
        "mapping_source": "authorized_seed_parenthetical", "mapping_version": "v1",
        "mapping_evidence": evidence, "mapping_evidence_start": seed["scientific_question"].index(evidence),
        "mapping_key": hashlib.sha256(evidence.encode()).hexdigest(),
    })
    plan["core_anchors"][0]["synonyms"] = [alternative]
    validated = validate_scientific_query_plan(plan, seed=seed)
    assert '("carbon dioxide" OR co2)' in compile_scientific_query_plan(validated, seed=seed)[0]["query"]
    plan["core_anchors"][0]["synonyms"][0]["mapping_key"] = "0" * 64
    with pytest.raises(CurieContractError, match="mapping evidence hash"):
        validate_scientific_query_plan(plan, seed=seed)


def test_v2_optional_synonym_cannot_bypass_mapping_validation():
    seed = _seed()
    plan = _plan(seed)
    optional = _anchor(seed, "hypothesis_seed", "sensing", "optional")
    optional["synonyms"] = [{"term": "magic"}]
    plan["optional_concepts"] = [optional]
    plan["intents"][0]["optional_concept_ids"] = ["optional"]
    with pytest.raises(CurieContractError):
        validate_scientific_query_plan(plan, seed=seed)


def test_v2_structured_proposal_adapts_to_shared_query_plan(tmp_path, monkeypatch):
    seed = _seed()
    seen = {}

    def fake_structured(_spec, *, prompt, schema, work_dir, purpose):
        seen.update(prompt=prompt, schema=schema, work_dir=work_dir, purpose=purpose)
        payload = {"status": "PLAN", "reason": "direct seed concepts", "plan": _plan(seed)}
        return {
            "payload": payload,
            "receipt": {"prompt_hash": "p", "validation_status": "PASS"},
            "raw_output": json.dumps(payload),
        }

    monkeypatch.setattr(structured_execution, "run_structured_model", fake_structured)
    decision = propose_scientific_query_plan(
        seed, spec=object(), work_dir=tmp_path, reformulation_index=0,
    )
    assert decision["status"] == "PLAN"
    assert "carbon dioxide" in seen["prompt"]
    assert '"status": "PLAN"' not in seen["prompt"]
    assert seen["purpose"] == "l05_scientific_query_planning"
    shared = build_multisource_query_plan(
        seed, seed_sha256=research_seed.seed_sha256(seed), providers=["europe-pmc"],
        scientific_plan=decision["plan"],
    )
    assert shared["schema_version"] == "L05QueryPlan/v1"
    assert shared["queries"][0]["origin"] == "generated"
    assert shared["queries"][0]["query_content_hash"]


def test_no_admissible_replan_cannot_replace_invalid_initial_plan(tmp_path, monkeypatch):
    payload = {"status": "NO_ADMISSIBLE_REPLAN", "reason": "none", "plan": None}
    monkeypatch.setattr(structured_execution, "run_structured_model", lambda *_args, **_kwargs: {
        "payload": payload, "receipt": {}, "raw_output": json.dumps(payload),
    })
    with pytest.raises(CurieContractError, match="initial"):
        propose_scientific_query_plan(_seed(), spec=object(), work_dir=tmp_path,
                                      reformulation_index=0)


def test_no_admissible_replan_requires_exhausted_seed_bound_transforms(tmp_path, monkeypatch):
    seed = _seed()
    seed["scientific_question"] = "Does carbon dioxide (CO2) alter yeast sensing?"
    previous = validate_scientific_query_plan(_plan(seed), seed=seed)
    executed = compile_scientific_query_plan(previous, seed=seed)
    feedback = {
        "previous_plan": previous,
        "executed_queries": executed,
        "validated_coverage_gaps": [{"gap_id": "G1"}],
        "semantic_rejections": [],
    }
    payload = {"status": "NO_ADMISSIBLE_REPLAN", "reason": "none", "plan": None}
    monkeypatch.setattr(structured_execution, "run_structured_model", lambda *_args, **_kwargs: {
        "payload": payload, "receipt": {}, "raw_output": json.dumps(payload),
    })
    with pytest.raises(CurieContractError, match="synonym"):
        propose_scientific_query_plan(seed, spec=object(), work_dir=tmp_path,
                                      reformulation_index=1, feedback=feedback)


def test_no_admissible_replan_after_exhausted_finite_plan(tmp_path, monkeypatch):
    seed = _seed()
    previous = validate_scientific_query_plan(_plan(seed), seed=seed)
    feedback = {
        "previous_plan": previous,
        "executed_queries": compile_scientific_query_plan(previous, seed=seed),
        "validated_coverage_gaps": [{"gap_id": "G1"}],
        "semantic_rejections": [],
    }
    payload = {"status": "NO_ADMISSIBLE_REPLAN", "reason": "all finite variants executed", "plan": None}
    monkeypatch.setattr(structured_execution, "run_structured_model", lambda *_args, **_kwargs: {
        "payload": payload, "receipt": {"validation_status": "PASS"},
        "raw_output": json.dumps(payload),
    })
    decision = propose_scientific_query_plan(seed, spec=object(), work_dir=tmp_path,
                                             reformulation_index=1, feedback=feedback)
    assert decision["status"] == "NO_ADMISSIBLE_REPLAN"


def test_no_admissible_replan_must_use_gap_targeted_seed_intent(tmp_path, monkeypatch):
    seed = _seed()
    previous = validate_scientific_query_plan(_plan(seed), seed=seed)
    feedback = {
        "previous_plan": previous,
        "executed_queries": compile_scientific_query_plan(previous, seed=seed),
        "executed_plans": [{"plan_content_hash": previous["plan_content_hash"]}],
        "validated_coverage_gaps": [{
            "gap_id": "G1", "topic": "yeast sensing",
            "reason": "Direct yeast sensing evidence is missing.",
            "search_directions": ["target yeast sensing evidence"],
        }],
        "semantic_rejections": [],
        "attempt_outcome": {"type": "COVERAGE_GAP"},
    }
    targeted = _plan(seed)
    targeted["reformulation_index"] = 1
    for key in ("parent_plan_content_hash", "feedback_sha256", "feedback_gap_ids"):
        targeted.pop(key)
    targeted["optional_concepts"] = [_anchor(seed, "scientific_question", "yeast sensing", "gap-term")]
    targeted["intents"][0]["optional_concept_ids"] = ["gap-term"]
    proposals = [
        {"status": "NO_ADMISSIBLE_REPLAN", "reason": "none", "plan": None},
        {"status": "PLAN", "reason": "target validated yeast sensing gap", "plan": targeted},
    ]
    calls = []

    def fake_structured(*_args, **kwargs):
        calls.append(kwargs)
        payload = proposals.pop(0)
        return {"payload": payload, "receipt": {"validation_status": "PASS"},
                "raw_output": json.dumps(payload)}

    monkeypatch.setattr(structured_execution, "run_structured_model", fake_structured)
    decision = propose_scientific_query_plan(
        seed, spec=object(), work_dir=tmp_path,
        reformulation_index=1, feedback=feedback,
    )
    assert decision["status"] == "PLAN"
    assert len(calls) == 2
    assert decision["plan"]["feedback_gap_ids"] == ["G1"]
    compiled = compile_scientific_query_plan(decision["plan"], seed=seed)
    assert len(compiled) == 1
    assert compiled[0]["query_content_hash"] not in {
        item["query_content_hash"] for item in feedback["executed_queries"]
    }
    assert '"yeast sensing"' in compiled[0]["query"]


def test_no_admissible_replan_when_gap_target_is_already_executed(tmp_path, monkeypatch):
    seed = _seed()
    previous = validate_scientific_query_plan(_plan(seed), seed=seed)
    targeted = _plan(seed)
    targeted["optional_concepts"] = [_anchor(seed, "scientific_question", "yeast sensing", "gap-term")]
    targeted["intents"][0]["optional_concept_ids"] = ["gap-term"]
    targeted_query = compile_scientific_query_plan(targeted, seed=seed)[0]
    feedback = {
        "previous_plan": previous,
        "executed_queries": compile_scientific_query_plan(previous, seed=seed) + [targeted_query],
        "executed_plans": [{"plan_content_hash": previous["plan_content_hash"]}],
        "validated_coverage_gaps": [{
            "gap_id": "G1", "topic": "yeast sensing",
            "reason": "Direct yeast sensing evidence is missing.",
            "search_directions": ["target yeast sensing evidence"],
        }],
        "semantic_rejections": [],
        "attempt_outcome": {"type": "COVERAGE_GAP"},
    }
    payload = {"status": "NO_ADMISSIBLE_REPLAN", "reason": "none", "plan": None}
    monkeypatch.setattr(structured_execution, "run_structured_model", lambda *_args, **_kwargs: {
        "payload": payload, "receipt": {"validation_status": "PASS"},
        "raw_output": json.dumps(payload),
    })
    decision = propose_scientific_query_plan(
        seed, spec=object(), work_dir=tmp_path,
        reformulation_index=1, feedback=feedback,
    )
    assert decision["status"] == "NO_ADMISSIBLE_REPLAN"


def test_no_admissible_replan_cannot_claim_exhaustion_for_generic_coverage_gap(tmp_path, monkeypatch):
    seed = _seed()
    previous = validate_scientific_query_plan(_plan(seed), seed=seed)
    feedback = {
        "previous_plan": previous,
        "executed_queries": compile_scientific_query_plan(previous, seed=seed),
        "executed_plans": [{"plan_content_hash": previous["plan_content_hash"]}],
        "validated_coverage_gaps": [{
            "gap_id": "NO_LOCATED_INTERPRETIVE_EVIDENCE",
            "topic": "located results or interpretation",
            "reason": "No verified interpretive extract was located.",
            "search_directions": ["refine the query toward direct empirical evidence"],
        }],
        "semantic_rejections": [],
        "attempt_outcome": {"type": "COVERAGE_GAP"},
    }
    payload = {"status": "NO_ADMISSIBLE_REPLAN", "reason": "none", "plan": None}
    monkeypatch.setattr(structured_execution, "run_structured_model", lambda *_args, **_kwargs: {
        "payload": payload, "receipt": {"validation_status": "PASS"},
        "raw_output": json.dumps(payload),
    })
    with pytest.raises(CurieContractError, match="cannot prove.*exhausted"):
        propose_scientific_query_plan(
            seed, spec=object(), work_dir=tmp_path,
            reformulation_index=1, feedback=feedback,
        )


def test_composite_split_prevents_premature_no_admissible_replan(tmp_path, monkeypatch):
    seed, previous, feedback = _composite_replan_fixture()
    calls = []

    def fake_structured(*_args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            payload = {"status": "NO_ADMISSIBLE_REPLAN", "reason": "exhausted", "plan": None}
        else:
            offered = json.loads(kwargs["prompt"].rsplit("\n", 1)[-1])
            split = [item for item in offered if item["operation"] == "composite intent split"]
            assert split, "the correction prompt must contain a validated split"
            assert all(item["plan"]["core_anchors"] == previous["core_anchors"] for item in split)
            assert all(item["plan"]["intents"][0]["core_concept_ids"] ==
                       previous["intents"][0]["core_concept_ids"] for item in split)
            selected = next(item["plan"] for item in split
                            if item["plan"]["intents"][0]["optional_concept_ids"] == ["nutrient"])
            payload = {"status": "PLAN", "reason": "split composite", "plan": selected}
        return {"payload": payload, "receipt": {"validation_status": "PASS"},
                "raw_output": json.dumps(payload)}

    monkeypatch.setattr(structured_execution, "run_structured_model", fake_structured)
    decision = propose_scientific_query_plan(
        seed, spec=object(), work_dir=tmp_path,
        reformulation_index=1, feedback=feedback,
    )
    assert decision["status"] == "PLAN"
    assert len(calls) == 2
    assert decision["plan"]["core_anchors"] == previous["core_anchors"]
    assert compile_scientific_query_plan(decision["plan"], seed=seed)[0]["query_content_hash"] not in {
        item["query_content_hash"] for item in feedback["executed_queries"]
    }
    audit = decision["receipt"]["replan_enumeration"]
    assert [item["kind"] for item in audit["transformations"]] == [
        "optional removal", "grounded core synonym expansion",
        "non-essential design constraint removal", "validated gap targeted intent",
        "composite intent split",
    ]
    assert audit["transformations"][-1]["applicable"] is True


def test_composite_split_executed_content_is_not_new(tmp_path, monkeypatch):
    seed, _previous, feedback = _composite_replan_fixture(execute_last_singleton=True)
    for index, item in enumerate(feedback["executed_queries"]):
        item["query_id"] = f"renamed-execution-{index}"
    payload = {"status": "NO_ADMISSIBLE_REPLAN", "reason": "exhausted", "plan": None}
    calls = []

    def fake_structured(*_args, **_kwargs):
        calls.append(1)
        return {"payload": payload, "receipt": {"validation_status": "PASS"},
                "raw_output": json.dumps(payload)}

    monkeypatch.setattr(structured_execution, "run_structured_model", fake_structured)
    decision = propose_scientific_query_plan(
        seed, spec=object(), work_dir=tmp_path,
        reformulation_index=1, feedback=feedback,
    )
    assert decision["status"] == "NO_ADMISSIBLE_REPLAN"
    assert len(calls) == 1
    audit = decision["receipt"]["replan_enumeration"]
    assert all(item["outcome"] != "admissible" for transformation in audit["transformations"]
               for item in transformation["candidates"])


def test_replan_without_optional_has_explicit_inapplicable_split(tmp_path, monkeypatch):
    seed = _seed()
    previous = validate_scientific_query_plan(_plan(seed), seed=seed)
    feedback = {
        "previous_plan": previous,
        "executed_queries": compile_scientific_query_plan(previous, seed=seed),
        "executed_plans": [{"plan_content_hash": previous["plan_content_hash"]}],
        "validated_coverage_gaps": [{"gap_id": "G1"}],
        "semantic_rejections": [],
        "attempt_outcome": {"type": "COVERAGE_GAP"},
    }
    payload = {"status": "NO_ADMISSIBLE_REPLAN", "reason": "exhausted", "plan": None}
    monkeypatch.setattr(structured_execution, "run_structured_model", lambda *_args, **_kwargs: {
        "payload": payload, "receipt": {"validation_status": "PASS"},
        "raw_output": json.dumps(payload),
    })
    decision = propose_scientific_query_plan(
        seed, spec=object(), work_dir=tmp_path,
        reformulation_index=1, feedback=feedback,
    )
    split = next(item for item in decision["receipt"]["replan_enumeration"]["transformations"]
                 if item["kind"] == "composite intent split")
    assert split["applicable"] is False
    assert split["candidates"] == []
    assert split["reason"]


def test_replan_candidate_contract_error_is_not_exhaustion(tmp_path, monkeypatch):
    seed, _previous, feedback = _composite_replan_fixture()
    payload = {"status": "NO_ADMISSIBLE_REPLAN", "reason": "exhausted", "plan": None}
    monkeypatch.setattr(structured_execution, "run_structured_model", lambda *_args, **_kwargs: {
        "payload": payload, "receipt": {"validation_status": "PASS"},
        "raw_output": json.dumps(payload),
    })
    original_validator = query_planner.validate_scientific_query_plan

    def fail_candidate(plan, *, seed):
        if plan["reformulation_index"] == 1:
            raise CurieContractError("candidate invariant failed")
        return original_validator(plan, seed=seed)

    monkeypatch.setattr(query_planner, "validate_scientific_query_plan", fail_candidate)
    with pytest.raises(CurieContractError, match="candidate invariant failed"):
        propose_scientific_query_plan(
            seed, spec=object(), work_dir=tmp_path,
            reformulation_index=1, feedback=feedback,
        )


def test_split_content_identity_ignores_ids_order_and_term_formatting():
    seed, previous, _feedback = _composite_replan_fixture()
    first = copy.deepcopy(previous)
    first.pop("plan_content_hash")
    first["intents"][0]["optional_concept_ids"] = ["nutrient"]
    changed = copy.deepcopy(first)
    changed["intents"][0]["intent_id"] = "renamed-split"
    changed["intents"][0]["core_concept_ids"].reverse()
    changed["core_anchors"].reverse()
    changed["optional_concepts"].reverse()
    next(item for item in changed["optional_concepts"]
         if item["concept_id"] == "nutrient")["term"] = "  NUTRIENT  "
    assert validate_scientific_query_plan(first, seed=seed)["plan_content_hash"] == \
        validate_scientific_query_plan(changed, seed=seed)["plan_content_hash"]
    assert compile_scientific_query_plan(first, seed=seed)[0]["query_content_hash"] == \
        compile_scientific_query_plan(changed, seed=seed)[0]["query_content_hash"]


def test_replan_model_error_is_not_no_admissible(tmp_path, monkeypatch):
    seed, _previous, feedback = _composite_replan_fixture()

    def fail_model(*_args, **_kwargs):
        raise structured_execution.StructuredExecutionError(
            "model service failed", category="SERVICE_ERROR"
        )

    monkeypatch.setattr(structured_execution, "run_structured_model", fail_model)
    with pytest.raises(structured_execution.StructuredExecutionError, match="model service failed"):
        propose_scientific_query_plan(
            seed, spec=object(), work_dir=tmp_path,
            reformulation_index=1, feedback=feedback,
        )


def test_unresolved_core_anchor_rejected_before_compilation():
    seed = _seed()
    seed["scientific_question"] = "Does carbon dioxide and Sk alter yeast sensing?"
    plan = _plan(seed)
    plan["core_anchors"][0] = _anchor(seed, "scientific_question", "Sk", "sk-core")
    plan["intents"][0]["core_concept_ids"][0] = "sk-core"
    with pytest.raises(CurieContractError, match="unresolved.*CORE"):
        validate_scientific_query_plan(plan, seed=seed)
    with pytest.raises(CurieContractError, match="unresolved.*CORE"):
        compile_scientific_query_plan(plan, seed=seed)
    with pytest.raises(CurieContractError, match="unresolved.*CORE"):
        build_multisource_query_plan(
            seed, seed_sha256=research_seed.seed_sha256(seed),
            providers=["europe-pmc"], scientific_plan=plan,
        )


def test_compiler_defensively_rejects_unresolved_core_if_validator_is_bypassed(monkeypatch):
    seed = _seed()
    seed["scientific_question"] = "Does carbon dioxide and Sk alter yeast sensing?"
    plan = _plan(seed)
    plan["core_anchors"][0] = _anchor(seed, "scientific_question", "Sk", "sk-core")
    plan["intents"][0]["core_concept_ids"][0] = "sk-core"
    monkeypatch.setattr(query_planner, "validate_scientific_query_plan", lambda *_args, **_kwargs: plan)
    with pytest.raises(CurieContractError, match="unresolved.*CORE"):
        compile_scientific_query_plan(plan, seed=seed)


def test_unresolved_advisory_metadata_is_allowed():
    seed = _seed()
    plan = validate_scientific_query_plan(_plan(seed), seed=seed)
    assert plan["unresolved_entities"] == ["Sk"]
    assert "sk" not in compile_scientific_query_plan(plan, seed=seed)[0]["query"]


@pytest.mark.parametrize("unresolved", ["Sk", "  sk  ", "Ｓｋ"])
def test_unresolved_core_synonym_rejected_with_finite_normalization(unresolved):
    seed = _seed()
    seed["scientific_question"] = "Does carbon dioxide (Sk) alter yeast sensing?"
    plan = _plan(seed)
    evidence = "carbon dioxide (Sk)"
    synonym = _anchor(seed, "scientific_question", "Sk", "unused")
    synonym.pop("concept_id")
    synonym.update({
        "mapping_source": "authorized_seed_parenthetical", "mapping_version": "v1",
        "mapping_evidence": evidence,
        "mapping_evidence_start": seed["scientific_question"].index(evidence),
        "mapping_key": hashlib.sha256(evidence.encode()).hexdigest(),
    })
    plan["core_anchors"][0]["synonyms"] = [synonym]
    plan["unresolved_entities"] = [unresolved]
    with pytest.raises(CurieContractError, match="unresolved.*CORE"):
        validate_scientific_query_plan(plan, seed=seed)


def test_v2_rejects_unbounded_or_boolean_operator_core_without_truncation():
    seed = _seed()
    seed["scientific_question"] = "Does carbon dioxide alter yeast sensing? " + "x" * 250
    plan = _plan(seed)
    plan["core_anchors"][0] = _anchor(seed, "scientific_question", "x" * 250, "long-core")
    plan["intents"][0]["core_concept_ids"][0] = "long-core"
    with pytest.raises(CurieContractError, match="exceeds"):
        compile_scientific_query_plan(plan, seed=seed)
    seed["scientific_question"] = "Does carbon dioxide NOT change yeast sensing?"
    plan = _plan(seed)
    plan["core_anchors"][0] = _anchor(seed, "scientific_question", "NOT", "operator")
    plan["intents"][0]["core_concept_ids"][0] = "operator"
    with pytest.raises(CurieContractError, match="reserved Boolean"):
        validate_scientific_query_plan(plan, seed=seed)


def test_zero_discovery_replan_cannot_narrow_prior_boolean_query(tmp_path, monkeypatch):
    seed = _seed()
    previous = validate_scientific_query_plan(_plan(seed), seed=seed)
    proposed = _plan(seed)
    proposed["reformulation_index"] = 1
    for key in ("parent_plan_content_hash", "feedback_sha256", "feedback_gap_ids"):
        proposed.pop(key)
    proposed["optional_concepts"] = [_anchor(seed, "hypothesis_seed", "sensing", "new-optional")]
    proposed["intents"][0]["optional_concept_ids"] = ["new-optional"]
    payload = {"status": "PLAN", "reason": "try narrower query", "plan": proposed}
    monkeypatch.setattr(structured_execution, "run_structured_model", lambda *_args, **_kwargs: {
        "payload": payload, "receipt": {}, "raw_output": json.dumps(payload),
    })
    feedback = {
        "previous_plan": previous,
        "executed_queries": compile_scientific_query_plan(previous, seed=seed),
        "validated_coverage_gaps": [{"gap_id": "G1"}],
        "semantic_rejections": [],
        "attempt_outcome": {"type": "ZERO_DISCOVERY"},
    }
    with pytest.raises(CurieContractError, match="broaden"):
        propose_scientific_query_plan(seed, spec=object(), work_dir=tmp_path,
                                      reformulation_index=1, feedback=feedback)


def test_content_identity_ignores_intent_id_and_core_order():
    seed = _seed()
    original = validate_scientific_query_plan(_plan(seed), seed=seed)
    renamed = copy.deepcopy(_plan(seed))
    renamed["intents"][0]["intent_id"] = "renamed"
    renamed["intents"][0]["core_concept_ids"].reverse()
    renamed["core_anchors"].reverse()
    assert validate_scientific_query_plan(renamed, seed=seed)["plan_content_hash"] == original["plan_content_hash"]
