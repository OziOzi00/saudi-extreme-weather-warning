# 成员 B 风险结果

成员 B 将规则引擎生成的 `risk_result_*.json` 提交到本目录。字段必须符合 [`../../docs/数据交接契约.md`](../../docs/数据交接契约.md) 与 [`../../schemas/risk_result.schema.json`](../../schemas/risk_result.schema.json)。

`example_risk_result.json` 是 Schema 联调样例，使用虚构值，不代表风险引擎、灾害验证或成员 B 工作已经完成。

正式结果必须显式写入 `rule_status: frozen`。`handoff/risk_dry_runs/` 中的 `draft` 结果不得复制到本目录或交给成员 C 作为正式结论。
