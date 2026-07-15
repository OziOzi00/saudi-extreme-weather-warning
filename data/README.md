# 数据目录说明

- `raw/graphcast_2020/`：成员 A 的 GraphCast 本地缓存，不提交 Git。
- `raw/imerg/`、`raw/ghcn/`：成员 B 用于天气层验证的本地观测，不提交 Git。
- `processed/`：本地中间结果，不提交 Git。
- `external/`：尚未版本化的外部资料和正式 case 清单，不提交 Git。
- `reference/`：体积可控、许可清晰、需要跨成员统一使用的版本化参考数据。

当前 `reference/` 中的 ADM1 GeoJSON 是 A 协助 B/C 准备的原型边界。来源、许可和限制见 [`reference/README.md`](reference/README.md)。MAZU 2025 原始日文件位于 `MAZU指标/indicators/`，不复制进本目录，也不提交 Git。

任何新增数据都应记录来源、许可、时间范围、变量、空间范围和生成方法。

GraphCast 缓存若存在但无法读取或缺少必需变量/层次，A 的加载器会把它保留为相邻 `.invalid[.N]` 文件后重新获取；`.partial` 文件表示尚未完成原子交付，不能交给 B。
