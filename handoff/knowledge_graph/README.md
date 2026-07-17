# 成员 C：知识图谱开发交接

`import_bundle.json` 是数据库无关、可审查的 Neo4j 开发输入，包含区域、候选案例、来源、影响证据以及示例 Risk JSON 的摘要关系。它不包含 NetCDF 栅格、网页全文或 Neo4j 数据库文件。

`import_bundle.json`仍是虚构Risk JSON接口示例。`formal_development_bundle.json`接入15份冻结暴雨development结果，共69个节点、98条关系。`heavy_rain_evaluation_bundle.json`进一步接入18份锁定独立结果，共87个节点、152条关系。

## 使用

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m saudi_warning.knowledge_graph.build_bundle
python -m saudi_warning.knowledge_graph.build_bundle `
  --risk handoff/risk_results/development_heavy_rain `
  --output handoff/knowledge_graph/formal_development_bundle.json `
  --generated-at 2026-07-17T00:00:00Z

python -m saudi_warning.knowledge_graph.build_bundle `
  --risk handoff/risk_results/development_heavy_rain `
  --risk handoff/risk_results/independent_heavy_rain `
  --output handoff/knowledge_graph/heavy_rain_evaluation_bundle.json `
  --generated-at 2026-07-17T03:35:02Z
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

2026-07-17已使用`heavy_rain_evaluation_bundle.json`完成本地Community 2026.06.0实机联调：87个节点、152条关系、6个约束和三组固定查询均通过。机器结果见`manifests/neo4j_live_verification.json`，完整边界见`docs/2026-07-17_Neo4j实机联调结果.md`。可复验脚本为`scripts/run_neo4j_live_integration.ps1`；脚本要求服务已启动且`.env.neo4j.local`只存在本机。
