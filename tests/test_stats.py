from freshfreq.stats import count_documents
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

