from __future__ import annotations

import json
from pathlib import Path

from freshfreq.cli import count_command
from freshfreq.dataset import metadata_path


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
