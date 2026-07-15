# 成员 C：知识图谱开发交接

`import_bundle.json` 是数据库无关、可审查的 Neo4j 开发输入，包含区域、候选案例、来源、影响证据以及示例 Risk JSON 的摘要关系。它不包含 NetCDF 栅格、网页全文或 Neo4j 数据库文件。

当前 bundle 标记为 `development_bundle`，因为案例尚未由全队批准，Risk JSON 也是虚构接口示例。它只能证明导入结构可运行。

## 使用

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m saudi_warning.knowledge_graph.build_bundle
```

真正导入 Neo4j 5.x 前，先执行 `neo4j/schema.cypher`，设置本地环境变量后运行：

```powershell
pip install -e ".[graph]"
$env:NEO4J_URI = "bolt://localhost:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "仅保存在本机的密码"
python -m saudi_warning.knowledge_graph.load_neo4j
```

密码、Neo4j 数据目录和原始灾害材料不得提交 Git。固定查询位于 `neo4j/queries/`。
