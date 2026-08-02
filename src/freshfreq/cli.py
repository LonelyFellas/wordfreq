from __future__ import annotations

import argparse
import csv
from pathlib import Path

from freshfreq.stats import count_documents


def count_command(input_path: Path, output_path: Path) -> None:
    with input_path.open(encoding="utf-8") as source:
        records = count_documents(line.rstrip("\n") for line in source)

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="freshfreq")
    subparsers = parser.add_subparsers(dest="command", required=True)

    count_parser = subparsers.add_parser("count", help="count tokens in line-delimited text")
    count_parser.add_argument("input", type=Path, help="UTF-8 file; one document per line")
    count_parser.add_argument("--output", "-o", type=Path, required=True)
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
        count_command(args.input, args.output)


if __name__ == "__main__":
    main()
