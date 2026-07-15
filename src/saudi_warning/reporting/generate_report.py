"""Generate a controlled Markdown report from one Risk JSON result.

This module is intentionally template-based: it cannot invent facts or alter the
score assigned by member B.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from saudi_warning.risk.validation import load_region_ids, validate_result


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _display(value: Any) -> str:
    if value is None or value == "":
        return "未提供"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _evidence_lines(items: list[dict[str, Any]], empty_text: str) -> list[str]:
    if not items:
        return [f"- {empty_text}"]
    lines = []
    for item in items:
        indicator = _display(item.get("indicator"))
        value = _display(item.get("value"))
        threshold = _display(item.get("threshold"))
        role = _display(item.get("role"))
        lines.append(f"- `{indicator}`：值={value}，阈值={threshold}，作用={role}")
    return lines


def render_report(
    risk: dict[str, Any],
    region: dict[str, str],
    impact_records: list[dict[str, str]],
    sources: dict[str, dict[str, str]],
) -> str:
    """Render one report without changing or inferring member-B output."""

    status = risk.get("rule_status", "unknown")
    disclosure = {
        "frozen": "冻结规则结果；仍须结合验证状态和证据使用。",
        "draft": "草案规则结果，仅供内部联调，不能作为正式预警。",
        "example": "虚构契约示例，仅供接口联调，不能作为真实预警或效果结论。",
    }.get(status, "规则状态未知，不能作为正式预警。")
    lines = [
        "# 沙特极端天气风险报告",
        "",
        f"> **状态声明：{disclosure}**",
        "",
        "## 风险结论（原样转述成员 B 输出）",
        "",
        f"- 案例：`{risk['case_id']}`",
        f"- 区域：{region['region_name_en']} / {region['region_name_ar']} "
        f"(`{risk['region_id']}`)",
        f"- 灾种：`{risk['hazard']}`",
        f"- 时效：{risk['lead_time_hours']} 小时",
        f"- 有效时间：{risk['valid_start_time']} 至 {risk['valid_end_time']}",
        f"- 风险等级：`{risk['risk_level']}`",
        f"- 风险分数：`{risk['risk_score']}`",
        f"- 置信度：`{risk['confidence']}`",
        f"- 规则：`{risk['rule_id']}`（`{status}`）",
        "",
        "## 指标摘要",
        "",
    ]
    for key, value in sorted(risk["indicator_summary"].items()):
        lines.append(f"- `{key}`：{_display(value)}")
    lines.extend(["", "## 支持证据", ""])
    lines.extend(_evidence_lines(risk["supporting_evidence"], "成员 B 输出中没有支持证据条目。"))
    lines.extend(["", "## 反向证据", ""])
    lines.extend(
        _evidence_lines(risk["contradicting_evidence"], "成员 B 输出中没有反向证据条目。")
    )
    lines.extend(["", "## 缺失证据", ""])
    lines.extend(_evidence_lines(risk["missing_evidence"], "成员 B 输出中没有缺失证据条目。"))
    lines.extend(["", "## 灾害影响资料（成员 C）", ""])
    if not impact_records:
        lines.append("- 当前没有与该案例、区域和灾种匹配的影响记录；状态应视为 `unknown`。")
    for record in impact_records:
        source = sources.get(record["source_id"], {})
        lines.extend(
            [
                f"- `{record['impact_status']}` / `{record['impact_category']}`："
                f"{record['impact_description_zh']}",
                f"  - 复核状态：`{record['review_status']}`；证据等级："
                f"`{record['evidence_tier']}`",
                f"  - 来源：[{source.get('publisher', record['source_id'])}]"
                f"({source.get('url', '')})",
            ]
        )
    verification = risk.get("verification")
    lines.extend(["", "## 验证状态", ""])
    if verification is None:
        lines.append("- 尚无成员 B 的天气层验证结果；不能据此宣称预报准确。")
    else:
        lines.append(f"- 成员 B 验证摘要：`{json.dumps(verification, ensure_ascii=False)}`")
    lines.extend(
        [
            "",
            "## 数据来源与边界",
            "",
            f"- 风险输入：`{risk['source_file']}`",
            f"- 区域边界代表年份：{region.get('boundary_year_represented', 'unknown')}；"
            "当前边界不是最新官方法定边界声明。",
            "- 报告由固定模板生成，没有重新计算气象指标、风险分数或阈值。",
            "",
        ]
    )
    return "\n".join(lines)


def validate_report_mode(risk: dict[str, Any], mode: str) -> None:
    """Prevent non-frozen results from entering the formal reporting path."""

    if mode not in {"development", "formal"}:
        raise ValueError(f"unsupported report mode: {mode}")
    if mode == "formal" and risk.get("rule_status") != "frozen":
        raise ValueError("formal reports require rule_status=frozen")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--risk", type=Path, required=True)
    parser.add_argument("--regions", type=Path, default=Path("configs/region_registry.csv"))
    parser.add_argument(
        "--truth",
        type=Path,
        default=Path("handoff/disaster_truth/disaster_impact_truth.csv"),
    )
    parser.add_argument(
        "--sources", type=Path, default=Path("handoff/disaster_truth/source_catalog.csv")
    )
    parser.add_argument("--schema", type=Path, default=Path("schemas/risk_result.schema.json"))
    parser.add_argument("--mode", choices=["development", "formal"], default="development")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    risk = json.loads(args.risk.read_text(encoding="utf-8"))
    try:
        validate_report_mode(risk, args.mode)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    errors = validate_result(risk, schema, load_region_ids(args.regions))
    if errors:
        raise SystemExit("invalid Risk JSON:\n- " + "\n- ".join(errors))
    regions = {row["region_id"]: row for row in _read_csv(args.regions)}
    sources = {row["source_id"]: row for row in _read_csv(args.sources)}
    base_case_id = risk["case_id"].removesuffix(f"_{risk['lead_time_hours']:03d}")
    impacts = [
        row
        for row in _read_csv(args.truth)
        if row["case_id"] == base_case_id
        and row["region_id"] == risk["region_id"]
        and row["hazard"] == risk["hazard"]
    ]
    report = render_report(risk, regions[risk["region_id"]], impacts, sources)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
