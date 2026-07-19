# Agent 整合技术方案

## 两类报告必须隔离

完整链路分为预测与验证两条：

```text
GraphCast → MAZU-like → Risk JSON → 无真值预测图谱 → Forecast Agent → 预测报告锁定
                                                         ↓ 锁定后
2020观测/灾害影响真值 → evaluation图谱 → Verification Agent → 命中/漏报/误报报告
```

Forecast Agent不得读取同期或事后的气象观测、灾害影响、新闻来源、验证结果或同地区未来案例。Verification Agent只在预测结果已经锁定后使用，输出属于事后评估而不是预测。

## 默认入口：Forecast Agent v3

默认命令：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_agent_report.ps1 `
  -Provider deterministic
```

`run_agent_report.ps1`已经切换到`run_agent_forecast.ps1`，生成：

- `outputs/forecast_report.json`；
- `outputs/forecast_report.md`；
- `outputs/prediction_context_bundle.json`。

## 联合研究入口：Forecast Agent v4

当评估对象是完整的“风险规则＋图谱纠错”预测器时，使用：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_joint_pipeline_v2.ps1
```

`agent_joint_forecast_report_v4`不再把图谱永远限制为并列影子建议，而是读取已经SHA锁定的`joint_final_risk`。报告必须同时保留`base_risk_level`、`knowledge_triggered`和`joint_final_risk_level`，因此图谱如何改变结论仍可追溯。预测锁不含观测、案例角色、灾害影响或评分答案；Verification仍只能在预测锁定后运行。

暴雨当前为`research_candidate`，高温因未通过development全部门槛固定为`research_only_blocked`。两者的`formal_warning_allowed`均为false。旧Forecast v3用于复现上一轮影子方案，不再代表当前联合研究主线。

预测快照使用`prediction_kg_bundle_v2`，每份报告包含一个ForecastCase、ForecastWindow、Region、RiskAssessment、冻结Rule和候选ConsistencyRule；满足截止时间时还可包含context-only的StaticPriorProfile及PriorSource。快照结构明确禁止：

- `HistoricalEvent`；
- `Evidence`；
- `ImpactRecord`；
- `ObservationTruth`；
- `TruthRecord`；
- `VerificationResult`；
- Risk JSON中的`verification`字段；
- 事件角色、影响状态、伤亡、观测值和来源ID等真值属性。

报告使用`agent_forecast_report_v3`，必须保留Risk JSON的等级、分数、置信度和规则状态，并输出：

- 气象风险事实；
- 知识先验状态；
- 内部一致性冲突；
- 独立的关注级别；
- 影子纠错状态、影子建议风险和禁止覆盖基础风险标记；
- 时间边界与限制。

当前已接入符合起报时间边界的WorldClim 2.1 ADM1地形与月降水基线，状态为`knowledge_prior_status=context_only`、`knowledge_prior_risk=null`。它只能解释宏观背景，不能识别事件日。暴露度、脆弱性和可验证历史事件先验仍不可用，不得用同期2020真值替代。

## 保守一致性检查与影子纠错

`configs/knowledge_consistency_rules_v1.yaml`保留首个失败候选的审计记录。它只比较同一份预测中的气象证据：

```text
Risk JSON为low
+ 主降水指标低于阈值
+ 至少两个水汽/动力辅助条件达到支持阈值
→ possible_underestimation / watch
```

上式是原候选关注级别。该标记只表示“主指标和辅助指标存在值得复核的不一致”，不能证明模型错误，不能改写Risk JSON，也不是历史知识先验。development目标窗审计中，它把命中/漏报从3/2改善为5/0，但同时产生3个误关注、仅1个正确否定；因此状态已降为`development_gate_failed_diagnostic_only`。报告可保留冲突字段用于审计，但有效`attention_level`维持原风险对应级别，低风险为`routine`。

默认预测链现使用 `configs/knowledge_consistency_rules_v2.yaml`。统一development基准比较了无比值限制、0.40/0.50/0.60阈值和过程持续型共5组候选，选择更简单的单窗规则：

```text
冻结暴雨Risk JSON为low
+ 主降水指标达到medium阈值的至少50%
+ 至少一个主指标矛盾
+ 至少两个水汽/动力支持条件
→ conflict_flag=possible_underestimation
→ shadow_correction_status=triggered_not_activated
→ shadow_suggested_risk_level=medium
→ base_risk_level仍为low，effective_attention_level仍为routine
```

它在development中补回1个漏报窗且未新增对照误报，但增益只来自1个事件案例；既有独立集的非盲复用中没有触发，不能验证新候选。Forecast Agent必须把基础风险和影子建议并列报告，不得合成为一个更高的正式等级。只有取得至少2个不同事件案例的正确增益、零新增误报和新的前瞻/独立证据后，才允许讨论激活。

## 显式入口：Verification Agent v1

旧`kg_bundle_v1`包含2020真实事件、影响记录和来源证据，只能用于事后验证。显式命令为：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_agent_verification_report.ps1 `
  -Provider deterministic
```

其输出仍为`agent_report_v1`。旧的`heavy_rain_evaluation_bundle.json`、`formal_development_bundle.json`和历史报告继续保留作审计，但不再是默认预测报告输入。

## OpenAI运行时

- 框架：OpenAI Agents SDK for Python；
- 默认模型：`gpt-5.6-luna`；
- Guardrail失败时最多使用`gpt-5.6-terra`重试一次；
- 无API或显式选择确定性模式时生成同Schema的确定性报告；
- API Key只从环境变量或被Git忽略的`.env.agent.local`读取；
- Agent不访问Shell、不接受自由文件路径、不修改Neo4j或Risk JSON。

真实联调已经完成：Forecast Agent调用全部五个只读工具后生成`openai_luna`报告，Guardrail确认`truth_accessed=false`，报告未出现同期洪水、伤亡或新闻答案。

## Forecast Agent五个工具

- `get_forecast_risk`：返回剔除`verification`后的预测事实；
- `get_prediction_context`：返回预测窗口、区域、规则和知识截止时间；
- `get_knowledge_prior`：返回起报前静态上下文、来源和context-only边界；
- `get_consistency_check`：返回确定性候选冲突检查；
- `get_forecast_constraints`：返回真值封印与报告边界。

缺少任何一次调用都会拒绝输出。模型不能执行任意Cypher，也不能自己检索2020真值。

## 运行配置

安装可选依赖：

```powershell
pip install -e ".[agent]"
```

本地环境变量：

```powershell
$env:OPENAI_API_KEY = "仅保存于本机的Key"
$env:OPENAI_BASE_URL = "兼容OpenAI协议的/v1地址"
$env:SAUDI_WARNING_AGENT_API_MODE = "responses"
```

如果服务只兼容Chat Completions，可把API模式设为`chat_completions`。不得把密钥提交Git或写进文档。

## 当前边界

预测真值泄漏已经在结构、工具和自动测试三层阻断。静态地形与月气候背景已经完成，但它本身没有事件日判别力。v2影子纠错已接入完整预测报告链，却仍是development回顾性选择结果，不是正式纠错能力。后续应补充预测时可用的动态或更细空间知识，并在全新development证据上预注册比较“Risk JSON单独结果”和“Risk JSON＋图谱先验”；独立集不得参与规则选择。
