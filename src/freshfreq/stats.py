from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from freshfreq.tokenize import tokenize


@dataclass(frozen=True, slots=True)
class FrequencyRecord:
    term: str
    occurrence_count: int
    document_frequency: int
    frequency_per_million: float
    zipf_frequency: float


def count_documents(documents: Iterable[str]) -> list[FrequencyRecord]:
    """Count surface forms while retaining cross-document dispersion."""
    occurrences: Counter[str] = Counter()
    document_frequency: Counter[str] = Counter()
    total_tokens = 0

    for document in documents:
        tokens = tokenize(document)
        occurrences.update(tokens)
        document_frequency.update(set(tokens))
        total_tokens += len(tokens)

    if total_tokens == 0:
        return []

    records = []
    for term, count in occurrences.most_common():
        probability = count / total_tokens
        records.append(
            FrequencyRecord(
                term=term,
                occurrence_count=count,
                document_frequency=document_frequency[term],
                frequency_per_million=probability * 1_000_000,
                zipf_frequency=math.log10(probability * 1_000_000_000),
            )
        )
    return records
