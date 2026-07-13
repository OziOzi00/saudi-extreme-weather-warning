# 协作开发说明

## 分支与提交

- `main` 保持可运行，只通过 Pull Request 合并。
- 分支采用 `feature/<成员>-<主题>` 或 `fix/<主题>`。
- 提交信息使用简洁动词开头，例如：`feat: add GraphCast case loader`。

## 代码约定

- Python 3.11+；公共函数必须有类型标注和简要 docstring。
- 读写 NetCDF、JSON 前后都应调用共享校验函数。
- 不把绝对路径、账号、令牌、下载数据写入代码或配置。

## 共享接口变更

以下文件是跨成员接口，改动前需在 PR 说明兼容性：

- `docs/data_contract.md`
- `configs/indicator_mapping.yaml`
- `configs/heavy_rain_rules_v1.yaml`
- `configs/heatwave_rules_v1.yaml`
- `src/saudi_warning/common/models.py`

## 大文件

任何 NetCDF、Zarr、GRIB、PDF 和原始观测数据都不提交。需要复现时，在 PR 写清数据来源、时间范围、变量和运行命令。
