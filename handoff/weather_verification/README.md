# Development天气验证交接

本目录保存B侧天气层验证的小型、可追溯交接文件，不保存IMERG/GHCN原始数据。

`development_pairs.csv`只包含7个已批准的`development`案例，严格排除5个`independent_test`案例。当前81条预期配对已经全部建立：

- 45条IMERG降水配对，使用相同ADM1和`weighted_mean/spatial_p95/maximum`口径，日文件覆盖率为1.0，标记为`accepted`；
- 36条GHCN温度配对，预测先采样到当天实际有观测的相同站点，再计算`station_mean/station_max/station_min`；由于归档中的观测时刻为空，UTC日界线尚未确认，标记为`provisional`。

`event_threshold`目前留空，因为本步骤只建立配对和QC，不使用观测结果调整或冻结阈值。`manifests/development_pairing_coverage.csv`记录全部81条预期配对；先前缺少的6个IMERG UTC日文件已补齐，当前`missing=0`。

`configs/weather_verification_qc_v1.yaml`已经冻结本轮development诊断口径。`development_continuous_metrics.csv`由专用入口生成，共36行：

- 12行`accepted_development_metric`：仅来自IMERG降水，包含3种聚合在all-leads及24/48/72h上的MAE、RMSE和Bias；
- 24行`provisional_diagnostic_not_formal`：仅来自GHCN TMAX/TMIN，保留相同连续指标，但不得作为正式温度或热浪验证结论；
- 阈值尚未冻结，因此命中、漏报、空报、POD、FAR、CSI和热浪序列均未计算，相关字段保持空白。

可复验命令：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m saudi_warning.verification.run_development_diagnostics
```

GHCN-Daily官方文档说明`OBS-TIME`是站点当地观测时间；当前沙特记录该字段为空，无法证明其与GraphCast UTC日窗口完全一致。在补齐时间语义并通过正式最低站点数规则前，不得把临时诊断描述为完整天气效果评估，也不得运行或查看`independent_test`结果。
