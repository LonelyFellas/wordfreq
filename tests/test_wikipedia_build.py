from __future__ import annotations

import json
from pathlib import Path

from freshfreq.sources.wikipedia import DumpPart
from freshfreq.sources.wikipedia_build import (
    WikipediaBuildPlan,
    create_build_plan,
    extract_build_parts,
    frequency_build_matches,
    write_build_manifest,
)


def make_part(name: str, size: int = 100) -> DumpPart:
    return DumpPart("20260801", name, f"https://example.test/{name}", size, "abc")


def test_create_build_plan_resolves_paths_and_estimates_disk(
    tmp_path: Path, monkeypatch
) -> None:
    parts = [make_part("part1.xml.bz2", 100), make_part("part2.xml.bz2", 200)]
    monkeypatch.setattr(
        "freshfreq.sources.wikipedia_build.resolve_parts",
        lambda snapshot, limit: ("20260801", parts),
    )

    plan = create_build_plan("latest", None, tmp_path)

    assert plan.snapshot == "20260801"
    assert plan.download_bytes == 300
    assert plan.estimated_extracted_bytes == 180
    assert plan.estimated_peak_bytes == 840
    assert plan.output_path == tmp_path / "releases/wikipedia-20260801-frequency.csv"


def test_extract_build_parts_only_processes_missing_outputs(tmp_path: Path, monkeypatch) -> None:
    downloaded = [tmp_path / "part1.xml.bz2", tmp_path / "part2.xml.bz2"]
    extracted_dir = tmp_path / "processed"
    extracted_dir.mkdir()
    (extracted_dir / "part1.txt.gz").write_bytes(b"complete")
    calls: list[list[Path]] = []

    def fake_extract(inputs, output_dir, *, min_chars, workers):
        calls.append(inputs)
        for path in inputs:
            (output_dir / path.name.removesuffix(".xml.bz2")).with_suffix(".txt.gz").write_bytes(
                b"complete"
            )

    monkeypatch.setattr(
        "freshfreq.sources.wikipedia_build.extract_wikipedia_parts", fake_extract
    )
    plan = WikipediaBuildPlan(
        snapshot="20260801",
        parts=tuple(make_part(path.name) for path in downloaded),
        raw_dir=tmp_path,
        extracted_dir=extracted_dir,
        output_path=tmp_path / "release.csv",
        work_dir=tmp_path / "work",
        download_bytes=200,
        estimated_extracted_bytes=120,
        estimated_peak_bytes=560,
    )

    outputs = extract_build_parts(plan, downloaded, min_chars=100, workers=2)

    assert calls == [[downloaded[1]]]
    assert all(path.is_file() for path in outputs)


def test_write_build_manifest_records_stage_atomically(tmp_path: Path) -> None:
    part = make_part("part1.xml.bz2")
    plan = WikipediaBuildPlan(
        snapshot="20260801",
        parts=(part,),
        raw_dir=tmp_path / "raw",
        extracted_dir=tmp_path / "processed",
        output_path=tmp_path / "release.csv",
        work_dir=tmp_path / "work",
        download_bytes=100,
        estimated_extracted_bytes=60,
        estimated_peak_bytes=280,
    )

    manifest_path = write_build_manifest(
        plan,
        stage="extracting",
        downloaded=[tmp_path / part.filename],
        extracted=[],
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["stage"] == "extracting"
    assert payload["snapshot"] == "20260801"
    assert not manifest_path.with_suffix(manifest_path.suffix + ".part").exists()


def test_frequency_build_matches_requires_same_configuration(tmp_path: Path) -> None:
    extracted = [tmp_path / "part.txt.gz"]
    plan = WikipediaBuildPlan(
        snapshot="20260801",
        parts=(make_part("part.xml.bz2"),),
        raw_dir=tmp_path / "raw",
        extracted_dir=tmp_path / "processed",
        output_path=tmp_path / "release.csv",
        work_dir=tmp_path / "work",
        download_bytes=100,
        estimated_extracted_bytes=60,
        estimated_peak_bytes=280,
    )
    plan.output_path.write_text("term,occurrence_count\n", encoding="utf-8")
    plan.output_path.with_suffix(".csv.metadata.json").write_text(
        json.dumps(
            {
                "source": "wikipedia",
                "snapshot": "20260801",
                "max_ngram": 2,
                "inputs": [str(extracted[0])],
            }
        ),
        encoding="utf-8",
    )

    assert frequency_build_matches(plan, extracted, 2)
    assert not frequency_build_matches(plan, extracted, 1)
