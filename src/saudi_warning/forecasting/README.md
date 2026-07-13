# 成员 A 工作区

本目录放置以下可测试模块：

- `graphcast_loader.py`：远程打开 WeatherBench 2、按起报时间/区域/变量/层次/时效裁剪。
- `indicator_converter.py`：将 6 小时时次转换为 MAZU-like 日窗口指标，并写出标准 NetCDF。

首个验收目标：一个 2020 个例生成包含 `daily_precip_total`、`tmax_c`、`ivt`、`wind850_speed` 的 `lead024` 文件，并满足 `docs/data_contract.md`。

运行样例：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m saudi_warning.forecasting.run_case --initial-time 2020-08-20T00:00:00Z --lead-hours 24
```

首次运行会将每个 6 小时时次裁剪后缓存至 `data/raw/graphcast_2020/`；同一个个例再次运行会直接使用这些本地缓存。缓存和产出的 NetCDF 均不提交 Git。

首次网络与文件输出验证（只处理降水，避免在尚未验证链路时下载全球高空场）：

```powershell
python -m saudi_warning.forecasting.run_precip_smoke
```
