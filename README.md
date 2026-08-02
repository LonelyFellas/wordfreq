# freshfreq

一个面向现代英语词频的可复现统计项目。项目按数据源和时间段分别保存统计结果，避免把
Wikipedia、网页、新闻和口语语料直接混为一个不可解释的数字。

当前 v0.1 骨架支持：

- Unicode 归一化和英文 token 提取；
- 统计出现次数和文档覆盖数；
- 计算每百万词频率和 Zipf 值；
- 从纯文本文件生成 CSV 统计结果；
- 使用版本化 JSON 配置描述数据集。

## 开始使用

```bash
uv sync
uv run freshfreq --help
uv run pytest
```

运行项目自带的示例（每行视为一篇独立文档）：

```bash
uv run freshfreq count examples/sample.txt --output data/processed/sample.csv
```

查看结果：

```bash
column -s, -t data/processed/sample.csv
```

统计自己的语料时，将 `examples/sample.txt` 换成真实文件路径。输入必须是 UTF-8 文本，
每行代表一篇独立文档；只有这样才能正确计算 `document_frequency`。

输出字段：

```text
term,occurrence_count,document_frequency,frequency_per_million,zipf_frequency
```

## 目录

```text
configs/          数据集和构建版本配置
data/raw/         原始语料，不提交 Git
data/processed/   中间统计，不提交 Git
data/releases/    最终发布数据，不提交 Git
src/freshfreq/    归一化、分词、统计、导出和 CLI
tests/            自动化测试
examples/         可直接运行的微型示例语料
```

后续数据源应分别构建，例如 `wikipedia`、`common_crawl`、`news` 和 `spoken`。聚合之前
必须保留来源、时间范围、总 token 数和总文档数。
