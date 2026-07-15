# 正式协作交付物

该目录仅保存通过 GitHub 同步、体积可控且版本稳定的派生交接件。

```text
handoff/
├─ mazu_like/       # 成员 A：每个 case 的 lead024/048/072 NetCDF
├─ mazu_statistics/ # A 协助 B：MAZU 2025 ADM1 描述统计，不是冻结规则
├─ region_summaries/# A 协助 B：GraphCast MAZU-like 的 ADM1 指标摘要
├─ risk_dry_runs/   # A 协助 B：候选规则试跑，禁止当作正式结果
├─ risk_results/    # 成员 B：每个区域、灾种、lead 的 Risk JSON
├─ disaster_truth/  # A 协助 C：来源索引与待复核影响真值
├─ knowledge_graph/ # A 协助 C：可审查的开发导入 bundle
└─ reports/         # A 协助 C：固定模板生成的报告
```

成员 B 读取 `mazu_like/`，并按 [`../docs/数据交接契约.md`](../docs/数据交接契约.md) 写入 `risk_results/`。Risk JSON 必须符合 [`../schemas/risk_result.schema.json`](../schemas/risk_result.schema.json)；`risk_results/example_risk_result.json` 仅供联调，数值不是实际风险结论。A 协助生成的 `risk_dry_runs/` 明确保持 `rule_status=draft`，不得导入 C 的正式图谱。

成员 C 读取风险 JSON，结合灾情资料完成图谱和报告；IMERG/GHCN 天气验证由 B 负责。完整栅格气象数据仍保留在 NetCDF，不进入图谱。当前 `knowledge_graph/` 和 `reports/` 使用候选案例及虚构 Risk JSON，只是开发交付，不是正式预警。

各交接件由谁生产、何时生产、哪些验证结果暂不进入版本化 handoff，见[三人分工与协作流程](../docs/团队协作流程.md)。

禁止放入：MAZU 全量指标、GraphCast 原始或裁剪缓存、IMERG/GHCN 原始文件、Neo4j 数据库，以及任何单文件超过 100 MB 的数据。
