# 高温 v3 前瞻 development 预注册

## 状态

本文件记录在读取新增 GraphCast 预报前完成的观测先行锁定。当前仍是 `development`，高温规则仍为 `draft/blocked`，独立高温集仍未打开。

候选聚合权重 `0.6` 来自既有 development 的回顾性敏感性分析，因此候选方法本身不是盲选；但下面两个新案例是在没有读取对应 GraphCast 预报的前提下，仅使用 SSOD 观测选出的，可用于前瞻式 development 检查。

## 锁定案例

| 角色 | case_id | 区域 | SSOD 目标日期 | 站点最大温度 |
| --- | --- | --- | --- | --- |
| 对照 | `20200623_00` | SA-08 Northern Borders | 2020-06-24～26 | 42.0 / 42.0 / 44.1°C |
| 事件 | `20200702_00` | SA-08 Northern Borders | 2020-07-03～05 | 47.0 / 47.0 / 47.4°C |

两个窗口每天都有 3 个 SSOD 站点。事件连续三天不低于 47°C，对照连续三天不高于 45°C。二者不在现有案例目录中，本地在锁定时也没有对应的 GraphCast 缓存、MAZU-like NetCDF 或正式交付文件。

选择对独立高温事件采用 14 天禁运缓冲，未使用 `20200729_00` 或其邻近过程。

## 锁定候选

候选温度为：

`空间P95 + 0.6 ×（区域最大值 - 空间P95）+ 2.305557°C`

以下内容保持不变：

- v2 的区域/季节高温与严重高温阈值；
- 暖夜辅助证据；
- 连续日风险分类；
- 偏差订正数值及 ±4°C 上限；
- 独立集不能调参的限制。

本次新案例不能再次用于搜索权重。若失败，必须保持 `blocked`，不能在这两个案例上尝试 0.5、0.75 或其他权重。

## 前瞻门槛

新事件预计有两个目标 lead，新对照也有两个目标 lead：

- 事件目标窗必须命中 2/2；
- 观测高温目标窗必须命中 2/2；
- 对照目标窗必须正确否定 2/2；
- 不允许修改阈值、偏差订正或连续日定义。

即使通过，也只允许把候选并入全部 development 交叉验证，不能仅凭一组新事件/对照冻结规则或打开独立集。

## 机器可读锁

- 选择清单：`manifests/heatwave_v3_prospective_selection.csv`；
- 候选配置：`configs/heatwave_v3_prospective_candidate.yaml`；
- 批处理目录：`configs/heatwave_v3_prospective_batch_catalog.csv`；
- 输入 SHA 与状态锁：`manifests/heatwave_v3_prospective_lock.json`；
- 验收器：`python -m saudi_warning.verification.heatwave_v3_prospective`。

必须先提交并推送上述锁，再允许读取两个新增案例的 GraphCast 预报。
