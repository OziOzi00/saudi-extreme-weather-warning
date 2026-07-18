# 2026-07-18 高温第二轮 development 复验结果

## 结论

在`heatwave_bias_correction_cv_v2_20260718`锁定后，使用8个高温development案例执行留一案例加性中位误差修正。结果较上一轮改善，但仍未达到预注册门槛，因此结论继续为`blocked`，高温规则保持`draft`，独立高温案例继续封存。

| 指标 | 第一轮CV | 第二轮扩展CV | 门槛 |
| --- | ---: | ---: | ---: |
| 事件目标窗召回 | 3/7 = 0.428571 | 5/9 = 0.555556 | ≥ 0.60 |
| 对照目标窗特异度 | 4/4 = 1.0 | 6/6 = 1.0 | ≥ 0.80 |
| 事件案例检出 | 2/4 = 0.50 | 3/5 = 0.60 | ≥ 0.666667 |
| 对照案例拒绝 | 2/2 = 1.0 | 3/3 = 1.0 | = 1.0 |

第二轮共8折、24条校准配对，每折使用其余7个案例。折内修正量介于`+2.156°C`和`+2.459°C`，全development固定估计为`+2.306°C`，没有触及±4°C上限。

## 时序与边界

第二轮两个新增日期是在读取对应GraphCast前凭SSOD观测锁定并推送主线的。新增配对生成后，沿用第一轮已经预注册的估计器、47/49°C阈值、成功门槛和修正上限；扩展输入散列又在计算汇总CV前提交到主线。由于具体新配对数值在第二个锁提交前已经形成，本结果仍属于development方法研究，不能包装成独立盲测。

运行器最初被旧的“恰好11个development案例”硬编码安全检查挡住，且在产生结果前退出。该检查改为只接受approved development，再由CV锁强制案例集合精确一致；正式暴雨输出仍有独立的15份结果数量闸门。

机器可读产物：

- `configs/heatwave_bias_correction_cv_v2.yaml`；
- `handoff/weather_verification/heatwave_bias_cv_v2_pairs.csv`；
- `handoff/risk_dry_runs/heatwave_bias_cv_v2_rule_review.csv`；
- `manifests/heatwave_bias_cv_v2_assessment.csv`。

不得根据本轮结果降低阈值、改变门槛或打开独立高温。若继续提高高温能力，需要新的预报档案或不同年份/地区的独立development热过程，而不是继续从同一2020年连续高温窗口中拆分伪样本。
