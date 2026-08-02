from __future__ import annotations

import csv
import json
import math
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from freshfreq.dataset import metadata_path
from freshfreq.sources.wikipedia import DumpPart, download_part, write_manifest
from freshfreq.sources.wikipedia_build import WikipediaBuildPlan, write_build_manifest
from freshfreq.sources.wikipedia_extract import iter_wikipedia_documents
from freshfreq.stats import iter_ngrams
from freshfreq.tokenize import tokenize


@dataclass(frozen=True, slots=True)
class PartCount:
    part: str
    document_count: int
    token_count: int
    chunk_count: int


@dataclass(frozen=True, slots=True)
class StreamingSummary:
    database_path: Path
    completed_parts: int
    document_count: int
    token_count: int
    term_count: int


class StreamingCounter:
    def __init__(
        self,
        database_path: Path,
        *,
        snapshot: str,
        max_ngram: int,
        min_chars: int,
        chunk_documents: int,
    ) -> None:
        if chunk_documents < 1:
            raise ValueError("chunk_documents must be at least 1")
        self.database_path = database_path
        self.max_ngram = max_ngram
        self.chunk_documents = chunk_documents
        self.configuration = {
            "schema_version": 1,
            "snapshot": snapshot,
            "max_ngram": max_ngram,
            "min_chars": min_chars,
            "tokenizer_version": 1,
        }
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS frequencies (
                    term TEXT PRIMARY KEY,
                    occurrence_count INTEGER NOT NULL,
                    document_frequency INTEGER NOT NULL
                ) WITHOUT ROWID
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS completed_parts (
                    part TEXT PRIMARY KEY,
                    sha1 TEXT NOT NULL,
                    document_count INTEGER NOT NULL,
                    token_count INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    completed_at TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )
            encoded = json.dumps(self.configuration, sort_keys=True)
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'configuration'"
            ).fetchone()
            if row is not None and row[0] != encoded:
                raise ValueError(
                    "streaming database configuration does not match this build; "
                    "use another --work-dir or remove the incompatible database"
                )
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES ('configuration', ?)",
                (encoded,),
            )

    def is_complete(self, part: DumpPart) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT sha1 FROM completed_parts WHERE part = ?", (part.filename,)
            ).fetchone()
        return row is not None and row[0] == part.sha1

    @staticmethod
    def _merge(
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

    def count_part(
        self,
        part: DumpPart,
        documents: Iterable[str],
        on_chunk: Callable[[int, int], None] | None = None,
    ) -> PartCount:
        if self.is_complete(part):
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT document_count, token_count, chunk_count
                    FROM completed_parts WHERE part = ?
                    """,
                    (part.filename,),
                ).fetchone()
            return PartCount(part.filename, row[0], row[1], row[2])

        occurrences: Counter[str] = Counter()
        document_frequency: Counter[str] = Counter()
        document_count = 0
        token_count = 0
        chunk_count = 0

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for document in documents:
                tokens = tokenize(document)
                terms = list(iter_ngrams(tokens, self.max_ngram))
                occurrences.update(terms)
                document_frequency.update(set(terms))
                document_count += 1
                token_count += len(tokens)
                if document_count % self.chunk_documents == 0:
                    self._merge(connection, occurrences, document_frequency)
                    occurrences.clear()
                    document_frequency.clear()
                    chunk_count += 1
                    if on_chunk is not None:
                        on_chunk(chunk_count, document_count)

            if occurrences:
                self._merge(connection, occurrences, document_frequency)
                chunk_count += 1
                if on_chunk is not None:
                    on_chunk(chunk_count, document_count)

            connection.execute(
                """
                INSERT INTO completed_parts(
                    part, sha1, document_count, token_count, chunk_count, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    part.filename,
                    part.sha1,
                    document_count,
                    token_count,
                    chunk_count,
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.commit()

        return PartCount(part.filename, document_count, token_count, chunk_count)

    def summary(self) -> StreamingSummary:
        with self._connect() as connection:
            part_row = connection.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(document_count), 0), COALESCE(SUM(token_count), 0)
                FROM completed_parts
                """
            ).fetchone()
            term_count = connection.execute("SELECT COUNT(*) FROM frequencies").fetchone()[0]
        return StreamingSummary(
            self.database_path,
            part_row[0],
            part_row[1],
            part_row[2],
            term_count,
        )

    def export(self, output_path: Path, parts: tuple[DumpPart, ...]) -> StreamingSummary:
        summary = self.summary()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".part")
        with self._connect() as connection, temporary.open(
            "w", encoding="utf-8", newline=""
        ) as destination:
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
            if summary.token_count:
                rows = connection.execute(
                    """
                    SELECT term, occurrence_count, document_frequency
                    FROM frequencies
                    ORDER BY occurrence_count DESC, term ASC
                    """
                )
                for term, count, doc_frequency in rows:
                    probability = count / summary.token_count
                    writer.writerow(
                        [
                            term,
                            count,
                            doc_frequency,
                            f"{probability * 1_000_000:.6f}",
                            f"{math.log10(probability * 1_000_000_000):.4f}",
                        ]
                    )
        temporary.replace(output_path)
        metadata = {
            "format_version": 1,
            "language": "en",
            "source": "wikipedia",
            "snapshot": self.configuration["snapshot"],
            "inputs": [part.filename for part in parts],
            "input_count": len(parts),
            "generated_at": datetime.now(UTC).isoformat(),
            "document_count": summary.document_count,
            "token_count": summary.token_count,
            "term_count": summary.term_count,
            "max_ngram": self.max_ngram,
            "count_backend": "sqlite_streaming",
            "database": str(self.database_path),
            "frequency_unit": "per_million_tokens",
            "zipf_definition": "log10(occurrences_per_billion_tokens)",
        }
        sidecar = metadata_path(output_path)
        sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        return summary


def stream_wikipedia_build(
    plan: WikipediaBuildPlan,
    *,
    connections: int,
    min_chars: int,
    max_ngram: int,
    chunk_documents: int,
    delete_raw: bool,
    on_progress: Callable[[str], None] = print,
) -> StreamingSummary:
    plan.work_dir.mkdir(parents=True, exist_ok=True)
    database_path = plan.work_dir / f"wikipedia-{plan.snapshot}-counts.sqlite3"
    counter = StreamingCounter(
        database_path,
        snapshot=plan.snapshot,
        max_ngram=max_ngram,
        min_chars=min_chars,
        chunk_documents=chunk_documents,
    )
    write_manifest(plan.raw_dir, plan.snapshot, list(plan.parts))

    total_parts = len(plan.parts)
    for index, part in enumerate(plan.parts, start=1):
        if counter.is_complete(part):
            on_progress(f"part {index}/{len(plan.parts)} already counted: {part.filename}")
            raw_path = plan.raw_dir / part.filename
            if delete_raw:
                raw_path.unlink(missing_ok=True)
            continue

        on_progress(f"downloading part {index}/{len(plan.parts)}: {part.filename}")
        raw_path = download_part(part, plan.raw_dir, connections)
        on_progress(f"counting part {index}/{len(plan.parts)}: {part.filename}")
        documents = (
            document.text for document in iter_wikipedia_documents(raw_path, min_chars=min_chars)
        )
        counter.count_part(
            part,
            documents,
            on_chunk=lambda chunk, docs, part_index=index, total=total_parts: on_progress(
                f"part {part_index}/{total} chunk {chunk}: {docs:,} documents"
            ),
        )
        if delete_raw:
            raw_path.unlink()
            on_progress(f"deleted raw part after commit: {part.filename}")
        write_build_manifest(
            plan,
            stage="streaming",
            downloaded=[],
            extracted=[],
            details={
                "mode": "streaming",
                "database": str(database_path),
                "completed_parts": counter.summary().completed_parts,
                "delete_raw": delete_raw,
            },
        )

    summary = counter.export(plan.output_path, plan.parts)
    write_build_manifest(
        plan,
        stage="complete",
        downloaded=[],
        extracted=[],
        details={
            "mode": "streaming",
            "database": str(database_path),
            "completed_parts": summary.completed_parts,
            "delete_raw": delete_raw,
        },
    )
    return summary
