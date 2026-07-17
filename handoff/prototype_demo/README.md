# 稳定原型演示交接

本目录用于 `v0.1.0-prototype` 阶段发布。运行仓库根目录下的：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_prototype_demo.ps1
```

脚本只读取已版本化的小型交接产物，不下载原始 GraphCast、IMERG、SSOD 或 MAZU 数据，也不要求启动 Neo4j。它会重新生成 `demo_summary.json`，验收 33 份冻结暴雨 Risk JSON，并运行原型边界测试。

建议演示两个案例：

- 正向覆盖：`20200725_00 / SA-14`，lead048 为 `medium`、lead072 为 `high`；可沿 Risk JSON、报告和图谱 bundle 查看证据链。
- 已知漏报：`20200501_00 / SA-09`，lead024/048 均为 `low`；仓库保留天气低估与规则空间尺度缺口的归因，且没有因该结果回调冻结规则。

`demo_summary.json` 是机器可读的阶段快照，不是业务运行状态。当前只能将暴雨链路称为稳定研究原型；高温规则仍为 draft，影响层没有可靠负例，Neo4j 只完成本地 development 联调。
