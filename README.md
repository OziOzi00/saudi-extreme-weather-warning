# Saudi Extreme Weather Warning

面向沙特阿拉伯强降水与高温/热浪的可追溯预警原型。第一版采用 **MAZU 2025 指标开发规则**，以 **GraphCast 2020 历史预报**进行回放，并通过 IMERG、GHCN-Daily 与灾害记录分别验证天气与影响。

## 当前范围

- 预警时效：未来 24 / 48 / 72 小时。
- 灾种：强降水风险、高温与热浪风险。
- 不在 v1 范围：沙尘、完整山洪影响预测、复杂机器学习、自己运行完整 GraphCast。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

复制 `.env.example` 为 `.env`，按需填写本地数据目录或服务连接信息。不要把密钥、NetCDF、GRIB 或原始数据提交到仓库。

## 项目结构

```text
src/saudi_warning/
  forecasting/       # 成员 A：GraphCast 读取和 MAZU-like 指标转换
  risk/               # 成员 B：规则、评分和风险结果
  knowledge_graph/    # 成员 C：Neo4j 导入与图谱查询
  reporting/          # 成员 C：可追溯预警报告
  common/             # 三方共享的数据模型、配置和校验
configs/              # 可版本化的指标映射、规则和路径配置
docs/                 # 架构、数据契约和协作约定
data/                 # 仅本地数据目录，占位文件会提交，实际数据被忽略
tests/                # 单元和接口测试
```

## 三方交接

1. 成员 A 输出规范的 `mazu_like_*.nc`。
2. 成员 B 读取该文件，输出每个行政区、灾种和时效的 `risk_result_*.json`。
3. 成员 C 将风险 JSON、观测与灾情证据写入图谱，并生成报告。

字段、单位、时间语义和文件命名以 [数据契约](docs/data_contract.md) 为准。总体方案见根目录的 [统一技术路线_v1.md](统一技术路线_v1.md)。

## 协作约定

- 从 `main` 拉取最新代码后创建功能分支：`feature/a-graphcast-loader`、`feature/b-risk-engine`、`feature/c-knowledge-graph`。
- 一个拉取请求聚焦一个可验证任务；不要混入大数据和个人环境文件。
- 修改共享契约或 YAML 配置时，请在 PR 中同时标注 A、B、C。
- 合并前至少运行 `pytest`。

## 数据不入库

MAZU 指标、GraphCast、IMERG、GHCN 下载文件和老师提供的 PDF 均只保存在本地或共享存储。仓库仅保存代码、配置、文档与小型合成测试数据。
