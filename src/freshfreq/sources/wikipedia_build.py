from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from freshfreq.dataset import metadata_path, read_metadata
from freshfreq.sources.wikipedia import DumpPart, download_part, resolve_parts, write_manifest
from freshfreq.sources.wikipedia_extract import extract_wikipedia_parts, extracted_filename


@dataclass(frozen=True, slots=True)
class WikipediaBuildPlan:
    snapshot: str
    parts: tuple[DumpPart, ...]
    raw_dir: Path
    extracted_dir: Path
    output_path: Path
    work_dir: Path
    download_bytes: int
    estimated_extracted_bytes: int
    estimated_peak_bytes: int

    def estimated_streaming_peak_bytes(self, max_ngram: int) -> int:
        """Return a conservative heuristic for the persistent DB and one raw part."""
        largest_part = max((part.size for part in self.parts), default=0)
        unigram_database = max(10_000_000_000, int(self.download_bytes * 0.4))
        ngram_multiplier = {1: 1.0, 2: 2.5, 3: 6.0}[max_ngram]
        return largest_part * 2 + int(unigram_database * ngram_multiplier)


def create_build_plan(
    snapshot: str,
    part_limit: int | None,
    data_dir: Path,
    output_path: Path | None = None,
    work_dir: Path | None = None,
) -> WikipediaBuildPlan:
    resolved, parts = resolve_parts(snapshot, part_limit)
    download_bytes = sum(part.size for part in parts)
    estimated_extracted_bytes = int(download_bytes * 0.6)
    return WikipediaBuildPlan(
        snapshot=resolved,
        parts=tuple(parts),
        raw_dir=data_dir / "raw" / "wikipedia" / resolved,
        extracted_dir=data_dir / "processed" / f"wikipedia-{resolved}",
        output_path=output_path
        or data_dir / "releases" / f"wikipedia-{resolved}-frequency.csv",
        work_dir=work_dir or data_dir / "work",
        download_bytes=download_bytes,
        estimated_extracted_bytes=estimated_extracted_bytes,
        estimated_peak_bytes=download_bytes + estimated_extracted_bytes * 3,
    )


def write_build_manifest(
    plan: WikipediaBuildPlan,
    *,
    stage: str,
    downloaded: list[Path],
    extracted: list[Path],
    details: dict[str, object] | None = None,
) -> Path:
    manifest_path = plan.output_path.with_suffix(".build-manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 1,
        "source": "wikimedia-enwiki",
        "snapshot": plan.snapshot,
        "updated_at": datetime.now(UTC).isoformat(),
        "stage": stage,
        "parts": [asdict(part) for part in plan.parts],
        "paths": {
            "raw_dir": str(plan.raw_dir),
            "extracted_dir": str(plan.extracted_dir),
            "output": str(plan.output_path),
            "work_dir": str(plan.work_dir),
        },
        "downloaded": [str(path) for path in downloaded],
        "extracted": [str(path) for path in extracted],
        "frequency_metadata": str(metadata_path(plan.output_path)),
    }
    if details:
        payload.update(details)
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest_path


def download_build_parts(plan: WikipediaBuildPlan, connections: int) -> list[Path]:
    write_manifest(plan.raw_dir, plan.snapshot, list(plan.parts))
    return [download_part(part, plan.raw_dir, connections) for part in plan.parts]


def extract_build_parts(
    plan: WikipediaBuildPlan,
    downloaded: list[Path],
    *,
    min_chars: int,
    workers: int,
) -> list[Path]:
    outputs = [plan.extracted_dir / extracted_filename(path) for path in downloaded]
    missing_inputs = [
        input_path
        for input_path, output_path in zip(downloaded, outputs, strict=True)
        if not output_path.is_file()
    ]
    if missing_inputs:
        extract_wikipedia_parts(
            missing_inputs,
            plan.extracted_dir,
            min_chars=min_chars,
            workers=workers,
        )
    return outputs


def frequency_build_matches(
    plan: WikipediaBuildPlan, extracted: list[Path], max_ngram: int
) -> bool:
    if not plan.output_path.is_file():
        return False
    metadata = read_metadata(plan.output_path)
    return (
        metadata.get("source") == "wikipedia"
        and metadata.get("snapshot") == plan.snapshot
        and metadata.get("max_ngram") == max_ngram
        and metadata.get("inputs") == [str(path) for path in extracted]
    )
