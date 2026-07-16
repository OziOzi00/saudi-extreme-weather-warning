# 成员 A 批处理说明

## 输入：事件清单

以 `configs/case_catalog_template.csv` 创建本地清单，例如：

```text
case_id,initial_time,event_type,notes
20200820_00,2020-08-20T00:00:00Z,demo,workflow demonstration only
20200715_00,2020-07-15T00:00:00Z,heatwave,example candidate
```

- `case_id`：项目内唯一标识；建议 `YYYYMMDD_HH`。
- `initial_time`：GraphCast 的 00 或 12 UTC 起报时间，ISO-8601 UTC。
- `event_type` 和 `notes`：可选的追溯信息。

版本化正式清单为 `configs/case_catalog_candidates.csv`：12 个真实案例已于 2026-07-16 批准并冻结 development/independent_test 划分；`20200820_00` 仍只是已跑通的 demo，不声明为极端灾害事件。若试验其他未批准日期，应使用 `data/external/` 下的本地清单，不提交 Git。

清单预检查会拒绝重复 `case_id`、重复起报时间、非 UTC `Z` 时间、非 00/12 UTC 起报、非 2020 回放年份和不安全的标识符，并报告已有输出是否真正通过契约验收：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m saudi_warning.forecasting.preflight_catalog `
  --catalog configs/case_catalog_candidates.csv
```

## 运行

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m saudi_warning.forecasting.run_batch `
  --catalog data/external/case_catalog.csv `
  --output-dir handoff/mazu_like `
  --manifest manifests/processing_manifest.csv
```

每个 case 会检查 +6 到 +72h 的本地裁剪缓存，只对缺失时次启动独立下载进程（默认每时次最多重试 3 次），并生成 lead024、lead048、lead072 三个 24 小时窗口。处理状态、路径和错误信息会立即写入 manifest。

只有三个输出均存在且通过自动验收的个例才标为 `skipped`。损坏缓存会保留为旁路 `.invalid` 文件并重新获取；新 NetCDF 先写入 `.partial`，通过验收后再原子替换目标，避免断电产生的半成品被交付。

## 自动验收与溯源

验收器检查文件名、11 个变量、单位、二维坐标、0.25° 网格、UTC 时间、24 小时窗口、lead、四个窗口时次、必需属性、有限值覆盖、宽松物理范围及 `Tmin <= Tmean <= Tmax`：

```powershell
python -m saudi_warning.forecasting.validate_mazu_like handoff/mazu_like `
  --report outputs/mazu_like_validation.json
```

交付清单 `manifests/delivery_manifest.csv` 为每份 NetCDF 保存大小、SHA-256、文件修改时间、验收时间/状态、时间窗口、指标版本、指标映射 SHA-256、A 侧实际实现 SHA-256 和基础 Git revision：

```powershell
python -m saudi_warning.forecasting.build_delivery_manifest `
  --catalog data/external/case_catalog.csv
```

## 一键 A 侧交付

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_a_delivery.ps1 `
  -Catalog data/external/case_catalog.csv
```

该命令依次执行清单预检查、可恢复批处理、NetCDF 验收、ADM1 摘要、交付清单、交付后复查和 A 侧测试。正式 MAZU-like 输出位于 `handoff/mazu_like/`；缓存和其他大数据不提交 Git。输出字段、单位和窗口语义见[数据交接契约](数据交接契约.md)。
