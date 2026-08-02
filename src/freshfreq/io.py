from __future__ import annotations

import gzip
from pathlib import Path
from typing import IO


def open_text(path: Path, mode: str = "rt") -> IO[str]:
    """Open UTF-8 text, transparently handling gzip files."""
    if "b" in mode:
        raise ValueError("open_text only supports text modes")
    if path.suffix == ".gz":
        return gzip.open(path, mode=mode, encoding="utf-8")
    return path.open(mode=mode, encoding="utf-8")

