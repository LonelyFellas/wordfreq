import pytest

from freshfreq.stats import count_documents, iter_ngrams
from freshfreq.tokenize import tokenize


def test_tokenize_normalizes_case_and_apostrophes() -> None:
    assert tokenize("Actually, DON'T stop.") == ["actually", "don't", "stop"]


def test_count_documents_tracks_occurrences_and_dispersion() -> None:
    records = count_documents(["Trade trade craft", "Trade hour"])
    by_term = {record.term: record for record in records}

    assert by_term["trade"].occurrence_count == 3
    assert by_term["trade"].document_frequency == 2
    assert by_term["craft"].document_frequency == 1
    assert by_term["trade"].zipf_frequency > by_term["craft"].zipf_frequency


def test_empty_input_has_no_records() -> None:
    assert count_documents(["", "---"]) == []


def test_iter_ngrams_emits_contiguous_terms() -> None:
    assert list(iter_ngrams(["false", "friend", "example"], 3)) == [
        "false",
        "friend",
        "example",
        "false friend",
        "friend example",
        "false friend example",
    ]


def test_count_documents_tracks_phrase_occurrences_and_dispersion() -> None:
    records = count_documents(
        ["A false friend is false", "Another false friend"], max_ngram=2
    )
    by_term = {record.term: record for record in records}

    assert by_term["false friend"].occurrence_count == 2
    assert by_term["false friend"].document_frequency == 2
    assert "friend is" in by_term


def test_count_documents_rejects_invalid_ngram_size() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        count_documents(["text"], max_ngram=0)
