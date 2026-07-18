# 预测前静态知识上下文

本目录保存可进入Forecast Agent的、小体积派生知识，不保存原始GeoTIFF。

- `static_context_v1.json`：13个ADM1 × 12个月的WorldClim 2.1地形与降水气候背景；
- `worldclim_adm1_monthly_context.csv`：相同数据的表格视图。
- `development_spatial_diagnostics_v1.json`：在标签评估前锁定并生成的15份development预测网格细空间诊断；
- `development_context_audit.csv`：打开development标签后的隔离评估结果，不得输入Forecast Agent。

当前状态严格为`context_only_not_validated`。它只说明区域地形和1970–2000月平均气候背景，不生成`knowledge_prior_risk`，不能判断某个2020事件日会不会发生暴雨，也不能改变冻结Risk JSON。

细空间局地热点候选触发0次、没有减少development漏报，已决定淘汰并保持在审计层，未接入Agent关注逻辑。

原始数据位于被Git忽略的`data/external/worldclim_2_1_10m/`。复建命令：

```powershell
pip install -e ".[knowledge]"
$env:PYTHONPATH = "$PWD\src"
python -m saudi_warning.knowledge_graph.static_context --generated-at 2026-07-18T13:00:00Z
```

完整复建静态上下文、细空间预测诊断、development隔离评估和边界测试：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_forecast_knowledge_development.ps1
```

来源为WorldClim 2.1（2020年1月发布，1970–2000基线），高程由SRTM派生。配置固定了下载URL、SHA-256、保守`available_at=2020-03-15T00:00:00Z`和分辨率限制。
