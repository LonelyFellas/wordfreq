# freshfreq

[English](README.md) | [简体中文](README.zh-CN.md)

`freshfreq` is a reproducible, source-aware pipeline for building and querying modern English
word-frequency datasets.

It keeps corpus domains and time periods separate instead of mixing Wikipedia, web, news, and
spoken language into a single unexplained score. The current release implements an end-to-end
English Wikipedia pipeline.

## Features

- Discover completed English Wikipedia snapshots.
- Plan and download selected multistream dump parts.
- Resume interrupted downloads and verify file size and SHA-1.
- Stream `.xml.bz2` files without loading an entire dump into memory.
- Keep main-namespace articles and filter redirects, non-articles, and short pages.
- Remove MediaWiki formatting, image links, and category links.
- Write one cleaned document per line in a gzip-compressed corpus.
- Count unigram, bigram, and trigram occurrences and cross-document frequency.
- Calculate frequency per million tokens and Zipf frequency.
- Produce a versioned JSON metadata sidecar for every frequency CSV.
- Query a word or phrase in text or JSON format.

## Requirements

- Python 3.11 or later
- [`uv`](https://docs.astral.sh/uv/)
- Enough disk space for the selected Wikimedia dump parts and extracted text

## Installation

```bash
uv sync
uv run freshfreq --help
```

Run the quality checks:

```bash
uv run pytest
uv run ruff check .
```

## Wikipedia workflow

### 1. Plan a download

This resolves the latest completed snapshot and prints the selected files without downloading
them:

```bash
uv run freshfreq wikipedia plan --snapshot latest --parts 1
```

Use an explicit snapshot for a reproducible build:

```bash
uv run freshfreq wikipedia plan --snapshot 20260701 --parts 1
```

### 2. Download dump parts

```bash
uv run freshfreq wikipedia download \
  --snapshot 20260701 \
  --parts 1 \
  --connections 4
```

Each file is split into eight byte ranges. Up to four ranges are downloaded concurrently by
default. Partial ranges are retained for a later resume. Completed files are checked against the
size and SHA-1 published by Wikimedia.

Downloads are stored under:

```text
data/raw/wikipedia/<snapshot>/
```

The directory also contains `manifest.json` with the source URL, size, checksum, and snapshot.

### 3. Extract clean article text

```bash
uv run freshfreq wikipedia extract \
  --input data/raw/wikipedia/20260701/enwiki-20260701-pages-articles-multistream1.xml-p1p41242.bz2 \
  --output data/processed/wikipedia-20260701-part1.txt.gz
```

The output is UTF-8 text compressed with gzip. Each physical line represents one independent
Wikipedia article, allowing document frequency to be calculated correctly.

### 4. Build a frequency dataset

```bash
uv run freshfreq count \
  data/processed/wikipedia-20260701-part1.txt.gz \
  --output data/processed/wikipedia-20260701-part1-frequency.csv \
  --source wikipedia \
  --snapshot 20260701
```

This produces two files:

```text
wikipedia-20260701-part1-frequency.csv
wikipedia-20260701-part1-frequency.csv.metadata.json
```

CSV columns:

```text
term,occurrence_count,document_frequency,frequency_per_million,zipf_frequency
```

The metadata sidecar records the source, snapshot, generation time, document count, token count,
term count, frequency unit, and Zipf definition.

### 5. Query a word

```bash
uv run freshfreq lookup actually \
  --dataset data/processed/wikipedia-20260701-part1-frequency.csv
```

Machine-readable output:

```bash
uv run freshfreq lookup actually \
  --dataset data/processed/wikipedia-20260701-part1-frequency.csv \
  --json
```

### Count and query phrases

Unigram counting remains the default. Use `--max-ngram 2` for words and bigrams, or
`--max-ngram 3` to also include trigrams:

```bash
uv run freshfreq count examples/sample.txt \
  --output data/processed/sample-ngrams.csv \
  --source custom \
  --max-ngram 3

uv run freshfreq lookup "trade and craft" \
  --dataset data/processed/sample-ngrams.csv
```

N-grams are contiguous normalized tokens within one document. Phrase frequency uses the total
corpus token count as its denominator, so word and phrase Zipf values remain comparable. The
selected maximum n-gram size is recorded in the metadata sidecar.

## Count a custom corpus

Input must be UTF-8 text with one document per line:

```bash
uv run freshfreq count examples/sample.txt \
  --output data/processed/sample-frequency.csv \
  --source custom
```

## Metrics

`occurrence_count` is the number of times a surface form occurs. `document_frequency` is the
number of independent documents containing it at least once.

Frequency per million tokens is:

```text
occurrence_count / total_token_count * 1,000,000
```

Zipf frequency is:

```text
log10(occurrences per billion tokens)
```

A Zipf difference of `1.0` represents an approximate tenfold difference in frequency.

## Current limitations

- Only English surface forms are counted; inflections are not merged into lemmas.
- N-grams are limited to contiguous phrases of at most three tokens.
- Counting bigrams and trigrams requires substantially more memory and output space.
- Wikipedia represents encyclopedic written English, not everyday spoken English.
- One dump part is a sample of a snapshot, not the complete English Wikipedia.
- Additional domains must be counted independently before a defensible combined score is built.

## Project structure

```text
configs/          Dataset and release configurations
data/raw/         Downloaded source corpora; ignored by Git
data/processed/   Extracted corpora and statistics; ignored by Git
data/releases/    Publishable release artifacts; ignored by Git
examples/         Small local examples
src/freshfreq/    CLI, source adapters, extraction, tokenization, and statistics
tests/            Automated tests
```

## Data and licensing

The project code and generated data are separate licensing concerns. Before publishing a dataset,
review every upstream source's attribution, redistribution, and derived-statistics terms. Raw
corpora and generated artifacts are intentionally excluded from Git.

Do not describe a Wikipedia-only result as general or spoken-English frequency. Always expose the
source, snapshot, corpus size, and methodology with the result.
