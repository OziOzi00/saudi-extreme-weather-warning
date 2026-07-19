# 统一候选评估交接件

本目录由 `python -m saudi_warning.risk.benchmark_integrated_candidates` 确定性生成，保存已经开放的development候选逐行结果、汇总指标和分批稳定性检查。

重要边界：

- 文件包含development观测标签，只能用于规则研究和Verification，不得进入Forecast Agent或预测图谱；
- 暴雨独立集只在机器可读manifest中记录冻结v2的既有结论和新影子候选的非盲压力检查，不参与候选选择；
- 独立高温案例未读取；
- 本轮是看到全部development结果后的回顾性统一比较，不是新的前瞻验证；
- 高温没有可冻结候选，图谱v2也只是未激活影子方案。
