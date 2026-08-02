from __future__ import annotations

import bz2
import gzip
from pathlib import Path

from freshfreq.io import open_text
from freshfreq.sources.wikipedia_extract import (
    clean_wikitext,
    extract_wikipedia,
    extract_wikipedia_parts,
)
from freshfreq.stats import count_documents

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Fresh frequency</title><ns>0</ns>
    <revision><text>'''Fresh frequency''' is a [[word frequency]] project. {{note|Ignore me}}</text></revision>
  </page>
  <page>
    <title>Redirected</title><ns>0</ns><redirect title="Target" />
    <revision><text>#REDIRECT [[Target]]</text></revision>
  </page>
  <page>
    <title>Talk:Fresh frequency</title><ns>1</ns>
    <revision><text>This discussion is not article content.</text></revision>
  </page>
</mediawiki>
"""


def test_clean_wikitext_removes_links_and_formatting() -> None:
    assert clean_wikitext("'''Word''' [[frequency]]") == "Word frequency"


def test_clean_wikitext_removes_file_and_category_links() -> None:
    source = (
        "Before {{box|[[File:Map.png|thumb|A noisy caption]]}} "
        "after [[Category:Examples]]"
    )
    assert clean_wikitext(source) == "Before after"


def test_extract_wikipedia_filters_redirects_and_namespaces(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.xml.bz2"
    output_path = tmp_path / "sample.txt.gz"
    input_path.write_bytes(bz2.compress(SAMPLE_XML.encode()))

    result = extract_wikipedia(input_path, output_path, min_chars=10)

    assert result.pages_seen == 3
    assert result.documents_written == 1
    assert result.redirects_skipped == 1
    assert result.non_articles_skipped == 1
    with gzip.open(output_path, "rt", encoding="utf-8") as output:
        text = output.read()
    assert "Fresh frequency is a word frequency project." in text
    assert "Redirected" not in text

    with open_text(output_path) as corpus:
        frequencies = {record.term: record for record in count_documents(corpus)}
    assert frequencies["frequency"].occurrence_count == 2


def test_extract_wikipedia_parts_writes_outputs_and_manifest(tmp_path: Path) -> None:
    inputs = [tmp_path / "part1.xml.bz2", tmp_path / "part2.xml.bz2"]
    for input_path in inputs:
        input_path.write_bytes(bz2.compress(SAMPLE_XML.encode()))

    batch = extract_wikipedia_parts(inputs, tmp_path / "extracted", min_chars=10, workers=2)

    assert len(batch.parts) == 2
    assert batch.total.pages_seen == 6
    assert batch.total.documents_written == 2
    assert batch.manifest_path.is_file()
    assert [part.output_path.name for part in batch.parts] == [
        "part1.txt.gz",
        "part2.txt.gz",
    ]
    assert all(part.output_path.is_file() for part in batch.parts)
