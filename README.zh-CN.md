# freshfreq

[English](README.md) | [简体中文](README.zh-CN.md)

`freshfreq` 是一个可复现、保留数据来源信息的现代英语词频构建与查询工具。

项目不会把 Wikipedia、网页、新闻和口语直接混合成一个无法解释的分数，而是分别保存
语料领域和时间范围。当前版本已经实现英文 Wikipedia 的端到端处理流程。

## 功能

- 发现已经完成的英文 Wikipedia 快照；
- 规划并下载指定数量的 multistream 分块；
- 支持断点续传，并校验文件大小和 SHA-1；
- 流式读取 `.xml.bz2`，不需要把整个 dump 装入内存；
- 只保留主命名空间文章，过滤重定向、非正文和过短页面；
- 清除 MediaWiki 格式、图片链接和分类链接；
- 输出 gzip 压缩语料，每行一篇独立文章；
- 统计 unigram、bigram、trigram 的出现次数和跨文档覆盖数；
- 计算每百万 token 频率和 Zipf 词频；
- 为每份词频 CSV 生成版本化 JSON 元数据；
- 以文本或 JSON 格式查询单词或短语。

## 环境要求

- Python 3.11 或更高版本；
- [`uv`](https://docs.astral.sh/uv/)；
- 足够存放 Wikipedia 分块和提取文本的磁盘空间。

## 安装

```bash
uv sync
uv run freshfreq --help
```

运行质量检查：

```bash
uv run pytest
uv run ruff check .
```

## Wikipedia 完整流程

### 1. 查看下载计划

解析最新完成的快照并显示文件，但不执行下载：

```bash
uv run freshfreq wikipedia plan --snapshot latest --parts 1
```

为了保证构建可复现，正式构建应指定快照：

```bash
uv run freshfreq wikipedia plan --snapshot 20260701 --parts 1
```

### 2. 下载分块

```bash
uv run freshfreq wikipedia download \
  --snapshot 20260701 \
  --parts 1 \
  --connections 4
```

每个文件被划分为八个字节区间，默认最多同时下载四段。未完成的分段会保留，后续运行可以
继续下载。完成后会使用 Wikimedia 公布的文件大小和 SHA-1 进行校验。

文件保存在：

```text
data/raw/wikipedia/<snapshot>/
```

目录中的 `manifest.json` 记录来源 URL、大小、校验值和快照。

### 3. 提取和清洗文章正文

```bash
uv run freshfreq wikipedia extract \
  --input data/raw/wikipedia/20260701/enwiki-20260701-pages-articles-multistream1.xml-p1p41242.bz2 \
  --output data/processed/wikipedia-20260701-part1.txt.gz
```

输出是 gzip 压缩的 UTF-8 文本，每一物理行代表一篇独立 Wikipedia 文章，从而可以正确
计算文档覆盖数。

### 4. 构建词频数据集

```bash
uv run freshfreq count \
  data/processed/wikipedia-20260701-part1.txt.gz \
  --output data/processed/wikipedia-20260701-part1-frequency.csv \
  --source wikipedia \
  --snapshot 20260701
```

该命令生成两个文件：

```text
wikipedia-20260701-part1-frequency.csv
wikipedia-20260701-part1-frequency.csv.metadata.json
```

CSV 字段：

```text
term,occurrence_count,document_frequency,frequency_per_million,zipf_frequency
```

元数据文件记录来源、快照、生成时间、文档数、token 数、词条数、频率单位和 Zipf 定义。

### 5. 查询单词

```bash
uv run freshfreq lookup actually \
  --dataset data/processed/wikipedia-20260701-part1-frequency.csv
```

机器可读的 JSON 输出：

```bash
uv run freshfreq lookup actually \
  --dataset data/processed/wikipedia-20260701-part1-frequency.csv \
  --json
```

### 统计和查询短语

默认仍然只统计 unigram。使用 `--max-ngram 2` 同时统计单词与二元短语；使用
`--max-ngram 3` 还会加入三元短语：

```bash
uv run freshfreq count examples/sample.txt \
  --output data/processed/sample-ngrams.csv \
  --source custom \
  --max-ngram 3

uv run freshfreq lookup "trade and craft" \
  --dataset data/processed/sample-ngrams.csv
```

n-gram 是同一篇文档内连续出现并经过归一化的 token。短语频率仍以整个语料的 token 总数
作为分母，因此单词和短语的 Zipf 值可以横向比较。所选最大 n-gram 长度会写入元数据文件。

## 统计自定义语料

输入必须是 UTF-8 文本，每行代表一篇独立文档：

```bash
uv run freshfreq count examples/sample.txt \
  --output data/processed/sample-frequency.csv \
  --source custom
```

## 指标说明

`occurrence_count` 是表面词形的总出现次数；`document_frequency` 是至少包含一次该词的独立
文档数量。

每百万 token 频率：

```text
occurrence_count / total_token_count * 1,000,000
```

Zipf 词频：

```text
log10（每十亿 token 的预计出现次数）
```

Zipf 相差 `1.0`，代表频率大约相差十倍。

## 当前限制

- 当前只统计英文表面词形，不会把不同变形合并为 lemma；
- n-gram 目前仅支持最多三个 token 的连续短语；
- bigram 和 trigram 会显著增加内存与输出空间需求；
- Wikipedia 代表百科书面英语，不代表日常口语；
- 一个 dump 分块只是某次快照的样本，不是完整英文 Wikipedia；
- 在生成可信综合分数前，其他领域必须独立统计并保留来源结果。

## 项目结构

```text
configs/          数据集和发布配置
data/raw/         下载的原始语料，不提交 Git
data/processed/   提取语料和统计结果，不提交 Git
data/releases/    可发布的数据产物，不提交 Git
examples/         本地微型示例
src/freshfreq/    CLI、数据源、提取、分词和统计实现
tests/            自动化测试
```

## 数据与许可证

项目代码和生成数据是两个不同的许可证问题。发布数据集之前，必须逐一核对上游来源的署名、
再分发和派生统计条款。原始语料和生成产物默认排除在 Git 之外。

不能把 Wikipedia 单一来源的结果描述为通用英语或口语词频。对外提供结果时应同时公开来源、
快照、语料规模和统计方法。
