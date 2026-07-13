# 数据契约 v1

本契约规定成员 A、B、C 的交接格式。任何不兼容更改必须提升 `indicator_version` 或在 PR 中提供迁移说明。

## A -> B：MAZU-like NetCDF

**命名：** `mazu_like_{YYYYMMDD}_{HH}_lead{LLL}.nc`，例如 `mazu_like_20200820_00_lead024.nc`。

**坐标：** `latitude`、`longitude`；保持 GraphCast 原生 0.25° 网格，不得伪造为 0.1°。

**必需变量：** `daily_precip_total`、`t2m_c`、`tmax_c`、`tmin_c`、`wind10_speed`、`pwat`、`ivt`、`wind850_speed`、`wind_shear_850_200`、`omega500`、`geopotential_height500`。

**必需全局属性：**

```text
forecast_model = GraphCast
initial_time = ISO-8601 UTC
lead_time_hours = 24 | 48 | 72
valid_start_time = ISO-8601 UTC
valid_end_time = ISO-8601 UTC
source_resolution = 0.25 degree
indicator_version = mazu_like_v1
```

每个变量必须包含 `units` 属性；转换公式和单位见 `configs/indicator_mapping.yaml`。

## B -> C：风险结果 JSON

每个 JSON 对应一个 `case_id + region + hazard + lead`，最低字段如下：

```json
{
  "case_id": "20200820_00_024",
  "region": "Makkah",
  "hazard": "heavy_rain",
  "lead_time_hours": 24,
  "risk_level": "high",
  "risk_score": 7,
  "triggered_conditions": ["daily_precip_total >= 20 mm"],
  "missing_conditions": [],
  "source_file": "mazu_like_20200820_00_lead024.nc",
  "rule_version": "v1"
}
```

`hazard` 仅允许 `heavy_rain` 或 `heatwave`；`risk_level` 由成员 B 冻结后的规则定义。

## C 的证据原则

天气观测证据（IMERG/GHCN）与灾害影响证据必须分开保存和评估。未找到灾情资料只能标记为 `unknown`，不能视为 `no`。
