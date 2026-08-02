from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from freshfreq.dataset import lookup_csv, metadata_path, read_metadata, result_as_dict
from freshfreq.io import open_text
from freshfreq.sources.wikipedia import download_part, resolve_parts, write_manifest
from freshfreq.sources.wikipedia_extract import extract_wikipedia
from freshfreq.stats import count_documents


def count_command(
    input_path: Path,
    output_path: Path,
    source_name: str,
    snapshot: str | None,
) -> None:
    document_count = 0

    def documents():
        nonlocal document_count
        with open_text(input_path) as source:
            for line in source:
                document_count += 1
                yield line.rstrip("\n")

    records = count_documents(documents())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(
            [
                "term",
                "occurrence_count",
                "document_frequency",
                "frequency_per_million",
                "zipf_frequency",
            ]
        )
        for record in records:
            writer.writerow(
                [
                    record.term,
                    record.occurrence_count,
                    record.document_frequency,
                    f"{record.frequency_per_million:.6f}",
                    f"{record.zipf_frequency:.4f}",
                ]
            )

    print(f"wrote {len(records):,} terms to {output_path}")
    metadata = {
        "format_version": 1,
        "language": "en",
        "source": source_name,
        "snapshot": snapshot,
        "input": str(input_path),
        "generated_at": datetime.now(UTC).isoformat(),
        "document_count": document_count,
        "token_count": sum(record.occurrence_count for record in records),
        "term_count": len(records),
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
    count_parser.add_argument("input", type=Path, help="UTF-8 file; one document per line")
    count_parser.add_argument("--output", "-o", type=Path, required=True)
    count_parser.add_argument("--source", default="custom", help="corpus source identifier")
    count_parser.add_argument("--snapshot", help="source snapshot, such as 20260701")

    lookup_parser = subparsers.add_parser("lookup", help="look up one word in a frequency CSV")
    lookup_parser.add_argument("term", help="one word; phrase lookup is not available yet")
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
        "--input", type=Path, help="downloaded pages-articles .xml.bz2 part for extraction"
    )
    wikipedia_parser.add_argument(
        "--min-chars", type=int, default=100, help="minimum cleaned article length"
    )
    wikipedia_parser.add_argument(
        "--connections", type=int, default=4, help="parallel connections per downloaded file"
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "count":
        if not args.input.is_file():
            parser.error(
                f"input file does not exist: {args.input}\n"
                "Try the bundled example: examples/sample.txt"
            )
        count_command(args.input, args.output, args.source, args.snapshot)
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
            if args.input is None or not args.input.is_file():
                parser.error("wikipedia extract requires an existing --input .xml.bz2 file")
            if args.output.suffix != ".gz":
                parser.error("wikipedia extract --output must end in .gz")
            if args.min_chars < 1:
                parser.error("--min-chars must be at least 1")
            result = extract_wikipedia(args.input, args.output, args.min_chars)
            print(f"pages seen: {result.pages_seen:,}")
            print(f"documents written: {result.documents_written:,}")
            print(f"redirects skipped: {result.redirects_skipped:,}")
            print(f"non-articles skipped: {result.non_articles_skipped:,}")
            print(f"short documents skipped: {result.short_documents_skipped:,}")
            print(f"saved: {args.output}")
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
