import pytest

from research_loop.l05_curie import CurieContractError
from research_loop.l05_curie.query_language import (
    classify_supported_input_language,
    validate_english_retrieval_query,
)


def test_scientific_greek_symbols_do_not_expand_natural_language_scope():
    assert classify_supported_input_language("β-catenin signaling in epithelial cells") == "en"
    assert classify_supported_input_language("α-synuclein aggregation") == "en"
    assert validate_english_retrieval_query("TGF-β signaling fibrosis") == "TGF-β signaling fibrosis"


def test_greek_language_words_remain_unsupported():
    with pytest.raises(CurieContractError, match="only Chinese and English"):
        classify_supported_input_language("βιολογία cell response")
