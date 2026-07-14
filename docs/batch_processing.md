# 成员 A 批处理说明

## 输入：事件清单

以 `configs/case_catalog_template.csv` 为模板创建本地事件清单，例如：

```text
case_id,initial_time,event_type,notes
20200820_00,2020-08-20T00:00:00Z,heavy_rain,example case
20200715_00,2020-07-15T00:00:00Z,heatwave,example case
```

- `case_id`：项目内唯一标识，推荐 `YYYYMMDD_HH`。
- `initial_time`：GraphCast 的 00 或 12 UTC 起报时间，ISO-8601 UTC。
- `event_type`、`notes`：可选，供后续筛选和追溯。

正式事件清单由成员 C 基于 2020 年事件和普通日期确定。它应保存在 `data/external/case_catalog.csv`（本地数据，不提交 Git）。

## 运行

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m saudi_warning.forecasting.run_batch `
  --catalog data/external/case_catalog.csv `
  --output-dir handoff/mazu_like `
  --manifest manifests/processing_manifest.csv
```

每个个例会：

1. 检查 `+6` 至 `+72h` 的本地裁剪缓存；
2. 仅对缺失时次启动独立下载进程，每个时次最多重试 3 次；
3. 由缓存生成 `lead024`、`lead048`、`lead072` 三个 MAZU-like NetCDF；
4. 将处理状态、输出路径或错误信息立即写入处理清单。

再次运行时，三个输出均存在的个例会标记为 `skipped`，不会重复下载或计算。正式、体积可控的 MAZU-like 输出位于 `handoff/mazu_like/`，需要随代码提交；原始缓存和其他大数据仍不提交 Git。
