# 成员 A 工作区

本目录放置以下可测试模块：

- `graphcast_loader.py`：远程打开 WeatherBench 2、按起报时间/区域/变量/层次/时效裁剪。
- `indicator_converter.py`：将 6 小时时次转换为 MAZU-like 日窗口指标，并写出标准 NetCDF。

首个验收目标：一个 2020 个例生成包含 `daily_precip_total`、`tmax_c`、`ivt`、`wind850_speed` 的 `lead024` 文件，并满足 `docs/data_contract.md`。
