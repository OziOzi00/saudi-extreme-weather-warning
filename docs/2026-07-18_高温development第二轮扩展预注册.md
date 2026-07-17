# 2026-07-18 高温 development 第二轮扩展预注册

## 结论

在不读取新增 GraphCast 预报的前提下，使用已经版本化的 NOAA SSODv2 2020 年沙特区域日摘要，锁定一组新的 SA-04 高温事件—对照配对：

| case_id | 角色 | 目标UTC窗口 | SSOD station_max | 当前状态 |
| --- | --- | --- | --- | --- |
| `20200622_00` | control | 2020-06-23 至 06-25 | 44.0 / 44.1 / 44.8°C | 预注册，等待预报 |
| `20200627_00` | event | 2020-06-28 至 06-30 | 47.0 / 48.0 / 47.0°C | 预注册，等待预报 |

两者逐日均至少有4个站点，满足第一轮已使用的“事件连续三日不低于47°C、对照连续三日不高于45°C、至少2站”的观测筛选规则。两个起报日期均不在现有案例目录中，锁定时本地没有相应 GraphCast 缓存或 MAZU-like 输出。

## 为什么只新增这一组

全年SSOD筛选还能找到SA-08和SA-12的高温窗口，但大部分与现有7月development热过程重复，或落入`20200729_00`独立高温案例前后7天的封存区。把这些连续窗口当成多个独立事件会制造伪重复并夸大样本量，因此本轮不采用。

`2020-08-21`至`08-23`也满足SA-04事件门槛，但对应的`20200820_00`已经作为demo读取过GraphCast结果，不能再伪装成预报盲选案例。本轮保留它的demo身份，不计入新的预注册证据。

## 锁定边界

- SSOD区域日摘要和基线案例目录的SHA-256已写入锁文件；
- 新案例只属于`development`，不得进入独立测试；
- 独立高温案例继续封存，未读取其配对或风险结果；
- 未修改47°C/49°C阈值、偏差修正方法或任何暴雨冻结规则；
- 当前只完成观测先验选择，不能声称新增案例已跑通或高温规则性能提高。

机器可读文件：

- `manifests/heatwave_development_expansion_v2_lock.json`；
- `manifests/heatwave_development_expansion_v2_selection.csv`；
- `configs/heatwave_development_expansion_v2_catalog.csv`。

运行以下命令可复核选择而不读取GraphCast：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m saudi_warning.verification.heatwave_expansion
```

下一道闸门是按锁定catalog下载两个案例的6–72小时GraphCast缓存、生成6份MAZU-like文件并完成A侧验收。只有交付通过后，才能在新的预注册交叉验证方案下重新估计development性能。
