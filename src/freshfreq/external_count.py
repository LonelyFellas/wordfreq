from __future__ import annotations

import csv
import math
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from freshfreq.stats import iter_ngrams
from freshfreq.tokenize import tokenize


@dataclass(frozen=True, slots=True)
class CountSummary:
    document_count: int
    token_count: int
    term_count: int
    chunk_count: int


def _merge_chunk(
    connection: sqlite3.Connection,
    occurrences: Counter[str],
    document_frequency: Counter[str],
) -> None:
    connection.executemany(
        """
        INSERT INTO frequencies(term, occurrence_count, document_frequency)
        VALUES (?, ?, ?)
        ON CONFLICT(term) DO UPDATE SET
            occurrence_count = occurrence_count + excluded.occurrence_count,
            document_frequency = document_frequency + excluded.document_frequency
        """,
        (
            (term, count, document_frequency[term])
            for term, count in occurrences.items()
        ),
    )
    connection.commit()


def count_documents_to_csv(
    documents: Iterable[str],
    output_path: Path,
    *,
    max_ngram: int = 1,
    chunk_documents: int = 5_000,
    work_dir: Path | None = None,
    on_chunk: Callable[[int, int], None] | None = None,
) -> CountSummary:
    """Count bounded document chunks, merge on disk, and stream a frequency CSV."""
    if max_ngram < 1:
        raise ValueError("max_ngram must be at least 1")
    if chunk_documents < 1:
        raise ValueError("chunk_documents must be at least 1")
    if work_dir is not None:
        work_dir.mkdir(parents=True, exist_ok=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document_count = 0
    token_count = 0
    chunk_count = 0
    occurrences: Counter[str] = Counter()
    document_frequency: Counter[str] = Counter()

    with tempfile.TemporaryDirectory(prefix="freshfreq-", dir=work_dir) as temporary:
        database_path = Path(temporary) / "counts.sqlite3"
        with sqlite3.connect(database_path) as connection:
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute(
                """
                CREATE TABLE frequencies (
                    term TEXT PRIMARY KEY,
                    occurrence_count INTEGER NOT NULL,
                    document_frequency INTEGER NOT NULL
                ) WITHOUT ROWID
                """
            )

            for document in documents:
                tokens = tokenize(document)
                terms = list(iter_ngrams(tokens, max_ngram))
                occurrences.update(terms)
                document_frequency.update(set(terms))
                document_count += 1
                token_count += len(tokens)

                if document_count % chunk_documents == 0:
                    _merge_chunk(connection, occurrences, document_frequency)
                    occurrences.clear()
                    document_frequency.clear()
                    chunk_count += 1
                    if on_chunk is not None:
                        on_chunk(chunk_count, document_count)

            if occurrences:
                _merge_chunk(connection, occurrences, document_frequency)
                chunk_count += 1
                if on_chunk is not None:
                    on_chunk(chunk_count, document_count)

            term_count = connection.execute("SELECT COUNT(*) FROM frequencies").fetchone()[0]
            with output_path.open("w", encoding="utf-8", newline="") as destination:
                writer = csv.writer(destination)
                writer.writerow(
                    [
                        "term",
                        "occurrence_count",
                        "document_frequency",
                        "frequency_per_million",
                        "zipf_frequency",
                    ]
                )
                if token_count:
                    rows = connection.execute(
                        """
                        SELECT term, occurrence_count, document_frequency
                        FROM frequencies
                        ORDER BY occurrence_count DESC, term ASC
                        """
                    )
                    for term, count, doc_frequency in rows:
                        probability = count / token_count
                        writer.writerow(
                            [
                                term,
                                count,
                                doc_frequency,
                                f"{probability * 1_000_000:.6f}",
                                f"{math.log10(probability * 1_000_000_000):.4f}",
                            ]
                        )

    return CountSummary(document_count, token_count, term_count, chunk_count)
