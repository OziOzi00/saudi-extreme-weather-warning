# 区域参考数据

`saudi_adm1_geoboundaries_2017.geojson` 是项目统一的沙特 ADM1 区域边界，供 MAZU 区域统计、Risk JSON 的 `region_id` 和后续图谱使用。

## 来源与许可

- 数据集：geoBoundaries `gbOpen`，边界 ID `SAU-ADM1-25081817`。
- 数据代表年份：2017；构建日期：2023-12-12。
- 原始来源元数据：OpenStreetMap、Wambacher。
- 许可：Open Data Commons Open Database License 1.0（ODbL 1.0）。
- API：<https://www.geoboundaries.org/api/current/gbOpen/SAU/ADM1/>。
- 固定下载版本：geoBoundaries Git 提交 `9469f09`。
- 原始文件 SHA-256：`75abcfd5a61790e5e505974f04cbd1d869e58d81b6faba039b000987e659e840`。

项目仅标准化属性名，几何保持来源文件不变。使用、修改或再分发时必须保留来源和 ODbL 署名要求。

## 项目字段

- `region_id`：采用来源提供的 ISO 3166-2 风格代码，如 `SA-01`；这是跨成员唯一标识。
- `region_name_en`：来源英文名称。
- `region_name_ar`：目前为空，待成员 C 根据可靠来源核定。
- `source_shape_id`：geoBoundaries 的原始要素标识。

该数据适合项目原型和区域聚合，但不是沙特政府最新法定边界。后续替换边界时必须保持 `region_id` 兼容、记录版本并重新生成区域统计。
