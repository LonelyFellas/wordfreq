# wordfreq / freshfreq

本仓维护可复现的英文词频数据流水线，不属于 tsz 在线 API 或 AI worker。Python >=3.11，uv 与 `uv.lock` 管理依赖；CLI 为 `freshfreq`，实现位于 `src/freshfreq`。

## 工作与交付

面向用户使用简体中文。从最新 origin/main 创建 codex/ 任务分支和独立 worktree，已有本任务工作区复用，保留用户改动。实现不自动包含提交、推送、合并或发布；hooks 正常执行。
已有目标明确就按实际代码实施，小改动不强制 spec。Bug 保留可重复失败，最小修复并沿原路径验证。需要通用 feature/test/ship 入口时直接使用全局技能，不复制 Web、Rust 或 Agent 流程。

## 数据与验证

- 词频必须保留来源、快照、域/时间范围、统计口径与 metadata，不能把不同语料混成无法解释的分数。
- 核对 build/extraction manifest、校验和与已完成输出后复用续跑结果；中断不代表零写入，不能盲删共享数据、下载缓存或正在使用的产物。
- 测试使用小型 fixture 和任务临时输出，不为普通验证下载整份 Wikipedia 或重跑大型流水线。真实全量下载/重建先明确目标、磁盘及资源范围。
- 按风险运行受影响 pytest；代码改动完成前执行 `uv run pytest` 与 `uv run ruff check .`。纯规则文档检查格式、链接与一致性，不额外运行套件；不套用其他仓覆盖率或数据库规则。

命令、数据格式与流程见 [README](README.md) 和 [中文说明](README.zh-CN.md)。结束报告实际输入/版本、验证与未完成阶段，保留正常数据，只清理本任务拥有的临时资源。
