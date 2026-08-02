import io
import urllib.error
from pathlib import Path

import pytest

from freshfreq.sources.wikipedia import (
    DumpPart,
    _download_range,
    discover_latest_snapshot,
    select_article_parts,
    split_ranges,
)


class RangeResponse(io.BytesIO):
    status = 206


def test_discover_latest_snapshot_ignores_latest_alias() -> None:
    html = '<a href="20260501/">old</a><a href="20260701/">new</a><a href="latest/">x</a>'
    assert discover_latest_snapshot(html) == "20260701"


def test_select_article_parts_filters_indexes_and_combined_files() -> None:
    filename = "enwiki-20260701-pages-articles-multistream1.xml-p1p41242.bz2"
    status = {
        "jobs": {
            "articlesmultistreamdump": {
                "status": "done",
                "files": {
                    filename: {
                        "size": 123,
                        "url": f"/enwiki/20260701/{filename}",
                        "sha1": "abc",
                    },
                    "enwiki-20260701-pages-articles-multistream-index.txt.bz2": {
                        "size": 10,
                        "url": "/ignored",
                        "sha1": "def",
                    },
                },
            }
        }
    }
    parts = select_article_parts(status, "20260701")
    assert [part.filename for part in parts] == [filename]
    assert parts[0].size == 123


def test_select_article_parts_rejects_incomplete_dump() -> None:
    status = {"jobs": {"articlesmultistreamdump": {"status": "running", "files": {}}}}
    with pytest.raises(RuntimeError, match="not complete"):
        select_article_parts(status, "20260801")


def test_split_ranges_covers_file_without_gaps() -> None:
    assert split_ranges(10, 3) == [(0, 3), (4, 7), (8, 9)]


def test_download_range_retries_429_and_resumes(tmp_path: Path, monkeypatch) -> None:
    retry = urllib.error.HTTPError(
        "https://example.test/part", 429, "limited", {"Retry-After": "1"}, None
    )
    responses = iter([retry, RangeResponse(b"data")])
    sleeps: list[float] = []

    def fake_urlopen(request, timeout):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("freshfreq.sources.wikipedia.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("freshfreq.sources.wikipedia.time.sleep", sleeps.append)
    part = DumpPart("20260801", "part.xml.bz2", "https://example.test/part", 4, "abc")
    output = tmp_path / "segment"

    _download_range(part, output, 0, 3)

    assert output.read_bytes() == b"data"
    assert sleeps == [1.0]
