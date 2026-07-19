# 整体链条影子纠错示例

该目录固定保存 `20200501_00_048 / SA-09 / heavy_rain` 的确定性研究回放，用于检查：

- Forecast Agent只读取预测时允许的信息，`truth_accessed=false`；
- 冻结暴雨v2基础风险保持`low`；
- 图谱v2可以输出`triggered_not_activated`和影子建议`medium`；
- 影子建议不覆盖Risk JSON，有效关注级别仍为`routine`；
- 该示例不是业务预警，也不是图谱候选的独立验证。

可使用 `python -m saudi_warning.agent.run_forecast_report` 从对应Risk JSON重建三份产物。
