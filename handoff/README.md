# 正式协作交付物

这个目录存放需要由 GitHub 在成员间同步的、体积可控且版本稳定的派生结果。

```text
handoff/
├─ mazu_like/       # 成员 A 输出：每个 case 的 lead024/048/072 NetCDF
└─ risk_results/    # 成员 B 输出：区域级风险 JSON
```

成员 C 读取 `risk_results/`，并结合本地保存的 IMERG、GHCN 和灾情资料完成图谱和报告。

禁止放入本目录的内容：MAZU 全量指标、GraphCast 原始或裁剪缓存、IMERG 原始文件、Neo4j 数据库文件，以及任何单文件超过 100 MB 的数据。
