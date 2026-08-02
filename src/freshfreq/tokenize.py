from __future__ import annotations

import re
import unicodedata

TOKEN_PATTERN = re.compile(r"[a-z]+(?:['’-][a-z]+)*", re.IGNORECASE)


def normalize_text(text: str) -> str:
    """Normalize Unicode, apostrophes, and case before tokenization."""
    normalized = unicodedata.normalize("NFKC", text)
    return normalized.replace("’", "'").casefold()


def tokenize(text: str) -> list[str]:
    """Extract normalized English surface-form tokens."""
    return TOKEN_PATTERN.findall(normalize_text(text))

