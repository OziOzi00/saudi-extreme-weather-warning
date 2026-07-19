# 极端天气联合预测报告（无真值模式）

> 本报告的联合结论由基础气象规则与预测前图谱一致性规则共同产生；`truth_accessed=false`。

## 综合结论

20200729_00 / SA-04 / +48h 的 heatwave 联合风险为 high。开发门槛未通过，当前状态为 research_only_blocked，不能直接视为正式业务预警。

## 决策链

- 案例：`20200729_00`
- 区域：`SA-04`
- 时效：`+48h`
- 灾种：`heatwave`
- 基础方法：`pooled_median_loco`
- 基础风险：`high`
- 图谱规则：`temporal_or_spatial`
- 图谱触发：`false`
- 联合最终风险：`high`
- 决策变化：`unchanged`
- 开发门槛通过：`false`
- 运行状态：`research_only_blocked`
- 正式预警许可：`false`

## 预测特征

- `candidate_tmax_degc`：`50.505766`
- `hot_day_threshold_degc`：`47.249969`

## 图谱推理说明

图谱一致性规则未触发，联合风险保持基础判断 high；未使用同期观测或事后答案进行改写。

## 限制

- 本报告只读取无真值预测锁；命中、漏报和误报只能在锁定后的验证阶段计算。
- 联合候选是在已打开的development样本上回顾性选择，存在样本量小和选择偏差风险。
- 该独立划分此前已经打开，本次属于非盲全链回放。
- 高温没有独立对照案例，且最佳候选未通过development全部门槛。

## 建议

- 保留基础风险与联合风险两列，供人工追溯图谱是否改变了结论。
- 仅用于研究和人工复核；补充独立高温对照案例前不得启用正式预警。

## 溯源

- 预测锁：`handoff/model_selection/joint_v2/locked_joint_heatwave_predictions.csv`
- 预测锁 SHA-256：`42ffbc31f74ddefeb964cb05d64dc5e288bff4e011e280af19fed16cab092704`
- 选择锁：`manifests/joint_pipeline_selection_lock_v2.json`
- 选择锁 SHA-256：`8d3526d9f6528378d274129ad424cba39904a5cfcce2e164fc62fe7b4ca55545`
