from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from freshfreq.dataset import lookup_csv, metadata_path, read_metadata, result_as_dict
from freshfreq.external_count import count_documents_to_csv
from freshfreq.io import open_text
from freshfreq.sources.wikipedia import download_part, resolve_parts, write_manifest
from freshfreq.sources.wikipedia_extract import extract_wikipedia, extract_wikipedia_parts


def count_command(
    input_paths: Path | Sequence[Path],
    output_path: Path,
    source_name: str,
    snapshot: str | None,
    max_ngram: int,
    chunk_documents: int = 5_000,
    work_dir: Path | None = None,
) -> None:
    paths = [input_paths] if isinstance(input_paths, Path) else list(input_paths)

    def documents():
        for input_path in paths:
            with open_text(input_path) as source:
                for line in source:
                    yield line.rstrip("\n")

    summary = count_documents_to_csv(
        documents(),
        output_path,
        max_ngram=max_ngram,
        chunk_documents=chunk_documents,
        work_dir=work_dir,
        on_chunk=lambda chunk, docs: print(f"merged chunk {chunk:,}: {docs:,} documents"),
    )

    print(f"wrote {summary.term_count:,} terms to {output_path}")
    metadata = {
        "format_version": 1,
        "language": "en",
        "source": source_name,
        "snapshot": snapshot,
        "input": str(paths[0]) if len(paths) == 1 else None,
        "inputs": [str(path) for path in paths],
        "input_count": len(paths),
        "generated_at": datetime.now(UTC).isoformat(),
        "document_count": summary.document_count,
        "token_count": summary.token_count,
        "term_count": summary.term_count,
        "max_ngram": max_ngram,
        "count_backend": "sqlite_chunked",
        "chunk_documents": chunk_documents,
        "chunk_count": summary.chunk_count,
        "frequency_unit": "per_million_tokens",
        "zipf_definition": "log10(occurrences_per_billion_tokens)",
    }
    sidecar = metadata_path(output_path)
    sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"wrote metadata to {sidecar}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="freshfreq")
    subparsers = parser.add_subparsers(dest="command", required=True)

    count_parser = subparsers.add_parser("count", help="count tokens in line-delimited text")
    count_parser.add_argument(
        "input",
        type=Path,
        nargs="+",
        help="one or more UTF-8 files; one document per line",
    )
    count_parser.add_argument("--output", "-o", type=Path, required=True)
    count_parser.add_argument("--source", default="custom", help="corpus source identifier")
    count_parser.add_argument("--snapshot", help="source snapshot, such as 20260701")
    count_parser.add_argument(
        "--max-ngram",
        type=int,
        choices=range(1, 4),
        default=1,
        metavar="N",
        help="include contiguous n-grams up to N (1-3; default: 1)",
    )
    count_parser.add_argument(
        "--chunk-documents",
        type=int,
        default=5_000,
        metavar="N",
        help="documents per in-memory chunk (default: 5000)",
    )
    count_parser.add_argument(
        "--work-dir",
        type=Path,
        help="directory for temporary on-disk counts (default: system temp)",
    )

    lookup_parser = subparsers.add_parser("lookup", help="look up a word or phrase in a CSV")
    lookup_parser.add_argument("term", help="word or contiguous phrase")
    lookup_parser.add_argument("--dataset", type=Path, required=True)
    lookup_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    wikipedia_parser = subparsers.add_parser(
        "wikipedia", help="plan or download an English Wikipedia dump snapshot"
    )
    wikipedia_parser.add_argument(
        "action",
        choices=("plan", "download", "extract"),
        help="show the plan, fetch selected parts, or extract an existing part",
    )
    wikipedia_parser.add_argument("--snapshot", default="latest", help="latest or YYYYMMDD")
    wikipedia_parser.add_argument(
        "--parts", type=int, default=1, help="number of article dump parts to select"
    )
    wikipedia_parser.add_argument(
        "--output", type=Path, default=Path("data/raw/wikipedia"), help="download directory"
    )
    wikipedia_parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        help="one or more downloaded pages-articles .xml.bz2 parts for extraction",
    )
    wikipedia_parser.add_argument(
        "--min-chars", type=int, default=100, help="minimum cleaned article length"
    )
    wikipedia_parser.add_argument(
        "--connections", type=int, default=4, help="parallel connections per downloaded file"
    )
    wikipedia_parser.add_argument(
        "--workers", type=int, default=1, help="parallel extraction workers (default: 1)"
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "count":
        missing = [path for path in args.input if not path.is_file()]
        if missing:
            parser.error(
                f"input file does not exist: {missing[0]}\n"
                "Try the bundled example: examples/sample.txt"
            )
        if args.chunk_documents < 1:
            parser.error("--chunk-documents must be at least 1")
        count_command(
            args.input,
            args.output,
            args.source,
            args.snapshot,
            args.max_ngram,
            args.chunk_documents,
            args.work_dir,
        )
    elif args.command == "lookup":
        if not args.dataset.is_file():
            parser.error(f"dataset file does not exist: {args.dataset}")
        try:
            result = lookup_csv(args.dataset, args.term)
        except ValueError as error:
            parser.error(str(error))
        if result is None:
            print(f"term not found: {args.term.casefold()}")
            return
        metadata = read_metadata(args.dataset)
        if args.json:
            print(json.dumps({"frequency": result_as_dict(result), "dataset": metadata}, indent=2))
            return
        print(f"term: {result.term}")
        print(f"occurrences: {result.occurrence_count:,}")
        print(f"documents: {result.document_frequency:,}")
        print(f"per million tokens: {result.frequency_per_million:.4f}")
        print(f"Zipf frequency: {result.zipf_frequency:.4f}")
        if metadata:
            print(f"source: {metadata.get('source', 'unknown')}")
            print(f"snapshot: {metadata.get('snapshot') or 'unknown'}")
            print(f"corpus tokens: {metadata.get('token_count', 0):,}")
    elif args.command == "wikipedia":
        if args.action == "extract":
            if not args.input:
                parser.error("wikipedia extract requires one or more --input .xml.bz2 files")
            missing = [path for path in args.input if not path.is_file()]
            if missing:
                parser.error(f"input file does not exist: {missing[0]}")
            if args.min_chars < 1:
                parser.error("--min-chars must be at least 1")
            if args.workers < 1:
                parser.error("--workers must be at least 1")
            if len(args.input) == 1 and args.output.suffix == ".gz":
                result = extract_wikipedia(args.input[0], args.output, args.min_chars)
                print(f"pages seen: {result.pages_seen:,}")
                print(f"documents written: {result.documents_written:,}")
                print(f"redirects skipped: {result.redirects_skipped:,}")
                print(f"non-articles skipped: {result.non_articles_skipped:,}")
                print(f"short documents skipped: {result.short_documents_skipped:,}")
                print(f"saved: {args.output}")
                return
            batch = extract_wikipedia_parts(
                args.input,
                args.output,
                min_chars=args.min_chars,
                workers=args.workers,
            )
            result = batch.total
            print(f"pages seen: {result.pages_seen:,}")
            print(f"documents written: {result.documents_written:,}")
            print(f"redirects skipped: {result.redirects_skipped:,}")
            print(f"non-articles skipped: {result.non_articles_skipped:,}")
            print(f"short documents skipped: {result.short_documents_skipped:,}")
            print(f"parts extracted: {len(batch.parts):,}")
            print(f"manifest: {batch.manifest_path}")
            return
        if args.parts < 1:
            parser.error("--parts must be at least 1")
        if args.connections < 1 or args.connections > 8:
            parser.error("--connections must be between 1 and 8")
        snapshot, parts = resolve_parts(args.snapshot, args.parts)
        total_size = sum(part.size for part in parts)
        print(f"snapshot: {snapshot}")
        print(f"selected parts: {len(parts)}")
        print(f"download size: {total_size / 1_000_000_000:.2f} GB")
        for part in parts:
            print(f"- {part.filename} ({part.size / 1_000_000:.1f} MB)")
        if args.action == "download":
            target_dir = args.output / snapshot
            manifest = write_manifest(target_dir, snapshot, parts)
            print(f"manifest: {manifest}")
            for index, part in enumerate(parts, start=1):
                print(f"downloading {index}/{len(parts)}: {part.filename}")
                print(f"saved: {download_part(part, target_dir, args.connections)}")


if __name__ == "__main__":
    main()
