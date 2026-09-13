import pytest

from research_loop.l0_language import (
    L0LanguageError,
    classify_user_language,
    validate_internal_english,
)


def test_scientific_greek_symbols_do_not_expand_natural_language_scope():
    assert classify_user_language("β-catenin signaling in epithelial cells") == "en"
    assert classify_user_language("α-synuclein aggregation") == "en"
    assert validate_internal_english("TGF-β signaling fibrosis") == "TGF-β signaling fibrosis"


def test_greek_language_words_remain_unsupported():
    with pytest.raises(L0LanguageError, match="only Chinese and English"):
        classify_user_language("βιολογία cell response")
