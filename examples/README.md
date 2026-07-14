# 联调样例数据

`data/` 中的三个 NetCDF 文件是成员 A 从 GraphCast 2020-08-20 00 UTC 起报生成的 MAZU-like v1 联调样例，分别对应 24、48、72 小时窗口。

它们用于成员 B 开发风险引擎、成员 C 验证风险 JSON 接口。文件已通过 `docs/data_contract.md` 规定的变量、单位、网格和元数据校验。

这里只存放小型、稳定的接口样例。原始 GraphCast 缓存、MAZU 全量指标、IMERG/GHCN 数据和批量输出必须存放在共享云盘或本地数据目录，不能提交到 Git。
