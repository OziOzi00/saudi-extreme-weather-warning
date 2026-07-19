# 联合Agent真实Neo4j与Luna/Terra联调

## 结论

2026-07-19已经补齐联合Agent的在线运行链，不再只是CSV读取和确定性模板：

```text
无真值联合预测锁
→ 参数化写入正在运行的Neo4j
→ Agent实时查询24/48/72小时图谱时间线
→ Luna默认生成 / Terra升级生成
→ Pydantic与程序守卫逐字段核对
→ JSON、Markdown和证据包
```

暴雨案例由`gpt-5.6-luna`真实生成，高温案例由`gpt-5.6-terra`真实生成。两次均满足：

- `neo4j_query_mode=live_neo4j`；
- `truth_accessed=false`；
- 五个受控工具全部调用；
- 24/48/72小时全部覆盖；
- 基础风险、图谱触发和联合最终风险未被模型改写；
- `formal_warning_allowed=false`。

## Neo4j隔离设计

在线预测节点使用独立标签：`JointPredictionCase`、`JointPredictionRegion`、`JointForecastWindow`和`JointRule`。查询只允许沿预测关系访问，不复用包含同期真值的`HistoricalEvent`、`Evidence`、Observation或Verification路径。

写入使用SHA锁定的无真值CSV，并显式拒绝`case_role`、`observed_*`、命中、漏报和误报字段。节点和关系均使用参数化Cypher与唯一约束，可重复运行而不产生重复窗口。

## 真实联调结果

| 灾种 | 模型 | 图谱写入 | 重点窗口 | 联合结果 | 报告状态 |
| --- | --- | ---: | --- | --- | --- |
| 暴雨 | `gpt-5.6-luna` | 15窗口、5案例、2区域 | `20200501_00 / SA-09 / +48h` | medium | research_candidate |
| 高温 | `gpt-5.6-terra` | 6窗口、1案例、2区域 | `20200729_00 / SA-04 / +48h` | high | research_only_blocked |

暴雨报告分析了三个lead均由low经图谱提升到medium，以及降水比例和支持条件的变化。高温报告分析了24小时medium向48/72小时high的演变，并明确三个窗口图谱均未触发、高温规则仍未通过开发门槛。

## 运行方法

本地需要已经忽略的`.env.agent.local`和`.env.neo4j.local`，密钥和密码不得提交：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_joint_agent_live.ps1 `
  -Hazard heavy_rain -Split development `
  -CaseId 20200501_00 -RegionId SA-09 -LeadTimeHours 48
```

默认使用Luna；复杂案例可显式传入`-Model gpt-5.6-terra`。Luna运行失败或结构化守卫未通过时，入口会自动尝试配置的Terra升级模型，不会静默退回伪装成大模型的模板报告。

## 可审计产物

- 联调清单：`manifests/joint_agent_live_integration_v1.json`；
- 暴雨Luna报告：`handoff/reports/joint_pipeline_live/heavy_rain_luna_live.md`；
- 高温Terra报告：`handoff/reports/joint_pipeline_live/heatwave_terra_live.md`；
- 每份报告旁均保存无真值证据包和结构化JSON；
- Schema：`schemas/agent_joint_forecast_report_v5.schema.json`。

## 仍需保持的边界

这次联调证明“Neo4j和大模型真实参与了运行”，不等于证明气象效果已经生产可用。暴雨图谱仍缺少新的独立触发证据；高温仍缺少独立对照且未通过development全部门槛。大模型只能解释锁定结果，不能修正气象数值或绕过规则门槛。
