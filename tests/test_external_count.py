from __future__ import annotations

import csv
from pathlib import Path

from freshfreq.external_count import count_documents_to_csv
from freshfreq.stats import count_documents


def read_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return {row["term"]: row for row in csv.DictReader(source)}


def test_chunked_count_matches_in_memory_count(tmp_path: Path) -> None:
    documents = ["Trade trade craft", "Trade and craft", "Trade and trade"]
    output = tmp_path / "frequency.csv"

    summary = count_documents_to_csv(
        documents,
        output,
        max_ngram=2,
        chunk_documents=1,
        work_dir=tmp_path,
    )
    rows = read_rows(output)
    expected = {record.term: record for record in count_documents(documents, max_ngram=2)}

    assert summary.document_count == 3
    assert summary.token_count == 9
    assert summary.term_count == len(expected)
    assert summary.chunk_count == 3
    assert rows["trade"]["occurrence_count"] == str(expected["trade"].occurrence_count)
    assert rows["trade"]["document_frequency"] == str(expected["trade"].document_frequency)
    assert rows["trade and"]["occurrence_count"] == "2"
    assert rows["trade and"]["document_frequency"] == "2"


def test_chunked_count_writes_header_for_empty_input(tmp_path: Path) -> None:
    output = tmp_path / "empty.csv"
    summary = count_documents_to_csv([], output, chunk_documents=2)

    assert summary.token_count == 0
    assert summary.term_count == 0
    assert output.read_text(encoding="utf-8").startswith("term,occurrence_count")
