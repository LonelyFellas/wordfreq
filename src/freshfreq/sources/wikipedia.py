from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

BASE_URL = "https://dumps.wikimedia.org/enwiki"
SNAPSHOT_PATTERN = re.compile(r'href="(\d{8})/"')
ARTICLE_PART_PATTERN = re.compile(r"pages-articles-multistream\d+\.xml-p\d+p\d+\.bz2$")
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
MAX_DOWNLOAD_ATTEMPTS = 12


@dataclass(frozen=True, slots=True)
class DumpPart:
    snapshot: str
    filename: str
    url: str
    size: int
    sha1: str


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "freshfreq/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def discover_latest_snapshot(index_html: str | None = None) -> str:
    if index_html is None:
        index_html = fetch_bytes(f"{BASE_URL}/").decode("utf-8")
    snapshots = SNAPSHOT_PATTERN.findall(index_html)
    if not snapshots:
        raise RuntimeError("no completed English Wikipedia snapshots were found")
    return max(snapshots)


def load_dump_status(snapshot: str) -> dict[str, Any]:
    url = f"{BASE_URL}/{snapshot}/dumpstatus.json"
    return json.loads(fetch_bytes(url))


def select_article_parts(status: dict[str, Any], snapshot: str) -> list[DumpPart]:
    job = status.get("jobs", {}).get("articlesmultistreamdump", {})
    if job.get("status") != "done":
        raise RuntimeError(f"Wikipedia article dump is not complete for snapshot {snapshot}")

    selected = []
    for filename, metadata in job.get("files", {}).items():
        if not ARTICLE_PART_PATTERN.search(filename):
            continue
        selected.append(
            DumpPart(
                snapshot=snapshot,
                filename=filename,
                url=f"https://dumps.wikimedia.org{metadata['url']}",
                size=int(metadata["size"]),
                sha1=metadata["sha1"],
            )
        )
    if not selected:
        raise RuntimeError(f"Wikipedia article dump has no data parts for snapshot {snapshot}")
    return sorted(selected, key=lambda part: part.filename)


def resolve_parts(snapshot: str, limit: int | None = None) -> tuple[str, list[DumpPart]]:
    resolved = discover_latest_snapshot() if snapshot == "latest" else snapshot
    if not re.fullmatch(r"\d{8}", resolved):
        raise ValueError("snapshot must be 'latest' or YYYYMMDD")
    parts = select_article_parts(load_dump_status(resolved), resolved)
    return resolved, parts[:limit]


def write_manifest(destination: Path, snapshot: str, parts: list[DumpPart]) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "manifest.json"
    payload = {
        "source": "wikimedia-enwiki",
        "snapshot": snapshot,
        "parts": [asdict(part) for part in parts],
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def split_ranges(size: int, connections: int) -> list[tuple[int, int]]:
    """Split a byte length into inclusive ranges of nearly equal size."""
    if size < 1 or connections < 1:
        raise ValueError("size and connections must be positive")
    connections = min(size, connections)
    chunk_size = (size + connections - 1) // connections
    return [
        (start, min(start + chunk_size - 1, size - 1))
        for start in range(0, size, chunk_size)
    ]


def _retry_delay(error: Exception, attempt: int) -> float:
    if isinstance(error, urllib.error.HTTPError):
        retry_after = error.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return min(max(float(retry_after), 1.0), 300.0)
    return min(5.0 * 2**attempt, 300.0) + random.uniform(0.0, 1.0)


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code in RETRYABLE_HTTP_CODES
    return isinstance(error, (urllib.error.URLError, TimeoutError, OSError))


def _download_range(part: DumpPart, path: Path, start: int, end: int) -> None:
    expected_size = end - start + 1
    for attempt in range(MAX_DOWNLOAD_ATTEMPTS):
        existing_size = path.stat().st_size if path.exists() else 0
        if existing_size == expected_size:
            return
        if existing_size > expected_size:
            path.unlink()
            existing_size = 0

        request = urllib.request.Request(
            part.url,
            headers={
                "User-Agent": "freshfreq/0.1",
                "Range": f"bytes={start + existing_size}-{end}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 206:
                    raise RuntimeError(
                        f"server did not honor range request for {part.filename}"
                    )
                with path.open("ab" if existing_size else "wb") as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
        except Exception as error:
            if not _is_retryable(error) or attempt == MAX_DOWNLOAD_ATTEMPTS - 1:
                raise
            delay = _retry_delay(error, attempt)
            print(
                f"retrying {part.filename} range after {type(error).__name__} "
                f"in {delay:.1f}s (attempt {attempt + 2}/{MAX_DOWNLOAD_ATTEMPTS})",
                flush=True,
            )
            time.sleep(delay)
            continue

        actual_size = path.stat().st_size
        if actual_size == expected_size:
            return
        error = OSError(
            f"incomplete range for {part.filename}: expected {expected_size}, got {actual_size}"
        )
        if attempt == MAX_DOWNLOAD_ATTEMPTS - 1:
            raise error
        delay = _retry_delay(error, attempt)
        print(
            f"retrying incomplete range for {part.filename} in {delay:.1f}s "
            f"(attempt {attempt + 2}/{MAX_DOWNLOAD_ATTEMPTS})",
            flush=True,
        )
        time.sleep(delay)

    raise RuntimeError(f"download attempts exhausted for {part.filename}")


def download_part(part: DumpPart, destination: Path, connections: int = 4) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / part.filename
    if target.exists() and target.stat().st_size == part.size:
        return target

    temporary = target.with_suffix(target.suffix + ".part")
    ranges = split_ranges(part.size, 8)
    segment_paths = [
        temporary.with_name(f"{temporary.name}.segment-{index:02d}")
        for index in range(len(ranges))
    ]
    if temporary.exists() and not segment_paths[0].exists():
        first_range_size = ranges[0][1] - ranges[0][0] + 1
        if temporary.stat().st_size <= first_range_size:
            temporary.replace(segment_paths[0])
        else:
            temporary.unlink()

    with ThreadPoolExecutor(max_workers=min(connections, len(ranges))) as executor:
        futures = [
            executor.submit(_download_range, part, path, start, end)
            for path, (start, end) in zip(segment_paths, ranges, strict=True)
        ]
        for future in futures:
            future.result()

    with temporary.open("wb") as output:
        for segment_path in segment_paths:
            with segment_path.open("rb") as segment:
                shutil.copyfileobj(segment, output, length=1024 * 1024)

    if temporary.stat().st_size != part.size:
        raise RuntimeError(
            f"size mismatch for {part.filename}: expected {part.size}, "
            f"got {temporary.stat().st_size}"
        )
    digest = hashlib.sha1()
    with temporary.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != part.sha1:
        raise RuntimeError(f"SHA-1 mismatch for {part.filename}")
    temporary.replace(target)
    for segment_path in segment_paths:
        segment_path.unlink(missing_ok=True)
    return target
