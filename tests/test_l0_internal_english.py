import copy

import pytest

from research_loop import l0_contract
from research_loop import l0_language_boundary as boundary
from research_loop.l0_language import L0LanguageError, normalize_semantic_fields


def _contract(question, hypothesis):
    return l0_contract.build_initial_contract(
        "C1",
        "1",
        question,
        l0_contract.build_source_input(
            input_type="inline",
            description="RNA-seq count matrix from cochlear tissue",
            fmt="text",
        ),
        hypothesis,
    )


def test_english_input_passes_through_without_translation():
    fields = {
        "scientific_question": "How does noise damage the cochlea?",
        "hypothesis": "Oxidative stress contributes to hair-cell injury.",
    }

    def translator(_fields):
        raise AssertionError("English input must not invoke translation")

    normalized, receipt = normalize_semantic_fields(fields, translator=translator)
    assert normalized == fields
    assert receipt["mode"] == "passthrough"


def test_chinese_input_is_translated_once_and_checked_as_english(monkeypatch, tmp_path):
    calls = []

    def translate(_project, candidate_id, fields):
        calls.append((candidate_id, copy.deepcopy(fields)))
        return {
            "scientific_question": "Does cochlear melanin reduce noise-induced injury?",
            "hypothesis": "Melanin-associated programs may protect hair cells.",
            "source_description": fields["source_description"],
        }, {"backend": "test", "model": "test-model"}

    monkeypatch.setattr(boundary.provider, "_translate", translate)
    canonical = boundary.normalize_contract(
        tmp_path,
        "C1",
        _contract(
            "耳蜗黑色素是否降低噪声损伤？",
            "黑色素相关程序可能保护毛细胞。",
        ),
    )

    assert len(calls) == 1
    assert canonical["scientific_question"] == "Does cochlear melanin reduce noise-induced injury?"
    assert canonical["current_round"]["hypothesis"] == "Melanin-associated programs may protect hair cells."
    assert "language_normalization" not in canonical


def test_translation_output_must_be_english(monkeypatch, tmp_path):
    def translate(_project, _candidate_id, fields):
        return {
            "scientific_question": "仍然是中文",
            "hypothesis": "Still English.",
            "source_description": fields["source_description"],
        }, {"backend": "test"}

    monkeypatch.setattr(boundary.provider, "_translate", translate)
    with pytest.raises(boundary.L0LanguageBoundaryError, match="must be English"):
        boundary.normalize_contract(
            tmp_path,
            "C1",
            _contract("中文科学问题？", "中文假说。"),
        )


def test_unsupported_language_is_rejected_before_translation():
    calls = []

    def translator(_fields):
        calls.append(True)
        return {}, {}

    with pytest.raises(L0LanguageError, match="only Chinese and English"):
        normalize_semantic_fields(
            {
                "scientific_question": "蝸牛の色素と騒音障害",
                "hypothesis": "English hypothesis.",
            },
            translator=translator,
        )
    assert calls == []
