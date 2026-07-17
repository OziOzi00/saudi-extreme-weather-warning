# MAZU-like ADM1 区域摘要

`mazu_like_adm1_indicator_summaries.csv` 是A交给B的预测区域摘要，包含12个正式案例和1个demo的39份lead文件、13个ADM1和11个指标，共5577行。

每行记录区域网格数、有效网格数、最小值、纬度余弦加权均值、空间 P95 和最大值。它用于 B 开发区域聚合和构造 Risk JSON 的 `indicator_summary`，不包含风险分数、风险等级或规则判断。

摘要沿用 `configs/region_registry.csv` 的 `region_id` 和 `data/reference/` 边界。完整气象场仍以 `handoff/mazu_like/*.nc` 为准。
