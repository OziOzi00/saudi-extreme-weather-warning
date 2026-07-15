# 协作开发说明

## 分支与提交

- `main` 应保持可运行；使用 `feature/<成员>-<主题>` 或 `fix/<主题>` 分支。
- 提交信息用简洁动词开头，例如 `feat: add GraphCast case loader`。
- 合并前运行 `$env:PYTHONPATH = "$PWD\src"; python -m pytest -q`。

## 代码与共享接口

- Python 3.11+；公共函数使用类型标注和简短 docstring。
- 跨成员接口包括 `docs/数据交接契约.md`、`configs/indicator_mapping.yaml`、两个风险规则 YAML 和 `src/saudi_warning/common/models.py`。修改时必须说明兼容性并请 A/B/C 审阅。
- 未冻结的规则不得描述为已验证；Agent 不得改变规则阈值、气象指标或风险分数。
- 职责、交接顺序和各成员待办以 [`docs/团队协作流程.md`](docs/团队协作流程.md) 为准；不要把 B/C 的计划或接口示例描述为已完成业务结果。

## 交付物与大文件

只提交 `handoff/` 中体积可控、稳定的派生交接件。不得提交 MAZU 全量数据、GraphCast 缓存、IMERG/GHCN 原始数据、Neo4j 数据库、密钥或本机绝对路径。

Risk JSON 应先以 `python -m json.tool handoff/risk_results/<file>.json` 检查语法，再对照 `schemas/risk_result.schema.json` 和交接示例。复现实验时，在 PR 写清数据来源、时间范围、变量和运行命令。
