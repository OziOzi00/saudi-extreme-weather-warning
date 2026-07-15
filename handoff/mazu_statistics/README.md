# MAZU 2025 区域描述统计

本目录是成员 A 协助成员 B 生成的小型分析交接件，不是已冻结风险规则。

- `mazu_2025_adm1_descriptive_stats.csv`：13 个 ADM1、年度和四季、11 个共享指标的描述统计。
- `saudi_adm1_grid_coverage.csv`：各 ADM1 包含的 MAZU 0.1° 网格中心数量。

统计定义：

- `daily_region_mean_*`：每日区域纬度余弦加权均值，再对有效日期计算分位数。
- `daily_region_max_*`：每日区域网格最大值，再对有效日期计算分位数。
- `daily_spatial_p95_*`：每日区域空间 P95，再对有效日期计算分位数。
- `valid_days`：该区域、时期、指标至少存在一个有限网格值的日期数。

边界使用 `data/reference/saudi_adm1_geoboundaries_2017.geojson`。这些结果用于提出候选阈值和检查区域差异；B 必须结合缺测、时间聚合语义和独立验证后才能冻结规则。
