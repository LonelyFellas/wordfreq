from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from freshfreq.cli import count_command, main, parse_part_limit
from freshfreq.dataset import metadata_path
from freshfreq.sources.wikipedia import DumpPart
from freshfreq.sources.wikipedia_build import WikipediaBuildPlan


def test_count_command_metadata_does_not_count_ngrams_as_tokens(tmp_path: Path) -> None:
    source = tmp_path / "documents.txt"
    output = tmp_path / "frequency.csv"
    source.write_text("one two three\none two\n", encoding="utf-8")

    count_command(source, output, "test", None, max_ngram=3)

    metadata = json.loads(metadata_path(output).read_text(encoding="utf-8"))
    assert metadata["token_count"] == 5
    assert metadata["max_ngram"] == 3


def test_count_command_combines_multiple_inputs(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    output = tmp_path / "frequency.csv"
    first.write_text("one shared\n", encoding="utf-8")
    second.write_text("two shared\n", encoding="utf-8")

    count_command([first, second], output, "test", "20260801", max_ngram=1)

    metadata = json.loads(metadata_path(output).read_text(encoding="utf-8"))
    assert metadata["input"] is None
    assert metadata["inputs"] == [str(first), str(second)]
    assert metadata["input_count"] == 2
    assert metadata["document_count"] == 2
    assert metadata["token_count"] == 4


def test_parse_part_limit_accepts_all_or_positive_integer() -> None:
    assert parse_part_limit("all") is None
    assert parse_part_limit("12") == 12
    with pytest.raises(Exception, match="positive integer"):
        parse_part_limit("0")


def test_wikipedia_build_runs_all_stages(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "release.csv"
    raw = tmp_path / "raw/part.xml.bz2"
    extracted = tmp_path / "processed/part.txt"
    part = DumpPart("20260801", raw.name, "https://example.test/part", 10, "abc")
    plan = WikipediaBuildPlan(
        snapshot="20260801",
        parts=(part,),
        raw_dir=raw.parent,
        extracted_dir=extracted.parent,
        output_path=output,
        work_dir=tmp_path / "work",
        download_bytes=10,
        estimated_extracted_bytes=6,
        estimated_peak_bytes=28,
    )

    def fake_download(build_plan, connections):
        raw.parent.mkdir(parents=True)
        raw.write_bytes(b"downloaded")
        return [raw]

    def fake_extract(build_plan, downloaded, *, min_chars, workers):
        extracted.parent.mkdir(parents=True)
        extracted.write_text("Fresh words here.\n", encoding="utf-8")
        return [extracted]

    monkeypatch.setattr("freshfreq.cli.create_build_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr("freshfreq.cli.download_build_parts", fake_download)
    monkeypatch.setattr("freshfreq.cli.extract_build_parts", fake_extract)
    monkeypatch.setattr(
        sys,
        "argv",
        ["freshfreq", "wikipedia", "build", "--snapshot", "20260801"],
    )

    main()

    assert output.is_file()
    assert metadata_path(output).is_file()
    manifest = json.loads(
        output.with_suffix(".build-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["stage"] == "complete"
