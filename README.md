# Saudi Extreme Weather Warning

> 队友准备最终报告或答辩PPT时，请先阅读根目录的[项目总览与答辩交接](项目总览与答辩交接.md)，再按其中的证据路径进入具体文档、代码、配置、评估锁和案例报告；该总览是导航，不替代原始证据。

面向沙特阿拉伯强降水与高温/热浪的可追溯预警原型。项目把“气象预报是否正确”和“风险/灾害预警是否正确”分开验证，避免把规则开发数据误当作独立预报验证。

## 当前技术路线

```text
MAZU 2025 历史指标 → 分析分布并冻结风险规则

GraphCast 2018/2020 历史预报 → MAZU-like 指标 → ADM1摘要 → 基础风险规则
  → 预测时图谱纠错 → 联合最终风险与预测锁 → Neo4j → 编排Agent
  → 系统结论/LLM独立意见双轨报告 → 两轨锁定后才连接观测与灾害记录
  → 天气层/影响层事后验证
```

MAZU 2025 是开发和标定后半段流程的历史指标数据，不是未来预报模型。当前回放实验读取已预计算的 GraphCast 2018/2020 历史预报；项目不训练天气模型，也不自行运行完整 GraphCast。GraphCast 数据保持原生 `0.25 degree` 网格，绝不表述为 `0.1 degree` 预报能力。

## 真实项目状态（2026-07-19）

- **工程主线完成**：GraphCast历史预报到MAZU-like、ADM1汇总、基础规则、预测时图谱纠错、联合预测锁、Neo4j、完整编排Agent和双轨报告均已实现并实机跑通。
- **数据交付完成**：仓库共有81份小型MAZU-like NetCDF；最新结项批次实际复用26个案例、78份NetCDF，生成29个案例—区域报告单元和957行过程指标。
- **联合方案已锁定**：暴雨比较234组候选后通过development门槛；高温比较2316组候选后仍无方案通过全部门槛。选择过程和独立回放由SHA锁约束。
- **暴雨结果**：系统在development为5命中/0漏报/0误报/4正确否定，在既有independent_test回放为5/0/0/6；独立集图谱触发0次，不能据此声称已证明独立纠错增益。
- **高温结果**：系统在development为9/5/8/15；independent_test为4/0/0/0，但该划分没有负样本，不能估计特异度。高温继续`research_only_blocked`。
- **Agent双轨已锁后评分**：29份报告覆盖87个窗口；系统结论不可修改，大模型意见单独生成和锁定。LLM没有超过暴雨系统；高温LLM虽然补齐召回，却显著增加误报。
- **真值泄漏已隔离**：预测锁和两轨意见全部形成之后，才接入IMERG、SSOD、GHCN旁证和灾害影响资料；预测态查询禁止同期观测、案例角色、灾害答案和评分字段。
- **影响层仅作描述性结论**：经复核正例合并为6个案例—区域单位，中高风险覆盖5/6；缺少可靠无影响负例，不能计算完整误报率或准确率。
- **自动验证通过**：当前全仓测试为172项；同时保留Schema、配置、预测锁、报告、SHA清单和历史预注册记录供复验。
- **项目边界**：这是`retrospective_transfer_replay`历史回放研究原型，不是实时业务预警平台。后续科研工作是补充全新高温development证据和影响负例，不应在已揭示的小样本上继续追分。

更完整的事实清单见 [项目状态](docs/项目状态.md)。

2026-07-15 对 B、C 的协助开发内容、仓库证据和后续依赖，见 [B 与 C 协助开发进展](docs/2026-07-15_B与C协助开发进展.md)。

2026-07-16 的案例扩展、GHCN 实测可用性和 IMERG 下一道闸门，见 [案例扩展与观测可用性](docs/2026-07-16_案例扩展与观测可用性.md)。
同日的证据逐条复核与案例批准建议见 [证据复核与案例批准建议](docs/2026-07-16_证据复核与案例批准建议.md)。
按成员归属整理的最新完成项、剩余任务和批处理快照见 [阶段进展与正式批处理启动](docs/2026-07-16_阶段进展与正式批处理启动.md)。

## 三方协作

| 成员 | 负责输入与产出 | 不负责 |
| --- | --- | --- |
| A | GraphCast → MAZU-like NetCDF、缓存与批处理 | 风险阈值、灾害结论 |
| B | MAZU 2025 统计、风险规则、风险 JSON、天气层评估 | 重算 A 的气象指标 |
| C | 区域/灾害真值、Neo4j、证据组织、报告 | 重算气象指标或风险分数 |

交接顺序是：A 写入 `handoff/mazu_like/`；B 读取 NetCDF 并写入 `handoff/risk_results/`；C 先仅凭预测时点可用信息建立无真值预测快照和预测报告。预测输出锁定后，C 才能把本地观测与灾害资料接入独立验证图谱，生成事后验证报告。字段与语义以 [数据交接契约](docs/数据交接契约.md) 为准。

每位成员的完成状态、输入、详细任务、正式输出和不负责事项见[三人分工与协作流程](docs/团队协作流程.md)。任务按技术归属记入 A/B/C；A 代办的 B/C 产物会明确标注实际执行人，不能视为成员 B/C 已亲自验收或已部署。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
$env:PYTHONPATH = "$PWD\src"
python -m pytest -q
```

启动本地 Neo4j 并准备好两个 Git 忽略的环境文件后，可运行完整编排 Agent：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_full_orchestrator_agent.ps1 `
  -RunId "20260719_new_case" `
  -CaseId "20200729_00" `
  -InitialTime "2020-07-29T00:00:00Z" `
  -Hazard "heatwave" `
  -RegionId "SA-04"
```

要重跑高温与暴雨的 development/independent_test 四组数据并生成双轨分析报告，可运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_dual_prediction_batch.ps1
```

该批处理会先锁定系统结果和LLM独立意见，再打开真值分别评分；输出位于 `handoff/reports/dual_prediction_batch_v1/`。

安装依赖后，队友可直接运行稳定原型验收（不下载原始数据、不要求启动 Neo4j）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_prototype_demo.ps1
```

命令会生成 [`handoff/prototype_demo/demo_summary.json`](handoff/prototype_demo/demo_summary.json)，并验收全部33份冻结暴雨Risk JSON和阶段边界。发布口径与演示案例见 [v0.1.0 原型发布说明](docs/2026-07-17_v0.1.0原型发布说明.md)。

本地可视化研判台不需要安装前端框架或启动 Neo4j。它会先从仓库正式产物重建轻量数据包，再在 `http://127.0.0.1:8765` 提供页面：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_dashboard.ps1
```

页面展示 13 个 ADM1 区域、33 份冻结暴雨结果、独立测试命中案例、已知影响漏报及高温/影响层的验证边界。使用说明见[可视化演示系统](docs/2026-07-18_可视化演示系统.md)。

默认的无真值 Forecast Agent 链可以先在无API、零费用模式下运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_agent_report.ps1 -Provider deterministic
```

安装`.[agent]`可选依赖并设置`OPENAI_API_KEY`后，把`Provider`改为`openai`即可启用Luna。事后验证必须显式运行 `scripts/run_agent_verification_report.ps1`，不能把验证报告冒充预测报告；详细边界见[Agent整合技术方案](docs/Agent整合技术方案.md)。

预测前静态知识、细空间诊断和development隔离评估可复建为：

```powershell
pip install -e ".[knowledge]"
powershell -ExecutionPolicy Bypass -File scripts/run_forecast_knowledge_development.ps1
```

统一候选基准可单独复建为：

```powershell
python -m saudi_warning.risk.benchmark_integrated_candidates
```

当前联合研究主线可一键重跑开发搜索、独立回放和无真值联合报告：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_joint_pipeline_v2.ps1
```

Neo4j服务已启动且本地忽略的Agent/Neo4j环境文件已配置时，可运行真实联合Agent：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_joint_agent_live.ps1
```

成员 A 新增个例的批处理命令见 [成员 A 批处理说明](docs/成员A批处理说明.md)。成员 B/C 的任务和当前完成边界见 [团队协作流程](docs/团队协作流程.md)。

成员 A 的完整交付可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_a_delivery.ps1`；默认以版本化 demo catalog 复验现有三份 lead。当前批准案例位于 `configs/case_catalog_candidates.csv`，正式批处理必须保持冻结的 development/independent_test 划分。

成员 C 的开发交付可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_c_development.ps1`；它校验案例/真值、生成图谱 bundle 和示例报告，并运行 C 侧测试，不会启动或修改本地 Neo4j 服务。

冻结暴雨development链可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_frozen_development_pipeline.ps1`，它复验v2闸门、生成并验收15份Risk JSON、图谱bundle和15份报告；不会读取独立测试观测或启动Neo4j。

已锁定的独立暴雨链可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_locked_independent_heavy_rain.ps1`复验；脚本会核对既有锁文件中的规则/观测SHA，不允许更换输入或回调规则。

## 仓库与数据边界

仓库保存代码、配置、文档、Schema、小型示例和体积可控的正式交接件。MAZU 全量指标、GraphCast 原始/裁剪缓存、IMERG/GHCN 原始文件、Neo4j 数据库和单文件超过 100 MB 的数据不得提交。规则详见 [交接目录说明](handoff/README.md)。

## 文档索引

- [文档分类导航](docs/README.md)
- [统一技术路线](docs/统一技术路线_v1.md)
- [整体链条规则与图谱纠错综合评估](docs/2026-07-19_整体链条规则与图谱纠错综合评估.md)
- [联合规则—图谱整体搜索与全链回放](docs/2026-07-19_联合规则图谱整体搜索与全链回放.md)
- [联合Agent真实Neo4j与Luna/Terra联调](docs/2026-07-19_联合Agent真实Neo4j与LunaTerra联调.md)
- [双轨系统与大模型独立预测批量评估](docs/2026-07-19_双轨系统与大模型独立预测批量评估.md)
- [可视化演示系统](docs/2026-07-18_可视化演示系统.md)
- [高温 development 误差诊断](docs/2026-07-18_高温development误差诊断.md)
- [当前高温规则与问题说明](docs/当前高温规则与问题说明.md)
- [Agent 整合技术方案](docs/Agent整合技术方案.md)
- [预测前静态知识上下文评估](docs/2026-07-18_预测前静态知识上下文评估.md)
- [高温 Agent 真实联调与 v4 分层诊断](docs/2026-07-18_高温Agent真实联调与v4分层诊断.md)
- [高温 v3 前瞻 development 预注册](docs/2026-07-18_高温v3前瞻development预注册.md)
- [高温 v3 前瞻 development 评估结果](docs/2026-07-18_高温v3前瞻development评估结果.md)
- [架构设计](docs/架构设计.md)
- [MAZU 2025 开发方法](docs/MAZU2025开发方法.md)
- [指标时间语义与聚合口径](docs/指标时间语义与聚合口径.md)
- [候选规则统计解释](docs/候选规则统计解释.md)
- [IMERG/GHCN 天气观测接入与验证](docs/天气观测接入与验证.md)
- [数据交接契约与风险 JSON Schema](docs/数据交接契约.md)
- [风险引擎说明](docs/风险引擎说明.md)
- [知识图谱设计](docs/知识图谱设计.md)
- [评估协议](docs/评估协议.md)
- [团队协作流程](docs/团队协作流程.md)
- [项目状态](docs/项目状态.md)
- [2026-07-15 B 与 C 协助开发进展](docs/2026-07-15_B与C协助开发进展.md)
- [2026-07-16 案例扩展与观测可用性](docs/2026-07-16_案例扩展与观测可用性.md)
- [2026-07-16 证据复核与案例批准建议](docs/2026-07-16_证据复核与案例批准建议.md)
- [2026-07-16 阶段进展与正式批处理启动](docs/2026-07-16_阶段进展与正式批处理启动.md)
- [2026-07-17 高温冷偏差修正预注册方案与结果](docs/2026-07-17_高温冷偏差修正预注册方案.md)
- [2026-07-17 Neo4j 实机联调结果](docs/2026-07-17_Neo4j实机联调结果.md)
- [2026-07-17 灾害影响层描述性评估](docs/2026-07-17_灾害影响层描述性评估.md)
- [2026-07-17 v0.1.0 稳定研究原型发布说明](docs/2026-07-17_v0.1.0原型发布说明.md)
- [2026-07-18 高温 development 第二轮扩展预注册](docs/2026-07-18_高温development第二轮扩展预注册.md)
- [2026-07-18 高温第二轮 development 复验结果](docs/2026-07-18_高温第二轮development复验结果.md)
- [变更记录](docs/变更记录.md)
