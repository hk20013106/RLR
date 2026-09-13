import copy

import pytest

from research_loop import l0_contract
from research_loop import l0_language_boundary as boundary
from research_loop.l0_language import L0LanguageError, normalize_semantic_fields


def _fields(
    question="How does noise damage the cochlea?",
    hypothesis="Oxidative stress contributes to hair-cell injury.",
):
    return {
        "scientific_question": question,
        "hypothesis": hypothesis,
        "source_description": "RNA-seq count matrix from cochlear tissue",
    }


def _contract(question, hypothesis, description="RNA-seq count matrix from cochlear tissue"):
    return l0_contract.build_initial_contract(
        "C1",
        "1",
        question,
        l0_contract.build_source_input(
            input_type="inline",
            description=description,
            fmt="text",
        ),
        hypothesis,
    )


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


def test_contract_normalization_freezes_english_before_l0_hash(monkeypatch, tmp_path):
    calls = []

    def translate(_project, candidate_id, fields):
        calls.append((candidate_id, copy.deepcopy(fields)))
        return {
            "scientific_question": "Does cochlear melanin reduce noise injury?",
            "hypothesis": "Melanin-associated programs may protect hair cells.",
            "source_description": fields["source_description"],
        }, {"backend": "test", "model": "test-model"}

    monkeypatch.setattr(boundary, "_translate", translate)
    raw = _contract(
        "耳蜗黑色素是否降低噪声损伤？",
        "黑色素相关程序可能保护毛细胞。",
    )

    canonical = boundary.normalize_contract(tmp_path, "C1", raw)

    assert len(calls) == 1
    assert canonical["scientific_question"] == "Does cochlear melanin reduce noise injury?"
    assert canonical["current_round"]["hypothesis"].startswith("Melanin-associated")
    assert canonical["language_normalization"]["mode"] == "translated"
    assert canonical["language_normalization"]["target_language"] == "en"
    assert boundary._validate_normalized_contract(canonical) == []


def test_contract_english_fast_path_does_not_call_provider(monkeypatch, tmp_path):
    def translate(*_args, **_kwargs):
        raise AssertionError("English canonical input must not invoke translation")

    monkeypatch.setattr(boundary, "_translate", translate)
    canonical = boundary.normalize_contract(
        tmp_path,
        "C1",
        _contract(
            "How does noise damage the cochlea?",
            "Oxidative stress contributes to hair-cell injury.",
        ),
    )

    assert canonical["language_normalization"]["mode"] == "passthrough"
    assert boundary._validate_normalized_contract(canonical) == []


def test_continuation_does_not_retranslate_non_english_internal_memory(tmp_path):
    raw = l0_contract.build_continuation_contract(
        "C2",
        "2",
        "1",
        "C1",
        "Does cochlear melanin reduce noise injury?",
        l0_contract.build_source_input(
            input_type="inline",
            description="RNA-seq count matrix",
            fmt="text",
        ),
        {
            "hypothesis": "上一轮中文内部假说",
            "final_decision": "KEEP",
            "conclusion": "Previous English conclusion.",
            "memory_hash": "a" * 64,
        },
        "Melanin-associated programs may protect hair cells.",
    )

    with pytest.raises(
        boundary.L0LanguageBoundaryError,
        match="inherited internal semantics must already be English",
    ):
        boundary.normalize_contract(tmp_path, "C2", raw)
