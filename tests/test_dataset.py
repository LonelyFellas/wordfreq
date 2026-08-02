from __future__ import annotations

from pathlib import Path

import pytest

from freshfreq.dataset import lookup_csv, metadata_path, read_metadata


def write_dataset(path: Path) -> None:
    path.write_text(
        "term,occurrence_count,document_frequency,frequency_per_million,zipf_frequency\n"
        "actually,12,8,24.000000,4.3802\n"
        "false friend,7,5,14.000000,4.1461\n"
        "word,5,4,10.000000,4.0000\n",
        encoding="utf-8",
    )


def test_lookup_csv_returns_typed_result(tmp_path: Path) -> None:
    dataset = tmp_path / "frequency.csv"
    write_dataset(dataset)
    result = lookup_csv(dataset, "actually")
    assert result is not None
    assert result.occurrence_count == 12
    assert result.frequency_per_million == 24.0


def test_lookup_csv_returns_phrase(tmp_path: Path) -> None:
    dataset = tmp_path / "frequency.csv"
    write_dataset(dataset)
    result = lookup_csv(dataset, "False   Friend")
    assert result is not None
    assert result.term == "false friend"
    assert result.occurrence_count == 7


def test_lookup_csv_rejects_empty_query(tmp_path: Path) -> None:
    dataset = tmp_path / "frequency.csv"
    write_dataset(dataset)
    with pytest.raises(ValueError, match="at least one"):
        lookup_csv(dataset, "---")


def test_read_metadata_uses_sidecar(tmp_path: Path) -> None:
    dataset = tmp_path / "frequency.csv"
    write_dataset(dataset)
    metadata_path(dataset).write_text('{"source": "wikipedia"}', encoding="utf-8")
    assert read_metadata(dataset) == {"source": "wikipedia"}


def test_read_metadata_is_optional(tmp_path: Path) -> None:
    dataset = tmp_path / "frequency.csv"
    write_dataset(dataset)
    assert read_metadata(dataset) == {}
