"""Resumable, controlled state machine for the complete research pipeline."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from scripts.summarize_mazu_like_adm1 import summarize_file
from saudi_warning.forecasting.run_batch import CaseRecord, output_paths, process_case
from saudi_warning.forecasting.validation import (
    validate_mazu_like_file,
    validate_mazu_like_sequence,
)
from saudi_warning.knowledge_graph.joint_runtime import (
    prediction_rows,
    query_joint_context,
    sha256,
    upsert_joint_predictions,
)
from saudi_warning.orchestration.joint_inference import build_runtime_prediction_lock


STAGES = (
    "preflight",
    "forecast_materialization",
    "contract_validation",
    "region_summary",
    "joint_inference_and_lock",
    "neo4j_publish_and_query",
    "live_agent_reports",
    "finalize_manifest",
)
CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class WorkflowRequest:
    run_id: str
    case_id: str
    initial_time: str
    hazard: str
    region_ids: tuple[str, ...]
    focus_lead_time_hours: int = 48
    model: str = "gpt-5.6-luna"
    escalation_model: str = "gpt-5.6-terra"
    cache_dir: str = "data/raw/graphcast_2020"
    mazu_dir: str = "handoff/mazu_like"
    output_root: str = "handoff/orchestrator_runs"


class ControlledWorkflow:
    """Only exposes the next legal transition; no arbitrary shell or rule edits."""

    def __init__(self, root: Path, request: WorkflowRequest):
        self.root = root.resolve()
        self.request = request
        self.run_dir = self.root / request.output_root / request.run_id
        self.state_path = self.run_dir / "workflow_state.json"
        self.handlers: dict[str, Callable[[], dict[str, Any]]] = {
            "preflight": self._preflight,
            "forecast_materialization": self._forecast,
            "contract_validation": self._validate_contract,
            "region_summary": self._summarize,
            "joint_inference_and_lock": self._infer,
            "neo4j_publish_and_query": self._neo4j,
            "live_agent_reports": self._reports,
            "finalize_manifest": self._finalize,
        }
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self._write_state(
                {
                    "schema_version": "controlled_orchestrator_state_v1",
                    "truth_accessed": False,
                    "request": self._request_dict(),
                    "status": "pending",
                    "stages": {stage: {"status": "pending"} for stage in STAGES},
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                }
            )
        elif self.state()["request"] != self._request_dict():
            raise ValueError("existing run_id belongs to a different immutable request")

    def _request_dict(self) -> dict[str, Any]:
        value = asdict(self.request)
        value["region_ids"] = list(self.request.region_ids)
        return value

    def state(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _write_state(self, state: dict[str, Any]) -> None:
        state["updated_at"] = utc_now()
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(self.state_path)

    def next_stage(self) -> str | None:
        state = self.state()
        for stage in STAGES:
            if state["stages"][stage]["status"] != "completed":
                return stage
        return None

    def advance(self) -> dict[str, Any]:
        stage = self.next_stage()
        if stage is None:
            return {"status": "complete", "next_stage": None}
        state = self.state()
        state["status"] = "running"
        state["stages"][stage] = {"status": "running", "started_at": utc_now()}
        self._write_state(state)
        try:
            result = self.handlers[stage]()
        except Exception as exc:
            state = self.state()
            state["status"] = "failed"
            state["stages"][stage] = {
                "status": "failed",
                "started_at": state["stages"][stage].get("started_at"),
                "failed_at": utc_now(),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            self._write_state(state)
            raise
        state = self.state()
        state["stages"][stage] = {
            "status": "completed",
            "started_at": state["stages"][stage].get("started_at"),
            "completed_at": utc_now(),
            "result": result,
        }
        next_stage = next((name for name in STAGES if state["stages"][name]["status"] != "completed"), None)
        state["status"] = "complete" if next_stage is None else "running"
        self._write_state(state)
        return {"status": state["status"], "completed_stage": stage, "next_stage": next_stage}

    def run_to_completion(self) -> dict[str, Any]:
        while self.next_stage() is not None:
            self.advance()
        return self.state()

    def _preflight(self) -> dict[str, Any]:
        request = self.request
        if not CASE_ID_PATTERN.fullmatch(request.run_id) or not CASE_ID_PATTERN.fullmatch(request.case_id):
            raise ValueError("run_id and case_id must use only safe identifier characters")
        if request.hazard not in {"heavy_rain", "heatwave"}:
            raise ValueError("unsupported hazard")
        if request.focus_lead_time_hours not in {24, 48, 72}:
            raise ValueError("focus lead must be 24, 48, or 72")
        if not request.initial_time.endswith("Z"):
            raise ValueError("initial_time must be explicit UTC ending in Z")
        parsed = datetime.fromisoformat(request.initial_time.replace("Z", "+00:00"))
        if parsed.year not in {2018, 2020} or parsed.hour not in {0, 12}:
            raise ValueError("runtime GraphCast replay supports 2018/2020 at 00 or 12 UTC")
        if any((parsed.minute, parsed.second, parsed.microsecond)):
            raise ValueError("initial_time must be an exact forecast cycle")
        expected_case = parsed.strftime("%Y%m%d_%H")
        if request.case_id != expected_case:
            raise ValueError("case_id must equal the UTC initial-time stamp")
        with (self.root / "configs/region_registry.csv").open(encoding="utf-8", newline="") as stream:
            registry = {row["region_id"] for row in csv.DictReader(stream)}
        unknown = set(request.region_ids) - registry
        if unknown or not request.region_ids:
            raise ValueError("unknown or empty region selection: " + ", ".join(sorted(unknown)))
        selection = json.loads(
            (self.root / "manifests/joint_pipeline_selection_lock_v2.json").read_text(encoding="utf-8")
        )
        if selection.get("independent_truth_used_by_selection_code") is not False:
            raise ValueError("selection lock does not preserve truth isolation")
        for relative_path, expected_hash in selection["input_sha256"].items():
            source = self.root / relative_path
            if not source.exists() or file_hash(source) != expected_hash:
                raise ValueError(f"selection input changed after lock: {relative_path}")
        return {
            "case_id_matches_initial_time": True,
            "regions_validated": list(request.region_ids),
            "selected_rule": selection[request.hazard]["selected"]["method"],
            "truth_accessed": False,
        }

    def _forecast(self) -> dict[str, Any]:
        case = CaseRecord(case_id=self.request.case_id, initial_time=self.request.initial_time)
        status, paths, message = process_case(
            case,
            self.root / self.request.cache_dir,
            self.root / self.request.mazu_dir,
            retries=3,
            timeout_seconds=1800,
        )
        return {
            "status": status,
            "message": message,
            "files": {str(lead): path.relative_to(self.root).as_posix() for lead, path in paths.items()},
        }

    def _forecast_paths(self) -> dict[int, Path]:
        return output_paths(self.root / self.request.mazu_dir, self.request.initial_time)

    def _validate_contract(self) -> dict[str, Any]:
        paths = self._forecast_paths()
        errors = validate_mazu_like_sequence(list(paths.values()))
        if errors:
            raise ValueError("MAZU-like sequence validation failed: " + " | ".join(errors))
        reports = {
            str(lead): validate_mazu_like_file(path).to_dict() for lead, path in paths.items()
        }
        return {
            "valid": True,
            "file_sha256": {str(lead): file_hash(path) for lead, path in paths.items()},
            "reports": reports,
        }

    def _summarize(self) -> dict[str, Any]:
        registry_path = self.root / "configs/region_registry.csv"
        with registry_path.open(encoding="utf-8", newline="") as stream:
            registry = {row["region_id"]: row["region_name_en"] for row in csv.DictReader(stream)}
        rows: list[dict[str, Any]] = []
        for path in self._forecast_paths().values():
            rows.extend(
                summarize_file(
                    path,
                    self.root / "data/reference/saudi_adm1_geoboundaries_2017.geojson",
                    registry,
                )
            )
        rows = [row for row in rows if row["region_id"] in set(self.request.region_ids)]
        output = self.run_dir / "adm1_indicator_summary.csv"
        pd.DataFrame(rows).to_csv(output, index=False, lineterminator="\n")
        expected = len(self.request.region_ids) * 3 * 11
        if len(rows) != expected:
            raise ValueError(f"expected {expected} ADM1 indicator rows, found {len(rows)}")
        return {"path": output.relative_to(self.root).as_posix(), "rows": len(rows), "sha256": file_hash(output)}

    def _infer(self) -> dict[str, Any]:
        lock = self.run_dir / f"{self.request.hazard}_prediction_lock.csv"
        frame = build_runtime_prediction_lock(
            self.root,
            summary_path=self.run_dir / "adm1_indicator_summary.csv",
            hazard=self.request.hazard,
            case_id=self.request.case_id,
            region_ids=list(self.request.region_ids),
            output_path=lock,
        )
        return {
            "path": lock.relative_to(self.root).as_posix(),
            "rows": len(frame),
            "sha256": file_hash(lock),
            "truth_accessed": False,
        }

    def _neo4j(self) -> dict[str, Any]:
        password = os.getenv("NEO4J_PASSWORD")
        if not password:
            raise ValueError("NEO4J_PASSWORD is required")
        lock = self.run_dir / f"{self.request.hazard}_prediction_lock.csv"
        frame = pd.read_csv(lock)
        selection = json.loads(
            (self.root / "manifests/joint_pipeline_selection_lock_v2.json").read_text(encoding="utf-8")
        )
        rule = selection[self.request.hazard]["selected"]["method"]
        rows = prediction_rows(
            frame,
            hazard=self.request.hazard,
            split=self.request.run_id,
            selected_rule=rule,
            prediction_lock_sha256=sha256(lock),
        )
        connection = {
            "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            "user": os.getenv("NEO4J_USER", "neo4j"),
            "password": password,
        }
        counts = upsert_joint_predictions(rows, **connection)
        contexts: dict[str, Any] = {}
        for region_id in self.request.region_ids:
            contexts[region_id] = query_joint_context(
                **connection,
                hazard=self.request.hazard,
                split=self.request.run_id,
                case_id=self.request.case_id,
                region_id=region_id,
            )
        context_path = self.run_dir / "neo4j_context.json"
        context_path.write_text(
            json.dumps(contexts, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            "query_mode": "live_neo4j",
            "counts": counts,
            "context_path": context_path.relative_to(self.root).as_posix(),
            "context_sha256": file_hash(context_path),
            "truth_accessed": False,
        }

    def _reports(self) -> dict[str, Any]:
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required")
        lock = self.run_dir / f"{self.request.hazard}_prediction_lock.csv"
        outputs: list[dict[str, Any]] = []
        environment = os.environ.copy()
        source_root = str(self.root / "src")
        environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
        for region_id in self.request.region_ids:
            prefix = self.run_dir / f"{self.request.hazard}_{region_id}_lead{self.request.focus_lead_time_hours:03d}"
            json_path = prefix.with_suffix(".json")
            markdown_path = prefix.with_suffix(".md")
            evidence_path = prefix.with_suffix(".evidence.json")
            command = [
                sys.executable,
                "-m",
                "saudi_warning.orchestration.run_runtime_report",
                "--root",
                str(self.root),
                "--prediction-lock",
                str(lock),
                "--hazard",
                self.request.hazard,
                "--runtime-namespace",
                self.request.run_id,
                "--case-id",
                self.request.case_id,
                "--region-id",
                region_id,
                "--lead-time-hours",
                str(self.request.focus_lead_time_hours),
                "--model",
                self.request.model,
                "--escalation-model",
                self.request.escalation_model,
                "--output-json",
                str(json_path),
                "--output-markdown",
                str(markdown_path),
                "--evidence-output",
                str(evidence_path),
            ]
            completed = subprocess.run(
                command,
                cwd=self.root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=900,
            )
            if completed.returncode != 0:
                raise RuntimeError("live report subprocess failed: " + completed.stderr[-2000:])
            report = json.loads(json_path.read_text(encoding="utf-8"))
            outputs.append(
                {
                    "region_id": region_id,
                    "report_json": json_path.relative_to(self.root).as_posix(),
                    "report_markdown": markdown_path.relative_to(self.root).as_posix(),
                    "evidence": evidence_path.relative_to(self.root).as_posix(),
                    "generation_mode": report["generation_mode"],
                    "joint_final_risk_level": report["joint_final_risk_level"],
                    "report_sha256": file_hash(json_path),
                }
            )
        return {"reports": outputs, "truth_accessed": False}

    def _finalize(self) -> dict[str, Any]:
        state = self.state()
        artifacts: list[dict[str, Any]] = []
        for path in sorted(self.run_dir.iterdir()):
            if path.is_file() and path.name not in {"workflow_state.json", "run_manifest.json"}:
                artifacts.append(
                    {
                        "path": path.relative_to(self.root).as_posix(),
                        "sha256": file_hash(path),
                        "size_bytes": path.stat().st_size,
                    }
                )
        manifest = {
            "schema_version": "controlled_orchestrator_run_manifest_v1",
            "status": "passed",
            "truth_accessed": False,
            "request": self._request_dict(),
            "completed_stages": [stage for stage in STAGES if stage != "finalize_manifest"],
            "artifacts": artifacts,
            "selection_lock_sha256": file_hash(
                self.root / "manifests/joint_pipeline_selection_lock_v2.json"
            ),
            "created_at": state["created_at"],
            "completed_at": utc_now(),
        }
        path = self.run_dir / "run_manifest.json"
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return {"path": path.relative_to(self.root).as_posix(), "sha256": file_hash(path)}
