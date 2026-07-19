"""Render one truth-free report from a locked joint-pipeline prediction."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


FORBIDDEN_TRUTH_COLUMNS = {
    "case_role",
    "observed_hot_day",
    "observed_tmax_degc",
    "observation_station_count",
    "candidate_outcome",
    "hits",
    "misses",
    "false_alarms",
}
RISK_LEVELS = {"low", "medium", "high"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _lock_reference(
    root: Path, split: str, hazard: str
) -> tuple[Path, str, str]:
    if split == "development":
        manifest_path = root / "manifests/joint_pipeline_selection_lock_v2.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        section = manifest["truth_free_development_prediction_locks"]
        key = "heavy_rain" if hazard == "heavy_rain" else "heatwave"
        return root / section[f"{key}_path"], section[f"{key}_sha256"], "retrospective_development"
    manifest_path = root / "manifests/joint_pipeline_full_chain_evaluation_v2.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    section = manifest["prediction_locks"]
    key = "heavy_rain" if hazard == "heavy_rain" else "heatwave"
    prediction_path = Path(section[f"{key}_path"])
    if not prediction_path.is_absolute():
        prediction_path = root / prediction_path
    return prediction_path, section[f"{key}_sha256"], "nonblind_existing_split_replay"


def _forecast_features(row: pd.Series, hazard: str) -> dict[str, Any]:
    if hazard == "heavy_rain":
        return {
            "primary_ratio": float(row["primary_ratio"]),
            "support_count": int(row["support_count"]),
        }
    return {
        "candidate_tmax_degc": float(row["candidate_tmax_degc"]),
        "hot_day_threshold_degc": float(row["hot_day_threshold_degc"]),
    }


def build_report(
    root: Path,
    hazard: str,
    split: str,
    case_id: str,
    region_id: str,
    lead_time_hours: int,
) -> dict[str, Any]:
    selection_path = root / "manifests/joint_pipeline_selection_lock_v2.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection_hash = _sha256(selection_path)
    if split == "independent_test":
        evaluation = json.loads(
            (root / "manifests/joint_pipeline_full_chain_evaluation_v2.json").read_text(
                encoding="utf-8"
            )
        )
        if evaluation["selection_lock_sha256"] != selection_hash:
            raise ValueError("independent replay and selection lock disagree")
    policy = yaml.safe_load(
        (root / "configs/joint_operating_policy_v2.yaml").read_text(encoding="utf-8")
    )
    prediction_path, expected_hash, evaluation_character = _lock_reference(
        root, split, hazard
    )
    actual_hash = _sha256(prediction_path)
    if actual_hash != expected_hash:
        raise ValueError("prediction lock hash mismatch")
    predictions = pd.read_csv(prediction_path)
    forbidden = FORBIDDEN_TRUTH_COLUMNS & set(predictions.columns)
    if forbidden:
        raise ValueError("truth fields found in forecast lock: " + ", ".join(sorted(forbidden)))
    match = predictions[
        predictions["case_id"].astype(str).eq(case_id)
        & predictions["region_id"].astype(str).eq(region_id)
        & predictions["lead_time_hours"].astype(int).eq(int(lead_time_hours))
    ]
    if len(match) != 1:
        raise ValueError(f"expected one locked prediction, found {len(match)}")
    row = match.iloc[0]
    selected = selection[hazard]["selected"]
    selected_rule = str(selected["method"])
    hazard_policy = policy["hazards"][hazard]
    configured_rule = hazard_policy.get("selected_joint_rule") or hazard_policy.get(
        "selected_best_available_joint_rule"
    )
    if configured_rule != selected_rule:
        raise ValueError("operating policy and selection lock disagree")
    if str(row["base_method"]) != str(selected["base_method"]):
        raise ValueError("prediction base method and selection lock disagree")
    if str(row["knowledge_mode"]) != str(selected["knowledge_mode"]):
        raise ValueError("prediction knowledge mode and selection lock disagree")

    base_risk = str(row["base_risk_level"])
    joint_risk = str(row["joint_final_risk_level"])
    triggered = _as_bool(row["knowledge_triggered"])
    passed = bool(selected["passes_all_gates"])
    operating_status = "research_candidate" if passed else "research_only_blocked"
    decision_change = "upgraded" if base_risk != joint_risk else "unchanged"
    if triggered and decision_change == "upgraded":
        reasoning = (
            f"图谱一致性规则已触发：{row['knowledge_mode']} 将基础风险从"
            f" {base_risk} 调整为 {joint_risk}。该调整只使用锁定预测特征，未读取同期真值。"
        )
    elif triggered:
        reasoning = (
            f"图谱一致性规则已触发，但基础规则已经给出 {base_risk}，"
            f"因此联合风险保持 {joint_risk}，没有重复升级。推理未读取同期真值。"
        )
    else:
        reasoning = (
            f"图谱一致性规则未触发，联合风险保持基础判断 {base_risk}；"
            "未使用同期观测或事后答案进行改写。"
        )
    gate_text = "已通过" if passed else "未通过"
    conclusion = (
        f"{case_id} / {region_id} / +{lead_time_hours}h 的 {hazard} 联合风险为"
        f" {joint_risk}。开发门槛{gate_text}，当前状态为 {operating_status}，"
        "不能直接视为正式业务预警。"
    )
    limitations = [
        "本报告只读取无真值预测锁；命中、漏报和误报只能在锁定后的验证阶段计算。",
        "联合候选是在已打开的development样本上回顾性选择，存在样本量小和选择偏差风险。",
    ]
    if split == "independent_test":
        limitations.append("该独立划分此前已经打开，本次属于非盲全链回放。")
    if hazard == "heatwave":
        limitations.append("高温没有独立对照案例，且最佳候选未通过development全部门槛。")
    else:
        limitations.append("暴雨图谱增益只来自一个development事件，独立回放中未触发纠错。")
    actions = ["保留基础风险与联合风险两列，供人工追溯图谱是否改变了结论。"]
    if hazard == "heatwave":
        actions.append("仅用于研究和人工复核；补充独立高温对照案例前不得启用正式预警。")
    else:
        actions.append("继续收集新的前瞻案例，重点验证图谱触发时是否稳定减少漏报且不新增误报。")
    report = {
        "schema_version": "agent_joint_forecast_report_v4",
        "report_mode": "joint_forecast",
        "truth_accessed": False,
        "dataset_split": split,
        "evaluation_character": evaluation_character,
        "hazard": hazard,
        "case_id": case_id,
        "region_id": region_id,
        "lead_time_hours": int(lead_time_hours),
        "selected_joint_rule": selected_rule,
        "base_method": str(row["base_method"]),
        "knowledge_mode": str(row["knowledge_mode"]),
        "base_risk_level": base_risk,
        "knowledge_triggered": triggered,
        "joint_final_risk_level": joint_risk,
        "decision_change": decision_change,
        "development_gate_passed": passed,
        "operating_status": operating_status,
        "formal_warning_allowed": False,
        "forecast_features": _forecast_features(row, hazard),
        "conclusion_zh": conclusion,
        "knowledge_reasoning_zh": reasoning,
        "limitations_zh": limitations,
        "recommended_actions_zh": actions,
        "provenance": {
            "prediction_lock_path": str(prediction_path.relative_to(root)).replace("\\", "/"),
            "prediction_lock_sha256": actual_hash,
            "selection_lock_path": str(selection_path.relative_to(root)).replace("\\", "/"),
            "selection_lock_sha256": selection_hash,
        },
    }
    errors = validate_report(report)
    if errors:
        raise ValueError("invalid joint report: " + "; ".join(errors))
    return report


def validate_report(report: dict[str, Any]) -> list[str]:
    """Validate decision invariants without adding a runtime JSON-Schema dependency."""
    errors: list[str] = []
    if report.get("schema_version") != "agent_joint_forecast_report_v4":
        errors.append("unexpected schema version")
    if report.get("report_mode") != "joint_forecast":
        errors.append("report mode must be joint_forecast")
    if report.get("truth_accessed") is not False:
        errors.append("forecast report must not access truth")
    base = report.get("base_risk_level")
    final = report.get("joint_final_risk_level")
    if base not in RISK_LEVELS or final not in RISK_LEVELS:
        errors.append("invalid risk level")
    expected_change = "unchanged" if base == final else "upgraded"
    if report.get("decision_change") != expected_change:
        errors.append("decision_change does not match risk levels")
    if report.get("formal_warning_allowed") is not False:
        errors.append("joint research report cannot authorize formal warning")
    passed = report.get("development_gate_passed") is True
    expected_status = "research_candidate" if passed else "research_only_blocked"
    if report.get("operating_status") != expected_status:
        errors.append("operating status does not match development gate")
    provenance = report.get("provenance", {})
    for key in ("prediction_lock_sha256", "selection_lock_sha256"):
        value = provenance.get(key)
        if not isinstance(value, str) or len(value) != 64:
            errors.append(f"invalid provenance hash: {key}")
    return errors


def render_markdown(report: dict[str, Any]) -> str:
    features = "\n".join(
        f"- `{key}`：`{value}`" for key, value in report["forecast_features"].items()
    )
    limitations = "\n".join(f"- {item}" for item in report["limitations_zh"])
    actions = "\n".join(f"- {item}" for item in report["recommended_actions_zh"])
    return f"""# 极端天气联合预测报告（无真值模式）

> 本报告的联合结论由基础气象规则与预测前图谱一致性规则共同产生；`truth_accessed=false`。

## 综合结论

{report['conclusion_zh']}

## 决策链

- 案例：`{report['case_id']}`
- 区域：`{report['region_id']}`
- 时效：`+{report['lead_time_hours']}h`
- 灾种：`{report['hazard']}`
- 基础方法：`{report['base_method']}`
- 基础风险：`{report['base_risk_level']}`
- 图谱规则：`{report['knowledge_mode']}`
- 图谱触发：`{str(report['knowledge_triggered']).lower()}`
- 联合最终风险：`{report['joint_final_risk_level']}`
- 决策变化：`{report['decision_change']}`
- 开发门槛通过：`{str(report['development_gate_passed']).lower()}`
- 运行状态：`{report['operating_status']}`
- 正式预警许可：`false`

## 预测特征

{features}

## 图谱推理说明

{report['knowledge_reasoning_zh']}

## 限制

{limitations}

## 建议

{actions}

## 溯源

- 预测锁：`{report['provenance']['prediction_lock_path']}`
- 预测锁 SHA-256：`{report['provenance']['prediction_lock_sha256']}`
- 选择锁：`{report['provenance']['selection_lock_path']}`
- 选择锁 SHA-256：`{report['provenance']['selection_lock_sha256']}`
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--hazard", choices=["heavy_rain", "heatwave"], required=True)
    parser.add_argument("--split", choices=["development", "independent_test"], required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--region-id", required=True)
    parser.add_argument("--lead-time-hours", type=int, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    report = build_report(
        root,
        args.hazard,
        args.split,
        args.case_id,
        args.region_id,
        args.lead_time_hours,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.output_markdown.write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {args.output_json}")
    print(f"wrote {args.output_markdown}")
    print("truth_accessed=false")


if __name__ == "__main__":
    main()
