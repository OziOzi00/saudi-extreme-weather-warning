# 成员 C：受控报告

报告由固定模板从 Risk JSON、区域注册表和灾害影响真值生成。模板不会修改成员 B 的风险等级、分数、阈值或置信度。

`example_warning_report.md` 使用仓库中的虚构 Risk JSON，因此必须始终保留“仅供接口联调”的状态声明。正式报告使用 `--mode formal`，代码会拒绝不是 `rule_status=frozen` 的 Risk JSON。

`development_heavy_rain/`包含15份由冻结暴雨规则生成的受控development报告，清单位于`manifests/formal_development_report_manifest.csv`。报告保留其生成时的development验证状态；独立结果应查看下述独立目录，不能回写或改造这些开发产物。

`independent_heavy_rain/`包含18份锁定独立结果报告，清单位于`manifests/independent_heavy_rain_report_manifest.csv`。报告保留`independent_test_one_time_locked`和`no_retuning`声明。
