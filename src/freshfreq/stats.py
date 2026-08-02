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


def iter_ngrams(tokens: list[str], max_ngram: int) -> Iterable[str]:
    """Yield contiguous n-grams, starting with unigrams."""
    for size in range(1, max_ngram + 1):
        for start in range(len(tokens) - size + 1):
            yield " ".join(tokens[start : start + size])


def count_documents(
    documents: Iterable[str], max_ngram: int = 1
) -> list[FrequencyRecord]:
    """Count contiguous surface-form n-grams and document dispersion."""
    if max_ngram < 1:
        raise ValueError("max_ngram must be at least 1")

    occurrences: Counter[str] = Counter()
    document_frequency: Counter[str] = Counter()
    total_tokens = 0

    for document in documents:
        tokens = tokenize(document)
        terms = list(iter_ngrams(tokens, max_ngram))
        occurrences.update(terms)
        document_frequency.update(set(terms))
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
