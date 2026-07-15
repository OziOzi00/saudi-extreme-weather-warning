# 成员 C：受控报告

报告由固定模板从 Risk JSON、区域注册表和灾害影响真值生成。模板不会修改成员 B 的风险等级、分数、阈值或置信度。

`example_warning_report.md` 使用仓库中的虚构 Risk JSON，因此必须始终保留“仅供接口联调”的状态声明。正式报告使用 `--mode formal`，代码会拒绝不是 `rule_status=frozen` 的 Risk JSON。
