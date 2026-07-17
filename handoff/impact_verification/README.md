# 灾害影响层描述性评估

`positive_impact_units.csv`只包含`reviewed + impact_status=yes`的“案例×区域×灾种”单位，并把同一单位的多条影响记录合并，避免将死亡、受伤、住房或交通等多个类别重复计算为多个事件。

命中定义为：冻结Risk JSON的有效窗与记录的影响时段存在实际重叠，且风险等级为`medium`或`high`。边界相接但没有时间交集不算重叠。

当前真值表没有任何经复核的`impact_status=no`记录，所以本目录只能报告已知正例覆盖率，不能计算精确率、特异度或误报率。`unknown`表示资料不足，全部排除。天气层`independent_test`案例在选择时已经使用已知影响资料，因此其影响覆盖结果也不是盲测。

机器汇总见`../../manifests/impact_layer_assessment.json`，复验命令：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_impact_evaluation.ps1
```
