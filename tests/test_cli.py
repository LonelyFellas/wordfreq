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
