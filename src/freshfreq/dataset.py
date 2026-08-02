from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from freshfreq.tokenize import tokenize


@dataclass(frozen=True, slots=True)
class LookupResult:
    term: str
    occurrence_count: int
    document_frequency: int
    frequency_per_million: float
    zipf_frequency: float


def metadata_path(dataset_path: Path) -> Path:
    return dataset_path.with_suffix(dataset_path.suffix + ".metadata.json")


def read_metadata(dataset_path: Path) -> dict[str, Any]:
    path = metadata_path(dataset_path)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def lookup_csv(dataset_path: Path, query: str) -> LookupResult | None:
    tokens = tokenize(query)
    if not tokens:
        raise ValueError("lookup requires at least one English word")
    normalized = " ".join(tokens)

    with dataset_path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            if row["term"] == normalized:
                return LookupResult(
                    term=normalized,
                    occurrence_count=int(row["occurrence_count"]),
                    document_frequency=int(row["document_frequency"]),
                    frequency_per_million=float(row["frequency_per_million"]),
                    zipf_frequency=float(row["zipf_frequency"]),
                )
    return None


def result_as_dict(result: LookupResult) -> dict[str, object]:
    return asdict(result)
