# 极端天气联合预测报告（无真值模式）

> 本报告的联合结论由基础气象规则与预测前图谱一致性规则共同产生；`truth_accessed=false`。

## 综合结论

20200501_00 / SA-09 / +48h 的 heavy_rain 联合风险为 medium。开发门槛已通过，当前状态为 research_candidate，不能直接视为正式业务预警。

## 决策链

- 案例：`20200501_00`
- 区域：`SA-09`
- 时效：`+48h`
- 灾种：`heavy_rain`
- 基础方法：`v2_base`
- 基础风险：`low`
- 图谱规则：`cross_window_persistence`
- 图谱触发：`true`
- 联合最终风险：`medium`
- 决策变化：`upgraded`
- 开发门槛通过：`true`
- 运行状态：`research_candidate`
- 正式预警许可：`false`

## 预测特征

- `primary_ratio`：`0.57966504`
- `support_count`：`2`

## 图谱推理说明

图谱一致性规则已触发：cross_window_persistence 将基础风险从 low 调整为 medium。该调整只使用锁定预测特征，未读取同期真值。

## 限制

- 本报告只读取无真值预测锁；命中、漏报和误报只能在锁定后的验证阶段计算。
- 联合候选是在已打开的development样本上回顾性选择，存在样本量小和选择偏差风险。
- 暴雨图谱增益只来自一个development事件，独立回放中未触发纠错。

## 建议

- 保留基础风险与联合风险两列，供人工追溯图谱是否改变了结论。
- 继续收集新的前瞻案例，重点验证图谱触发时是否稳定减少漏报且不新增误报。

## 溯源

- 预测锁：`handoff/model_selection/joint_v2/locked_development_joint_heavy_rain_predictions.csv`
- 预测锁 SHA-256：`e7e0816f29aa7341bc3f7be279b59b184e9183d17d245e67e31cab08807f615f`
- 选择锁：`manifests/joint_pipeline_selection_lock_v2.json`
- 选择锁 SHA-256：`8d3526d9f6528378d274129ad424cba39904a5cfcce2e164fc62fe7b4ca55545`
