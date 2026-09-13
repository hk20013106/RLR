import copy

import pytest

from research_loop import l0_contract
from research_loop.l0_language import L0LanguageError, normalize_semantic_fields


def _fields(question="How does noise damage the cochlea?", hypothesis="Oxidative stress contributes to hair-cell injury."):
    return {
        "scientific_question": question,
        "hypothesis": hypothesis,
        "source_description": "RNA-seq count matrix from cochlear tissue",
    }


def test_english_user_semantics_pass_through_without_translation():
    calls = []

    def translator(_fields):
        calls.append(True)
        raise AssertionError("English input must not be translated")

    normalized, receipt = normalize_semantic_fields(_fields(), translator=translator)

    assert normalized == _fields()
    assert calls == []
    assert receipt["mode"] == "passthrough"
    assert receipt["target_language"] == "en"


def test_chinese_user_semantics_translate_once_to_internal_english():
    source = _fields(
        question="耳蜗黑色素是否降低噪声损伤？",
        hypothesis="黑色素相关程序可能降低氧化应激和毛细胞损伤。",
    )
    calls = []

    def translator(fields):
        calls.append(copy.deepcopy(fields))
        return {
            "scientific_question": "Does cochlear melanin reduce noise-induced injury?",
            "hypothesis": "Melanin-associated programs may reduce oxidative stress and hair-cell injury.",
            "source_description": fields["source_description"],
        }, {"backend": "test", "model": "test-model"}

    normalized, receipt = normalize_semantic_fields(source, translator=translator)

    assert len(calls) == 1
    assert normalized["scientific_question"].startswith("Does cochlear melanin")
    assert normalized["hypothesis"].startswith("Melanin-associated programs")
    assert normalized["source_description"] == source["source_description"]
    assert receipt["mode"] == "translated"
    assert receipt["source_languages"]["scientific_question"] == "zh"
    assert receipt["source_languages"]["hypothesis"] == "zh"


def test_other_language_is_rejected_before_translation():
    calls = []

    def translator(_fields):
        calls.append(True)
        return {}, {}

    with pytest.raises(L0LanguageError, match="only Chinese and English"):
        normalize_semantic_fields(
            _fields(question="蝸牛の色素と騒音障害"),
            translator=translator,
        )
    assert calls == []


def test_schema_11_contract_rejects_non_english_internal_semantics(tmp_path):
    contract = l0_contract.build_initial_contract(
        "C1",
        "1",
        "耳蜗黑色素是否降低噪声损伤？",
        l0_contract.build_source_input(
            input_type="inline",
            description="RNA-seq count matrix",
            fmt="text",
        ),
        "黑色素相关程序可能保护毛细胞。",
    )
    contract = l0_contract.promote_to_current_schema(contract)
    raw = l0_contract.serialize_contract(contract)
    errors = l0_contract.validate_l0_input_contract(
        contract,
        {},
        tmp_path,
        "C1",
        artifact_path=tmp_path / "C1.l0_input.yaml",
        raw_bytes=raw,
    )

    assert any("scientific_question" in error and "English" in error for error in errors)
    assert any("current_round.hypothesis" in error and "English" in error for error in errors)
