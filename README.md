# Saudi Extreme Weather Warning

面向沙特阿拉伯强降水与高温/热浪的可追溯预警原型。项目把“气象预报是否正确”和“风险/灾害预警是否正确”分开验证，避免把规则开发数据误当作独立预报验证。

## 当前技术路线

```text
MAZU 2025 历史指标 → 分析分布并冻结风险规则 → 风险 JSON → 图谱/报告

GraphCast 2020 历史预报 → MAZU-like 指标 → 已冻结的风险规则 → 风险 JSON
                                      ↓
                         IMERG / GHCN / 灾害记录分层验证
```

MAZU 2025 是开发和标定后半段流程的历史指标数据，不是未来预报模型。当前回放实验读取已预计算的 GraphCast 2020 历史预报；v1 不训练天气模型，也不自行运行完整 GraphCast。GraphCast 数据保持原生 `0.25 degree` 网格，绝不表述为 `0.1 degree` 预报能力。

## 真实项目状态（2026-07-16）

- **已完成（成员 A）**：GraphCast → MAZU-like 主流程，以及 catalog 预检查、可恢复缓存、原子写入、NetCDF 自动验收、ADM1 摘要、SHA-256 溯源和一键交付；并协助完成 MAZU 2025 统计与 B 侧草案。
- **已完成的演示交接个例**：`2020-08-20T00:00:00Z` 的 lead024、lead048、lead072，位于 [`handoff/mazu_like/`](handoff/mazu_like/)；它仅是流程演示，不声明为已确认极端灾害事件。
- **观测、案例与证据已继续推进**：候选目录已扩展为 7 个事件、5 个对照和 1 个 demo；GHCN/IMERG 候选筛选已完成；12 条影响真值已逐条复核，并形成天气层、影响层和数据集划分批准建议。
- **案例已批准**：成员 A 在单人继续推进的工作方式下，已按审计建议批准 12 个真实案例并冻结为 7 个 development、5 个 independent_test；该决定不虚构为其他成员分别验收。
- **A侧正式批处理与交付收尾已完成**：12 个批准案例的144个 GraphCast时次缓存齐全，36份24/48/72h MAZU-like NetCDF全部通过契约验收；ADM1区域摘要和39份文件（含3份demo）的SHA-256交付清单已重建。
- **B/C 归属任务已继续推进**：A 已代为完成 GHCN/IMERG 观测准备、对照筛选、灾害证据复核、案例批准材料和知识图谱开发骨架；这些产物可复验，但不表示 B/C 本人已验收。
- **B侧development配对已闭合**：7个development案例形成81/81条配对；45条IMERG记录accepted、36条GHCN记录因日界线未知保持provisional。之后仅在暴雨v2冻结后打开4个独立暴雨案例，高温独立案例继续封存。
- **development连续指标已分层生成**：12行IMERG accepted降水指标可用于开发检查；24行GHCN温度结果明确标为provisional非正式诊断，分类技能与热浪序列未提前计算。
- **风险规则已按灾种分层推进**：暴雨v2达到development预设闸门后冻结；高温v2因仅1组事件/对照且GHCN仍provisional，继续保持draft。
- **正式development链路已形成**：15份冻结暴雨Risk JSON、15份受控报告，以及69节点/98关系的图谱bundle均已生成并验收。
- **独立暴雨评估已锁定完成**：54/54条IMERG配对accepted；冻结P95门槛得到6命中、0漏报、0空报、12正确否定。结果样本较小，规则不得回调。
- **仍待正式完成**：解决高温样本/QC后再冻结；Neo4j实机导入及最终影响层评估仍未完成。

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

交接顺序是：A 写入 `handoff/mazu_like/`；B 读取 NetCDF 并写入 `handoff/risk_results/`；C 读取风险 JSON，结合本地观测和灾害资料建立宏观图谱与报告。字段与语义以 [数据交接契约](docs/数据交接契约.md) 为准。

每位成员的完成状态、输入、详细任务、正式输出和不负责事项见[三人分工与协作流程](docs/团队协作流程.md)。任务按技术归属记入 A/B/C；A 代办的 B/C 产物会明确标注实际执行人，不能视为成员 B/C 已亲自验收或已部署。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
$env:PYTHONPATH = "$PWD\src"
python -m pytest -q
```

成员 A 新增个例的批处理命令见 [成员 A 批处理说明](docs/成员A批处理说明.md)。成员 B/C 的任务和当前完成边界见 [团队协作流程](docs/团队协作流程.md)。

成员 A 的完整交付可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_a_delivery.ps1`；默认以版本化 demo catalog 复验现有三份 lead。当前批准案例位于 `configs/case_catalog_candidates.csv`，正式批处理必须保持冻结的 development/independent_test 划分。

成员 C 的开发交付可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_c_development.ps1`；它校验案例/真值、生成图谱 bundle 和示例报告，并运行 C 侧测试，不会启动或修改本地 Neo4j 服务。

冻结暴雨development链可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_frozen_development_pipeline.ps1`，它复验v2闸门、生成并验收15份Risk JSON、图谱bundle和15份报告；不会读取独立测试观测或启动Neo4j。

已锁定的独立暴雨链可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_locked_independent_heavy_rain.ps1`复验；脚本会核对既有锁文件中的规则/观测SHA，不允许更换输入或回调规则。

## 仓库与数据边界

仓库保存代码、配置、文档、Schema、小型示例和体积可控的正式交接件。MAZU 全量指标、GraphCast 原始/裁剪缓存、IMERG/GHCN 原始文件、Neo4j 数据库和单文件超过 100 MB 的数据不得提交。规则详见 [交接目录说明](handoff/README.md)。

## 文档索引

- [统一技术路线](docs/统一技术路线_v1.md)
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
- [变更记录](docs/变更记录.md)
