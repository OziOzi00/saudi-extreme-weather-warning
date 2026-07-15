# 候选风险规则试跑

本目录是成员 A 协助成员 B 生成的 **draft 开发产物**，不能作为正式预警、成员 B 最终交付或独立评估结论。

- `candidate_threshold_audit.csv`：13 个 ADM1 × 4 季的暴雨/高温候选参考值、绝对下限和实际应用门槛，共 260 行。
- `risk_evidence_audit.csv`：78 份草案结果的等级、分数、置信度和支持/矛盾/缺失证据计数。
- `results/`：3 个 lead × 13 个 ADM1 × 2 个灾种的逐文件草案 JSON。

运行方式：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m saudi_warning.risk.run_draft
```

引擎会拒绝用 `status: draft` 的规则写入 `handoff/risk_results/`。规则经全队评审、观测验证并冻结前，正式目录应继续只保留接口示例。

完整草案联调可运行 `powershell -ExecutionPolicy Bypass -File scripts/run_b_dry_integration.ps1`，它会重新生成结果、运行 Risk JSON 验收并执行 B 侧相关测试。
