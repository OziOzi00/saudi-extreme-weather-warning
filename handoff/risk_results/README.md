# 成员 B 风险结果

成员 B 将规则引擎生成的 `risk_result_*.json` 提交到本目录。字段必须符合 [`../../docs/数据交接契约.md`](../../docs/数据交接契约.md) 与 [`../../schemas/risk_result.schema.json`](../../schemas/risk_result.schema.json)。

`example_risk_result.json` 是 Schema 联调样例，使用虚构值，不代表风险引擎、灾害验证或成员 B 工作已经完成。

正式结果必须显式写入 `rule_status: frozen`。`handoff/risk_dry_runs/` 中的 `draft` 结果不得复制到本目录或交给成员 C 作为正式结论。

`development_heavy_rain/`包含15份由冻结暴雨v2生成的development目标区域结果，均通过Schema、区域、冻结状态和批次唯一性验收。它们带有development验证溯源，但不代表独立测试效果；高温规则仍为draft，因此没有正式高温JSON。

`independent_heavy_rain/`包含18份一次性独立暴雨结果；每份`verification`均指向锁文件、独立指标并声明`no_retuning=true`。独立天气层结果良好，但样本规模、极值低估和影响层unknown限制仍然有效。
