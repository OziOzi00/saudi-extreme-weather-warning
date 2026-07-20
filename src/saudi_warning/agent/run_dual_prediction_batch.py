"""Batch the complete joint pipeline and add a separately scored LLM advisory forecast."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from scripts.summarize_mazu_like_adm1 import summarize_file
from saudi_warning.agent.dual_prediction_runtime import generate_dual_prediction_report
from saudi_warning.agent.run_joint_live_report import _generation_mode
from saudi_warning.forecasting.run_batch import CaseRecord, output_paths, process_case
from saudi_warning.forecasting.validation import validate_mazu_like_sequence
from saudi_warning.knowledge_graph.joint_runtime import (
    prediction_rows,
    query_joint_context,
    sha256,
    upsert_joint_predictions,
)
from saudi_warning.orchestration.joint_inference import build_runtime_prediction_lock
from saudi_warning.risk.benchmark_integrated_candidates import (
    heatwave_candidate_rows,
    load_heatwave_development,
)
from saudi_warning.risk.select_joint_pipeline import apply_locked_heatwave_candidate


GROUPS = {
    ("heavy_rain", "development"): (
        "handoff/model_selection/joint_v2/locked_development_joint_heavy_rain_predictions.csv",
        "handoff/model_selection/joint_v2/selected_joint_heavy_rain_development_details.csv",
    ),
    ("heavy_rain", "independent_test"): (
        "handoff/model_selection/joint_v2/locked_joint_heavy_rain_predictions.csv",
        "handoff/model_selection/joint_v2/independent_joint_heavy_rain_details.csv",
    ),
    ("heatwave", "development"): (
        "handoff/model_selection/joint_v2/locked_development_joint_heatwave_predictions.csv",
        "handoff/model_selection/joint_v2/selected_joint_heatwave_development_details.csv",
    ),
    ("heatwave", "independent_test"): (
        "handoff/model_selection/joint_v2/locked_joint_heatwave_predictions.csv",
        "handoff/model_selection/joint_v2/independent_joint_heatwave_details.csv",
    ),
}
STAGES = (
    "materialize_and_validate_forecasts",
    "rebuild_adm1_summaries",
    "replay_system_predictions",
    "publish_neo4j",
    "generate_dual_reports",
    "lock_llm_advisories",
    "post_lock_verification",
    "finalize",
)
RISK_LEVELS = {"low", "medium", "high"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


class DualBatch:
    def __init__(
        self,
        root: Path,
        output_dir: Path,
        rain_model: str,
        heat_model: str,
        fallback_model: str,
    ):
        self.root = root.resolve()
        self.output_dir = output_dir if output_dir.is_absolute() else self.root / output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.output_dir / "batch_state.json"
        self.rain_model = rain_model
        self.heat_model = heat_model
        self.fallback_model = fallback_model
        self.selection_path = self.root / "manifests/joint_pipeline_selection_lock_v2.json"
        self.selection = _load_json(self.selection_path)
        if not self.state_path.exists():
            _write_json(
                self.state_path,
                {
                    "schema_version": "dual_prediction_batch_state_v1",
                    "status": "pending",
                    "truth_accessed_during_prediction": False,
                    "stages": {stage: "pending" for stage in STAGES},
                    "created_at": _utc_now(),
                    "updated_at": _utc_now(),
                },
            )

    def _state(self) -> dict[str, Any]:
        return _load_json(self.state_path)

    def _set_stage(self, stage: str, status: str, result: Any | None = None) -> None:
        state = self._state()
        state["status"] = "running" if status != "failed" else "failed"
        state["stages"][stage] = status
        state["updated_at"] = _utc_now()
        if result is not None:
            state.setdefault("stage_results", {})[stage] = result
        _write_json(self.state_path, state)

    def run(self) -> dict[str, Any]:
        handlers = {
            "materialize_and_validate_forecasts": self._materialize,
            "rebuild_adm1_summaries": self._summarize,
            "replay_system_predictions": self._replay,
            "publish_neo4j": self._publish,
            "generate_dual_reports": self._reports,
            "lock_llm_advisories": self._lock_advisories,
            "post_lock_verification": self._verify,
            "finalize": self._finalize,
        }
        for stage in STAGES:
            if self._state()["stages"][stage] == "completed":
                continue
            self._set_stage(stage, "running")
            try:
                result = handlers[stage]()
            except Exception as exc:
                self._set_stage(
                    stage,
                    "failed",
                    {"error_type": type(exc).__name__, "error": str(exc)},
                )
                raise
            self._set_stage(stage, "completed", result)
        state = self._state()
        state["status"] = "complete"
        state["updated_at"] = _utc_now()
        _write_json(self.state_path, state)
        return state

    def _source_units(self) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for (hazard, split), (prediction, _) in GROUPS.items():
            frame = pd.read_csv(self.root / prediction)[["case_id", "region_id"]].drop_duplicates()
            frame["hazard"] = hazard
            frame["dataset_split"] = split
            frames.append(frame)
        return pd.concat(frames, ignore_index=True).sort_values(
            ["hazard", "dataset_split", "case_id", "region_id"]
        )

    def _source_summaries(self) -> pd.DataFrame:
        paths = [
            self.root / "handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv",
            self.root / "handoff/region_summaries/heatwave_v5_2018_adm1_indicator_summaries.csv",
        ]
        return pd.concat([pd.read_csv(path) for path in paths], ignore_index=True)

    def _materialize(self) -> dict[str, Any]:
        summaries = self._source_summaries()
        units = self._source_units()
        cases = sorted(set(units["case_id"].astype(str)))
        results: list[dict[str, Any]] = []
        for case_id in cases:
            match = summaries[
                pd.to_datetime(summaries["initial_time"], utc=True)
                .dt.strftime("%Y%m%d_%H")
                .eq(case_id)
            ]
            if match.empty:
                raise ValueError(f"missing initial time for {case_id}")
            initial_time = str(match.iloc[0]["initial_time"])
            cache_year = pd.Timestamp(initial_time).year
            status, paths, message = process_case(
                CaseRecord(case_id=case_id, initial_time=initial_time),
                self.root / f"data/raw/graphcast_{cache_year}",
                self.root / "handoff/mazu_like",
                retries=3,
                timeout_seconds=1800,
            )
            errors = validate_mazu_like_sequence(list(paths.values()))
            if errors:
                raise ValueError(f"{case_id} sequence invalid: {' | '.join(errors)}")
            results.append(
                {
                    "case_id": case_id,
                    "status": status,
                    "message": message,
                    "files": [path.relative_to(self.root).as_posix() for path in paths.values()],
                    "sha256": [_hash(path) for path in paths.values()],
                }
            )
        _write_json(self.output_dir / "forecast_materialization.json", results)
        return {"case_count": len(cases), "netcdf_count": len(cases) * 3}

    def _summarize(self) -> dict[str, Any]:
        units = self._source_units()
        source = self._source_summaries()
        with (self.root / "configs/region_registry.csv").open(
            encoding="utf-8", newline=""
        ) as stream:
            registry = {row["region_id"]: row["region_name_en"] for row in csv.DictReader(stream)}
        rows: list[dict[str, Any]] = []
        for case_id, case_units in units.groupby("case_id"):
            stamp = str(case_id)
            initial = source[
                pd.to_datetime(source["initial_time"], utc=True).dt.strftime("%Y%m%d_%H").eq(stamp)
            ].iloc[0]["initial_time"]
            paths = output_paths(self.root / "handoff/mazu_like", str(initial))
            selected_regions = set(case_units["region_id"].astype(str))
            for path in paths.values():
                rows.extend(
                    row
                    for row in summarize_file(
                        path,
                        self.root / "data/reference/saudi_adm1_geoboundaries_2017.geojson",
                        registry,
                    )
                    if str(row["region_id"]) in selected_regions
                )
        frame = pd.DataFrame(rows).drop_duplicates(
            ["initial_time", "lead_time_hours", "region_id", "indicator"]
        )
        output = self.output_dir / "adm1_full_process_data.csv"
        frame.to_csv(output, index=False, lineterminator="\n")
        expected = len(units) * 3 * 11
        if len(frame) != expected:
            raise ValueError(f"expected {expected} full-process rows, found {len(frame)}")
        return {"rows": len(frame), "units": len(units), "sha256": _hash(output)}

    def _development_heat_lock(self) -> pd.DataFrame:
        selected = self.selection["heatwave"]["selected"]
        search = yaml.safe_load(
            (self.root / "configs/joint_pipeline_candidate_search_v2.yaml").read_text(
                encoding="utf-8"
            )
        )
        config = yaml.safe_load(
            (self.root / search["heatwave"]["base_config"]).read_text(encoding="utf-8")
        )
        base = heatwave_candidate_rows(load_heatwave_development(self.root), config)
        base = base[base["method"].eq(selected["base_method"])].copy()
        locked = apply_locked_heatwave_candidate(base, selected)
        locked["base_risk_level"] = np.select(
            [
                locked["base_candidate_positive"].astype(bool),
                locked["candidate_hot_day"].astype(bool),
            ],
            ["high", "medium"],
            default="low",
        )
        locked["joint_final_risk_level"] = np.select(
            [locked["candidate_positive"].astype(bool), locked["integrated_hot_day"].astype(bool)],
            ["high", "medium"],
            default="low",
        )
        return locked

    def _replay(self) -> dict[str, Any]:
        summary_path = self.output_dir / "adm1_full_process_data.csv"
        lock_dir = self.output_dir / "system_prediction_locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        comparisons: list[dict[str, Any]] = []
        for (hazard, split), (reference_path, _) in GROUPS.items():
            reference = pd.read_csv(self.root / reference_path).sort_values(
                ["case_id", "region_id", "lead_time_hours"]
            )
            if hazard == "heatwave" and split == "development":
                rebuilt = self._development_heat_lock()
            else:
                pieces: list[pd.DataFrame] = []
                for case_id, group in reference.groupby("case_id"):
                    temp = self.output_dir / "_temporary_prediction_lock.csv"
                    pieces.append(
                        build_runtime_prediction_lock(
                            self.root,
                            summary_path=summary_path,
                            hazard=hazard,
                            case_id=str(case_id),
                            region_ids=sorted(set(group["region_id"].astype(str))),
                            output_path=temp,
                        )
                    )
                rebuilt = pd.concat(pieces, ignore_index=True)
            rebuilt = rebuilt.sort_values(["case_id", "region_id", "lead_time_hours"])
            columns = [
                "case_id",
                "region_id",
                "lead_time_hours",
                "base_method",
                "knowledge_mode",
                "base_risk_level",
                "knowledge_triggered",
                "joint_final_risk_level",
            ]
            left = rebuilt[columns].reset_index(drop=True).copy()
            right = reference[columns].reset_index(drop=True).copy()
            for field in ("knowledge_triggered",):
                left[field] = left[field].map(_as_bool)
                right[field] = right[field].map(_as_bool)
            pd.testing.assert_frame_equal(left, right, check_dtype=False)
            output = lock_dir / f"{hazard}_{split}.csv"
            rebuilt_columns = [column for column in reference.columns if column in rebuilt.columns]
            rebuilt[rebuilt_columns].to_csv(output, index=False, lineterminator="\n")
            comparisons.append(
                {
                    "hazard": hazard,
                    "dataset_split": split,
                    "rows": len(rebuilt),
                    "reference_decisions_reproduced": True,
                    "path": output.relative_to(self.root).as_posix(),
                    "sha256": _hash(output),
                }
            )
        temporary = self.output_dir / "_temporary_prediction_lock.csv"
        temporary.unlink(missing_ok=True)
        _write_json(self.output_dir / "system_replay_audit.json", comparisons)
        return {"groups": comparisons, "truth_accessed": False}

    def _connection(self) -> dict[str, str]:
        password = os.getenv("NEO4J_PASSWORD")
        if not password:
            raise ValueError("NEO4J_PASSWORD is required")
        return {
            "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            "user": os.getenv("NEO4J_USER", "neo4j"),
            "password": password,
        }

    def _namespace(self, split: str) -> str:
        return f"dual_prediction_batch_v1_{split}"

    def _publish(self) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for hazard, split in GROUPS:
            path = self.output_dir / "system_prediction_locks" / f"{hazard}_{split}.csv"
            frame = pd.read_csv(path)
            selected = self.selection[hazard]["selected"]
            rows = prediction_rows(
                frame,
                hazard=hazard,
                split=self._namespace(split),
                selected_rule=selected["method"],
                prediction_lock_sha256=sha256(path),
            )
            counts = upsert_joint_predictions(rows, **self._connection())
            results.append({"hazard": hazard, "dataset_split": split, **counts})
        _write_json(self.output_dir / "neo4j_publish_audit.json", results)
        return {"groups": results, "query_mode": "live_neo4j"}

    def _indicator_context(self, case_id: str, region_id: str) -> list[dict[str, Any]]:
        frame = pd.read_csv(self.output_dir / "adm1_full_process_data.csv")
        stamps = pd.to_datetime(frame["initial_time"], utc=True).dt.strftime("%Y%m%d_%H")
        selected = frame[stamps.eq(case_id) & frame["region_id"].astype(str).eq(region_id)]
        output: list[dict[str, Any]] = []
        for lead, group in selected.groupby("lead_time_hours"):
            indicators: dict[str, Any] = {}
            for row in group.itertuples(index=False):
                indicators[str(row.indicator)] = {
                    "unit": str(row.unit),
                    "minimum": float(row.minimum),
                    "weighted_mean": float(row.weighted_mean),
                    "spatial_p95": float(row.spatial_p95),
                    "maximum": float(row.maximum),
                }
            output.append({"lead_time_hours": int(lead), "indicators": indicators})
        return sorted(output, key=lambda item: item["lead_time_hours"])

    def _packet(self, hazard: str, split: str, case_id: str, region_id: str) -> dict[str, Any]:
        lock = self.output_dir / "system_prediction_locks" / f"{hazard}_{split}.csv"
        context = query_joint_context(
            **self._connection(),
            hazard=hazard,
            split=self._namespace(split),
            case_id=case_id,
            region_id=region_id,
        )
        selected = self.selection[hazard]["selected"]
        passed = bool(selected["passes_all_gates"])
        return {
            "system_timeline": context,
            "forecast_indicators": self._indicator_context(case_id, region_id),
            "method_status": {
                "selected_joint_rule": selected["method"],
                "development_gate_passed": passed,
                "operating_status": "research_candidate" if passed else "research_only_blocked",
                "formal_warning_allowed": False,
                "development_metrics": {
                    key: value
                    for key, value in selected.items()
                    if key
                    in {
                        "target_window_recall",
                        "target_window_specificity",
                        "observed_hot_day_recall",
                        "observed_nonhot_day_specificity",
                        "event_case_detection_fraction",
                        "control_case_rejection_fraction",
                    }
                },
            },
            "provenance": {
                "prediction_lock_path": lock.relative_to(self.root).as_posix(),
                "prediction_lock_sha256": _hash(lock),
                "selection_lock_path": self.selection_path.relative_to(self.root).as_posix(),
                "selection_lock_sha256": _hash(self.selection_path),
                "neo4j_query_mode": "live_neo4j",
                "dataset_split": split,
            },
            "constraints": [
                "系统联合预测是不可修改事实。",
                "LLM必须另外给出可单独评分的综合预测意见。",
                "预测阶段禁止读取事件/对照标签、同期观测、命中、漏报、误报和灾害答案。",
                "两类预测都不是正式业务预警。",
            ],
        }

    def _validate_report(
        self,
        report: dict[str, Any],
        packet: dict[str, Any],
        hazard: str,
        split: str,
        case_id: str,
        region_id: str,
    ) -> list[str]:
        errors: list[str] = []
        expected = packet["system_timeline"]["timeline"]
        if report.get("truth_accessed") is not False:
            errors.append("truth_accessed must be false")
        for field, value in {
            "case_id": case_id,
            "region_id": region_id,
            "hazard": hazard,
            "dataset_split": split,
            "selected_joint_rule": packet["method_status"]["selected_joint_rule"],
            "development_gate_passed": packet["method_status"]["development_gate_passed"],
            "operating_status": packet["method_status"]["operating_status"],
            "formal_warning_allowed": False,
        }.items():
            if report.get(field) != value:
                errors.append(f"{field} does not match immutable packet")
        timeline = report.get("timeline_analysis", [])
        if len(timeline) != 3:
            errors.append("timeline must contain 24/48/72 hours")
        else:
            for actual, source in zip(timeline, expected, strict=True):
                mappings = {
                    "lead_time_hours": "lead_time_hours",
                    "system_base_risk_level": "base_risk_level",
                    "system_knowledge_triggered": "knowledge_triggered",
                    "system_joint_final_risk_level": "joint_final_risk_level",
                }
                for target, origin in mappings.items():
                    if actual.get(target) != source[origin]:
                        errors.append(f"{target} changed at +{source['lead_time_hours']}h")
                advisory = actual.get("llm_advisory_risk_level")
                if advisory not in RISK_LEVELS:
                    errors.append("invalid LLM advisory risk")
                agreement = advisory == source["joint_final_risk_level"]
                if actual.get("agreement_with_system") is not agreement:
                    errors.append("agreement flag is inconsistent")
            focus = next(
                (
                    item
                    for item in timeline
                    if item["lead_time_hours"] == report["focus_lead_time_hours"]
                ),
                None,
            )
            if focus is None:
                errors.append("focus lead missing")
            else:
                if report.get("system_focus_risk_level") != focus["system_joint_final_risk_level"]:
                    errors.append("system focus risk changed")
                if report.get("llm_focus_advisory_risk_level") != focus["llm_advisory_risk_level"]:
                    errors.append("LLM focus risk does not match timeline")
                if report.get("focus_agreement") is not focus["agreement_with_system"]:
                    errors.append("focus agreement does not match timeline")
        return errors

    def _render(self, report: dict[str, Any]) -> str:
        rows = [
            "| 时效 | 系统基础风险 | 图谱触发 | 系统最终风险 | LLM独立意见 | LLM置信度 | 一致 | 分析 |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for item in report["timeline_analysis"]:
            rows.append(
                f"| +{item['lead_time_hours']}h | {item['system_base_risk_level']} | "
                f"{str(item['system_knowledge_triggered']).lower()} | "
                f"{item['system_joint_final_risk_level']} | {item['llm_advisory_risk_level']} | "
                f"{item['llm_advisory_confidence']} | {str(item['agreement_with_system']).lower()} | "
                f"{item['advisory_analysis_zh']} |"
            )
        limitations = "\n".join(f"- {item}" for item in report["limitations_zh"])
        actions = "\n".join(f"- {item}" for item in report["recommended_actions_zh"])
        return f"""# 系统联合预测与大模型独立意见双轨报告

> `truth_accessed=false`。系统结果不可修改；LLM意见是单独预测者，不覆盖系统结果。

## 案例

- 案例/区域：`{report["case_id"]} / {report["region_id"]}`
- 灾种/划分：`{report["hazard"]} / {report["dataset_split"]}`
- 重点时效：`+{report["focus_lead_time_hours"]}h`
- 系统重点风险：`{report["system_focus_risk_level"]}`
- LLM重点意见：`{report["llm_focus_advisory_risk_level"]}`（`{report["llm_focus_confidence"]}`）
- 是否一致：`{str(report["focus_agreement"]).lower()}`
- 运行边界：`{report["operating_status"]}`；正式预警许可：`false`

## 系统结果分析

{report["system_analysis_zh"]}

## 大模型独立综合预测意见

{report["llm_advisory_summary_zh"]}

## 逐窗口双轨结果

{chr(10).join(rows)}

## 一致与分歧分析

{report["comparison_analysis_zh"]}

## 不确定性

{report["uncertainty_analysis_zh"]}

## 限制

{limitations}

## 建议

{actions}

## 溯源

{report["provenance_summary_zh"]}
"""

    def _reports(self) -> dict[str, Any]:
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required")
        reports_dir = self.output_dir / "reports"
        progress_path = self.output_dir / "report_progress.csv"
        units = self._source_units()
        completed: list[dict[str, Any]] = []
        if progress_path.exists():
            completed = pd.read_csv(progress_path).to_dict(orient="records")
        completed_keys = {
            (
                str(row["hazard"]),
                str(row["dataset_split"]),
                str(row["case_id"]),
                str(row["region_id"]),
            )
            for row in completed
            if row.get("status") == "completed"
        }
        for row in units.itertuples(index=False):
            key = (str(row.hazard), str(row.dataset_split), str(row.case_id), str(row.region_id))
            if key in completed_keys:
                continue
            packet = self._packet(*key)
            model = self.rain_model if row.hazard == "heavy_rain" else self.heat_model
            models = list(dict.fromkeys([model, self.fallback_model]))
            report: dict[str, Any] | None = None
            used_model = ""
            failures: list[str] = []
            for candidate_model in models:
                try:
                    candidate = generate_dual_prediction_report(packet, candidate_model)
                    candidate["generation_mode"] = _generation_mode(candidate_model)
                    candidate["focus_lead_time_hours"] = 48
                    focus = next(
                        item
                        for item in candidate["timeline_analysis"]
                        if int(item["lead_time_hours"]) == 48
                    )
                    candidate["system_focus_risk_level"] = focus["system_joint_final_risk_level"]
                    candidate["llm_focus_advisory_risk_level"] = focus["llm_advisory_risk_level"]
                    candidate["llm_focus_confidence"] = focus["llm_advisory_confidence"]
                    candidate["focus_agreement"] = focus["agreement_with_system"]
                    errors = self._validate_report(candidate, packet, *key)
                    if not errors:
                        report = candidate
                        used_model = candidate_model
                        break
                    failures.extend(errors)
                except Exception as exc:
                    failures.append(f"{candidate_model}: {type(exc).__name__}: {exc}")
            if report is None:
                raise RuntimeError("dual report failed: " + "; ".join(failures))
            directory = reports_dir / str(row.hazard) / str(row.dataset_split)
            prefix = directory / f"{row.case_id}_{row.region_id}"
            json_path = prefix.with_suffix(".json")
            markdown_path = prefix.with_suffix(".md")
            evidence_path = prefix.with_suffix(".evidence.json")
            _write_json(json_path, report)
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(
                self._render(report), encoding="utf-8", newline="\n"
            )
            _write_json(evidence_path, packet)
            completed.append(
                {
                    "hazard": row.hazard,
                    "dataset_split": row.dataset_split,
                    "case_id": row.case_id,
                    "region_id": row.region_id,
                    "status": "completed",
                    "model": used_model,
                    "generation_mode": report["generation_mode"],
                    "system_focus_risk": report["system_focus_risk_level"],
                    "llm_focus_risk": report["llm_focus_advisory_risk_level"],
                    "focus_agreement": report["focus_agreement"],
                    "report_json": json_path.relative_to(self.root).as_posix(),
                    "report_sha256": _hash(json_path),
                }
            )
            pd.DataFrame(completed).to_csv(
                progress_path, index=False, lineterminator="\n"
            )
            print(f"report {len(completed)}/{len(units)} {key} model={used_model}", flush=True)
        return {"report_count": len(completed), "truth_accessed": False}

    def _lock_advisories(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for path in sorted((self.output_dir / "reports").glob("*/*/*.json")):
            if path.name.endswith(".evidence.json"):
                continue
            report = _load_json(path)
            for item in report["timeline_analysis"]:
                rows.append(
                    {
                        "case_id": report["case_id"],
                        "region_id": report["region_id"],
                        "hazard": report["hazard"],
                        "dataset_split": report["dataset_split"],
                        "lead_time_hours": item["lead_time_hours"],
                        "system_joint_final_risk_level": item["system_joint_final_risk_level"],
                        "llm_advisory_risk_level": item["llm_advisory_risk_level"],
                        "llm_advisory_confidence": item["llm_advisory_confidence"],
                        "agreement_with_system": item["agreement_with_system"],
                        "truth_accessed": False,
                    }
                )
        frame = pd.DataFrame(rows).sort_values(
            ["hazard", "dataset_split", "case_id", "region_id", "lead_time_hours"]
        )
        if (
            len(frame) != 87
            or frame.duplicated(
                ["hazard", "dataset_split", "case_id", "region_id", "lead_time_hours"]
            ).any()
        ):
            raise ValueError("advisory lock must contain 29 units x 3 windows")
        output = self.output_dir / "llm_advisory_prediction_lock.csv"
        frame.to_csv(output, index=False, lineterminator="\n")
        return {"rows": len(frame), "sha256": _hash(output), "truth_accessed": False}

    def _metrics(self, details: pd.DataFrame, hazard: str, split: str) -> dict[str, Any]:
        target = details[details["evaluation_scope"].eq("target_window")].copy()
        truth = (
            target["case_role"].eq("event")
            if hazard == "heavy_rain"
            else target["observed_hot_day"].map(_as_bool)
        )
        output: dict[str, Any] = {
            "hazard": hazard,
            "dataset_split": split,
            "target_windows": len(target),
            "positive_windows": int(truth.sum()),
            "negative_windows": int((~truth).sum()),
        }
        for name, column in (
            ("system", "system_joint_final_risk_level"),
            ("llm_advisory", "llm_advisory_risk_level"),
        ):
            positive = target[column].isin(["medium", "high"])
            tp = int((positive & truth).sum())
            fn = int((~positive & truth).sum())
            fp = int((positive & ~truth).sum())
            tn = int((~positive & ~truth).sum())
            output[name] = {
                "hits": tp,
                "misses": fn,
                "false_alarms": fp,
                "correct_negatives": tn,
                "recall": tp / (tp + fn) if tp + fn else None,
                "specificity": tn / (tn + fp) if tn + fp else None,
                "balanced_accuracy": (
                    ((tp / (tp + fn)) + (tn / (tn + fp))) / 2 if tp + fn and tn + fp else None
                ),
            }
        output["llm_changed_windows"] = int(
            (target["llm_advisory_risk_level"] != target["system_joint_final_risk_level"]).sum()
        )
        return output

    def _verify(self) -> dict[str, Any]:
        advisory = pd.read_csv(self.output_dir / "llm_advisory_prediction_lock.csv")
        metrics: list[dict[str, Any]] = []
        details_dir = self.output_dir / "verification"
        details_dir.mkdir(parents=True, exist_ok=True)
        for (hazard, split), (_, truth_path) in GROUPS.items():
            truth = pd.read_csv(self.root / truth_path)
            predictions = advisory[
                advisory["hazard"].eq(hazard) & advisory["dataset_split"].eq(split)
            ].copy()
            keys = ["case_id", "region_id", "lead_time_hours"]
            truth["case_id"] = truth["case_id"].astype(str)
            predictions["case_id"] = predictions["case_id"].astype(str)
            merged = truth.merge(
                predictions[
                    keys
                    + [
                        "system_joint_final_risk_level",
                        "llm_advisory_risk_level",
                        "llm_advisory_confidence",
                        "agreement_with_system",
                    ]
                ],
                on=keys,
                how="left",
                validate="one_to_one",
            )
            if merged["llm_advisory_risk_level"].isna().any():
                raise ValueError(f"missing advisory rows for {hazard}/{split}")
            output = details_dir / f"{hazard}_{split}_scored_details.csv"
            merged.to_csv(output, index=False, lineterminator="\n")
            metrics.append(self._metrics(merged, hazard, split))
        result = {
            "schema_version": "dual_prediction_post_lock_verification_v1",
            "prediction_lock_sha256": _hash(self.output_dir / "llm_advisory_prediction_lock.csv"),
            "truth_opened_only_after_lock": True,
            "groups": metrics,
        }
        _write_json(details_dir / "system_vs_llm_metrics.json", result)
        return result

    def _finalize(self) -> dict[str, Any]:
        artifacts: list[dict[str, Any]] = []
        for path in sorted(self.output_dir.rglob("*")):
            if path.is_file() and path.name not in {"batch_state.json", "batch_manifest.json"}:
                artifacts.append(
                    {
                        "path": path.relative_to(self.root).as_posix(),
                        "sha256": _hash(path),
                        "size_bytes": path.stat().st_size,
                    }
                )
        manifest = {
            "schema_version": "dual_prediction_batch_manifest_v1",
            "status": "passed",
            "report_units": 29,
            "forecast_windows": 87,
            "truth_accessed_during_prediction": False,
            "truth_opened_only_after_advisory_lock": True,
            "selection_lock_sha256": _hash(self.selection_path),
            "artifacts": artifacts,
            "completed_at": _utc_now(),
        }
        path = self.output_dir / "batch_manifest.json"
        _write_json(path, manifest)
        return {"path": path.relative_to(self.root).as_posix(), "sha256": _hash(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("handoff/reports/dual_prediction_batch_v1"),
    )
    parser.add_argument("--rain-model", default="gpt-5.6-luna")
    parser.add_argument("--heat-model", default="gpt-5.6-terra")
    parser.add_argument("--fallback-model", default="gpt-5.6-luna")
    args = parser.parse_args()
    batch = DualBatch(
        args.root,
        args.output_dir,
        args.rain_model,
        args.heat_model,
        args.fallback_model,
    )
    state = batch.run()
    print(f"status={state['status']}")
    print(f"output={batch.output_dir}")


if __name__ == "__main__":
    main()
