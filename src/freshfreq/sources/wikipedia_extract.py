from __future__ import annotations

import bz2
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import mwparserfromhell

from freshfreq.io import open_text

WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class WikipediaDocument:
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    pages_seen: int
    documents_written: int
    redirects_skipped: int
    non_articles_skipped: int
    short_documents_skipped: int


def clean_wikitext(source: str) -> str:
    """Remove MediaWiki markup and collapse the result to one physical line."""
    parsed = mwparserfromhell.parse(source)
    for link in parsed.filter_wikilinks(recursive=True):
        title = str(link.title).strip().casefold()
        if title.startswith(("file:", "image:", "category:")):
            parsed.remove(link, recursive=True)
    plain = parsed.strip_code(normalize=True, collapse=True)
    return WHITESPACE_PATTERN.sub(" ", plain).strip()


def iter_wikipedia_documents(path: Path, min_chars: int = 100) -> Iterator[WikipediaDocument]:
    """Stream article documents from a Wikimedia pages-articles XML bz2 part."""
    with bz2.open(path, mode="rb") as source:
        for _, element in ET.iterparse(source, events=("end",)):
            if not element.tag.endswith("}page") and element.tag != "page":
                continue

            namespace = element.findtext("{*}ns")
            redirect = element.find("{*}redirect")
            title = element.findtext("{*}title") or ""
            raw_text = element.findtext("{*}revision/{*}text") or ""

            if namespace == "0" and redirect is None:
                cleaned = clean_wikitext(raw_text)
                if len(cleaned) >= min_chars:
                    yield WikipediaDocument(title=title, text=cleaned)
            element.clear()


def extract_wikipedia(
    input_path: Path, output_path: Path, min_chars: int = 100
) -> ExtractionResult:
    """Extract line-delimited article text and return auditable counters."""
    pages_seen = 0
    documents_written = 0
    redirects_skipped = 0
    non_articles_skipped = 0
    short_documents_skipped = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with bz2.open(input_path, mode="rb") as source, open_text(output_path, "wt") as output:
        for _, element in ET.iterparse(source, events=("end",)):
            if not element.tag.endswith("}page") and element.tag != "page":
                continue
            pages_seen += 1
            namespace = element.findtext("{*}ns")
            redirect = element.find("{*}redirect")
            raw_text = element.findtext("{*}revision/{*}text") or ""

            if namespace != "0":
                non_articles_skipped += 1
            elif redirect is not None:
                redirects_skipped += 1
            else:
                cleaned = clean_wikitext(raw_text)
                if len(cleaned) < min_chars:
                    short_documents_skipped += 1
                else:
                    output.write(cleaned)
                    output.write("\n")
                    documents_written += 1
            element.clear()

    return ExtractionResult(
        pages_seen=pages_seen,
        documents_written=documents_written,
        redirects_skipped=redirects_skipped,
        non_articles_skipped=non_articles_skipped,
        short_documents_skipped=short_documents_skipped,
    )
