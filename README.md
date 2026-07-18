# Saudi Extreme Weather Warning

面向沙特阿拉伯强降水与高温/热浪的可追溯预警原型。项目把“气象预报是否正确”和“风险/灾害预警是否正确”分开验证，避免把规则开发数据误当作独立预报验证。

## 当前技术路线

```text
MAZU 2025 历史指标 → 分析分布并冻结风险规则

GraphCast 2020 历史预报 → MAZU-like 指标 → 已冻结的风险规则 → 风险 JSON
                                                        ├→ 无真值预测图谱 → Forecast Agent 报告
                                                        └→ 结果锁定后才连接 IMERG / SSOD / GHCN / 灾害记录
                                                                                 → 验证图谱 → Verification 报告
```

MAZU 2025 是开发和标定后半段流程的历史指标数据，不是未来预报模型。当前回放实验读取已预计算的 GraphCast 2020 历史预报；v1 不训练天气模型，也不自行运行完整 GraphCast。GraphCast 数据保持原生 `0.25 degree` 网格，绝不表述为 `0.1 degree` 预报能力。

## 真实项目状态（2026-07-18）

- **阶段版本已收束**：当前成果作为 `v0.1.0-prototype` 稳定研究原型发布；提供无需原始数据的一键验收、机器可读快照、正向案例和已知漏报案例。它不是实时业务预报服务。
- **已完成（成员 A）**：GraphCast → MAZU-like 主流程，以及 catalog 预检查、可恢复缓存、原子写入、NetCDF 自动验收、ADM1 摘要、SHA-256 溯源和一键交付；并协助完成 MAZU 2025 统计与 B 侧草案。
- **已完成的演示交接个例**：`2020-08-20T00:00:00Z` 的 lead024、lead048、lead072，位于 [`handoff/mazu_like/`](handoff/mazu_like/)；它仅是流程演示，不声明为已确认极端灾害事件。
- **观测、案例与证据已继续推进**：目录现有10个事件、6个对照和1个demo；IMERG/GHCN/SSOD筛选已完成；影响真值仍保持逐条复核和天气层/影响层分离。
- **案例已批准**：成员 A 在单人继续推进的工作方式下，已批准20个真实案例并冻结为15个development、5个independent_test；高温前瞻扩展没有打开独立高温案例。
- **A侧正式批处理与交付收尾已完成**：20个批准案例的240个GraphCast时次缓存齐全，加demo共252个；60份批准案例NetCDF加3份demo全部通过验收，ADM1摘要为9009行，63/63份交付文件均记录SHA-256。
- **B/C 归属任务已继续推进**：A 已代为完成 GHCN/IMERG 观测准备、对照筛选、灾害证据复核、案例批准材料和知识图谱开发骨架；这些产物可复验，但不表示 B/C 本人已验收。
- **B侧development配对已闭合**：15个development案例形成225/225条accepted配对，其中45条IMERG、180条NOAA SSODv2；GHCN缺少`OBS-TIME`，只作数值旁证。
- **development指标已分层生成**：12行IMERG与24行SSOD指标、24行高温时序均已生成；独立高温预报—观测结果未读取。
- **风险规则已按灾种分层推进**：暴雨v2达到development预设闸门后冻结；高温v2虽补足4事件/2对照和accepted观测，但目标窗召回仅0.142857、事件案例检出仅0.25，继续保持draft。
- **高温冷偏差修正已完成预注册复验**：6折留一案例修正的固定估计为`+2.280°C`，目标窗召回改善至3/7、事件案例检出改善至2/4，但仍未达到冻结门槛；没有读取独立高温案例，也没有根据结果降低阈值。
- **高温第二轮development扩展已完成A侧交付和配对**：仅凭SSOD观测锁定的`20200622_00`对照与`20200627_00`事件已形成6份NetCDF和36条accepted温度配对；扩展交叉验证输入已锁，尚未计算汇总结果，独立高温继续封存。
- **高温第二轮交叉验证仍为阻塞**：沿用原预注册方法后，目标窗召回提升至5/9、事件案例检出提升至3/5，对照特异度保持1.0，但前两项仍未达到0.60和2/3门槛；高温规则未冻结，独立高温未开启。
- **正式development链路已形成**：15份冻结暴雨Risk JSON、15份受控报告，以及69节点/98关系的图谱bundle均已生成并验收。
- **独立暴雨评估已锁定完成**：54/54条IMERG配对accepted；冻结P95门槛得到6命中、0漏报、0空报、12正确否定。结果样本较小，规则不得回调。
- **Neo4j本地实机联调已完成**：Community 2026.06.0精确导入综合暴雨bundle，87个节点、152条关系、6个约束及三组固定查询全部通过；这是development联调，不是生产部署。
- **Agent 已拆分为预测态与验证态**：默认入口生成 `agent_forecast_report_v2`，只能读取冻结 Risk JSON 和无真值 `prediction_kg_bundle_v2`；旧 `agent_report_v1` 仅用于结果锁定后的事后验证。`gpt-5.6-luna` 已真实生成一份 `truth_accessed=false` 的暴雨预测报告，但这不等同于模型气象能力已独立验证。
- **预测前静态知识已接入但仅限解释**：WorldClim 2.1的ADM1地形与1970–2000月降水基线已按`available_at`接入，当前 `knowledge_prior=context_only`、风险值为空。旧内部一致性候选虽补回2个漏报却对4个对照产生3个误关注，已降级为`development_gate_failed_diagnostic_only`；它可保留冲突记录，但默认关注级别不再从`routine`升为`watch`。
- **细空间预测诊断候选已复验并淘汰**：预注册的P99/最大值/超阈面积热点条件在15份development暴雨预测中触发0次，对两个漏报没有改善；漏报窗的预测最大值也低于5毫米，说明只更换P95聚合无法修复模型整片低估。该候选未接入Agent关注逻辑。
- **高温v4分层诊断已执行**：不改47/49°C阈值、不混入区域最大值、不使用已评估SA-08拟合；按lead中位偏差修正在同步观测天气真值上达到高温日4/6、非高温日8/9，优于pooled方法，只获得进入下一批全新prospective development的资格，高温规则仍为draft/blocked。
- **灾害影响层描述性评估已完成**：9条经复核正例合并为6个案例—区域单位，冻结中高风险覆盖5/6；没有可靠无影响负例，因此不能计算误报率、特异度或完整准确率。
- **唯一影响漏报已完成归因**：`20200501_00 / SA-09`的lead024为明确天气低估；lead048显示区域P95规则的局地尺度盲区并伴随天气低估。4个对照仍未取得合格无影响证据。
- **仍待正式完成**：补充新的高温development证据并在新预注册方案下继续研究偏差；补充可靠影响负例及更广泛影响证据。

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

成员 A 新增个例的批处理命令见 [成员 A 批处理说明](docs/成员A批处理说明.md)。成员 B/C 的任务和当前完成边界见 [团队协作流程](docs/团队协作流程.md)。

成员 A 的完整交付可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_a_delivery.ps1`；默认以版本化 demo catalog 复验现有三份 lead。当前批准案例位于 `configs/case_catalog_candidates.csv`，正式批处理必须保持冻结的 development/independent_test 划分。

成员 C 的开发交付可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_c_development.ps1`；它校验案例/真值、生成图谱 bundle 和示例报告，并运行 C 侧测试，不会启动或修改本地 Neo4j 服务。

冻结暴雨development链可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_frozen_development_pipeline.ps1`，它复验v2闸门、生成并验收15份Risk JSON、图谱bundle和15份报告；不会读取独立测试观测或启动Neo4j。

已锁定的独立暴雨链可使用 `powershell -ExecutionPolicy Bypass -File scripts/run_locked_independent_heavy_rain.ps1`复验；脚本会核对既有锁文件中的规则/观测SHA，不允许更换输入或回调规则。

## 仓库与数据边界

仓库保存代码、配置、文档、Schema、小型示例和体积可控的正式交接件。MAZU 全量指标、GraphCast 原始/裁剪缓存、IMERG/GHCN 原始文件、Neo4j 数据库和单文件超过 100 MB 的数据不得提交。规则详见 [交接目录说明](handoff/README.md)。

## 文档索引

- [统一技术路线](docs/统一技术路线_v1.md)
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
