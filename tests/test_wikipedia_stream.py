from __future__ import annotations

import csv
from pathlib import Path

import pytest

from freshfreq.sources.wikipedia import DumpPart
from freshfreq.sources.wikipedia_build import WikipediaBuildPlan
from freshfreq.sources.wikipedia_extract import WikipediaDocument
from freshfreq.sources.wikipedia_stream import StreamingCounter, stream_wikipedia_build


def make_part(filename: str = "part1.xml.bz2") -> DumpPart:
    return DumpPart("20260801", filename, f"https://example.test/{filename}", 10, "abc")


def make_counter(tmp_path: Path, chunk_documents: int = 1) -> StreamingCounter:
    return StreamingCounter(
        tmp_path / "counts.sqlite3",
        snapshot="20260801",
        max_ngram=1,
        min_chars=10,
        chunk_documents=chunk_documents,
    )


def test_streaming_counter_resumes_without_double_counting(tmp_path: Path) -> None:
    counter = make_counter(tmp_path)
    part = make_part()

    first = counter.count_part(part, ["one shared", "two shared"])
    resumed = counter.count_part(part, ["this must not be counted"])
    output = tmp_path / "frequency.csv"
    summary = counter.export(output, (part,))

    assert first == resumed
    assert summary.completed_parts == 1
    assert summary.document_count == 2
    assert summary.token_count == 4
    with output.open(encoding="utf-8", newline="") as source:
        rows = {row["term"]: row for row in csv.DictReader(source)}
    assert rows["shared"]["occurrence_count"] == "2"
    assert "must" not in rows


def test_streaming_counter_rolls_back_failed_part(tmp_path: Path) -> None:
    counter = make_counter(tmp_path)
    part = make_part()

    def failing_documents():
        yield "words before failure"
        raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated interruption"):
        counter.count_part(part, failing_documents())

    summary = counter.summary()
    assert summary.completed_parts == 0
    assert summary.document_count == 0
    assert summary.token_count == 0
    assert summary.term_count == 0


def test_streaming_counter_rejects_incompatible_database(tmp_path: Path) -> None:
    make_counter(tmp_path)
    with pytest.raises(ValueError, match="configuration does not match"):
        StreamingCounter(
            tmp_path / "counts.sqlite3",
            snapshot="20260801",
            max_ngram=2,
            min_chars=10,
            chunk_documents=1,
        )


def test_streaming_build_deletes_raw_only_after_counting(
    tmp_path: Path, monkeypatch
) -> None:
    part = make_part()
    raw_path = tmp_path / "raw" / part.filename
    plan = WikipediaBuildPlan(
        snapshot="20260801",
        parts=(part,),
        raw_dir=raw_path.parent,
        extracted_dir=tmp_path / "processed",
        output_path=tmp_path / "release.csv",
        work_dir=tmp_path / "work",
        download_bytes=10,
        estimated_extracted_bytes=6,
        estimated_peak_bytes=28,
    )

    def fake_download(dump_part, destination, connections):
        destination.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(b"verified dump")
        return raw_path

    monkeypatch.setattr("freshfreq.sources.wikipedia_stream.download_part", fake_download)
    monkeypatch.setattr(
        "freshfreq.sources.wikipedia_stream.iter_wikipedia_documents",
        lambda path, min_chars: iter([WikipediaDocument("Title", "fresh streaming words")]),
    )

    summary = stream_wikipedia_build(
        plan,
        connections=1,
        min_chars=10,
        max_ngram=1,
        chunk_documents=1,
        delete_raw=True,
        on_progress=lambda message: None,
    )

    assert summary.completed_parts == 1
    assert not raw_path.exists()
    assert plan.output_path.is_file()
    assert plan.output_path.with_suffix(".build-manifest.json").is_file()
