from __future__ import annotations

import bz2
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
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


@dataclass(frozen=True, slots=True)
class ExtractedPart:
    input_path: Path
    output_path: Path
    result: ExtractionResult


@dataclass(frozen=True, slots=True)
class BatchExtractionResult:
    parts: tuple[ExtractedPart, ...]
    total: ExtractionResult
    manifest_path: Path


def clean_wikitext(source: str) -> str:
    """Remove MediaWiki markup and collapse the result to one physical line."""
    parsed = mwparserfromhell.parse(source)
    for link in parsed.filter_wikilinks(recursive=True):
        title = str(link.title).strip().casefold()
        if title.startswith(("file:", "image:", "category:")):
            link.title = ""
            link.text = ""
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
    temporary_path = output_path.with_name(f"{output_path.name}.part{output_path.suffix}")
    temporary_path.unlink(missing_ok=True)
    with bz2.open(input_path, mode="rb") as source, open_text(temporary_path, "wt") as output:
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

    temporary_path.replace(output_path)

    return ExtractionResult(
        pages_seen=pages_seen,
        documents_written=documents_written,
        redirects_skipped=redirects_skipped,
        non_articles_skipped=non_articles_skipped,
        short_documents_skipped=short_documents_skipped,
    )


def extracted_filename(input_path: Path) -> str:
    name = input_path.name
    for suffix in (".bz2", ".xml"):
        name = name.removesuffix(suffix)
    return f"{name}.txt.gz"


def _extract_part(arguments: tuple[Path, Path, int]) -> ExtractedPart:
    input_path, output_path, min_chars = arguments
    return ExtractedPart(
        input_path=input_path,
        output_path=output_path,
        result=extract_wikipedia(input_path, output_path, min_chars),
    )


def extract_wikipedia_parts(
    input_paths: list[Path],
    output_dir: Path,
    *,
    min_chars: int = 100,
    workers: int = 1,
) -> BatchExtractionResult:
    """Extract multiple dump parts and write an auditable batch manifest."""
    if not input_paths:
        raise ValueError("at least one input part is required")
    if workers < 1:
        raise ValueError("workers must be at least 1")
    output_dir.mkdir(parents=True, exist_ok=True)
    jobs = [
        (input_path, output_dir / extracted_filename(input_path), min_chars)
        for input_path in input_paths
    ]

    if workers == 1:
        parts = tuple(_extract_part(job) for job in jobs)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            parts = tuple(executor.map(_extract_part, jobs))

    total = ExtractionResult(
        pages_seen=sum(part.result.pages_seen for part in parts),
        documents_written=sum(part.result.documents_written for part in parts),
        redirects_skipped=sum(part.result.redirects_skipped for part in parts),
        non_articles_skipped=sum(part.result.non_articles_skipped for part in parts),
        short_documents_skipped=sum(part.result.short_documents_skipped for part in parts),
    )
    manifest_path = output_dir / "extraction-manifest.json"
    manifest = {
        "format_version": 1,
        "min_chars": min_chars,
        "workers": workers,
        "parts": [
            {
                "input": str(part.input_path),
                "output": str(part.output_path),
                **asdict(part.result),
            }
            for part in parts
        ],
        "total": asdict(total),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return BatchExtractionResult(parts, total, manifest_path)
