from pathlib import Path

import yaml

from saudi_warning.risk.benchmark_integrated_candidates import (
    assess_heatwave,
    assess_rain,
    heatwave_candidate_rows,
    load_heatwave_development,
    load_rain_rows,
    rain_candidate_rows,
    run,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/integrated_candidate_benchmark_v1.yaml"


def test_benchmark_keeps_independent_heatwave_sealed(tmp_path: Path) -> None:
    result = run(
        ROOT,
        CONFIG_PATH,
        tmp_path / "model_selection",
        tmp_path / "assessment.json",
    )
    assert result["heatwave"]["independent_heatwave_opened"] is False
    assert result["heavy_rain"]["selected_official_base_rule"] == (
        "heavy_rain_graphcast_scale_v2"
    )
    assert result["knowledge_graph"]["base_risk_mutation_enabled"] is False
    assert result["heatwave"]["selected_development_method"] is None
    assert result["heatwave"]["best_available_development_method"] == (
        "blend075_pooled_loco"
    )
    assert result["heavy_rain"]["selected_shadow_knowledge_candidate"] == (
        "v2_kg_ratio_050_support2"
    )
    assert result["heavy_rain"]["best_observed_development_knowledge_candidate"] == (
        "v2_kg_persistence_ratio050_support2"
    )
    assert result["heavy_rain"]["shadow_candidate_activation_eligible"] is False


def test_all_opened_heatwave_development_batches_are_compared() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    rows = load_heatwave_development(ROOT)
    details = heatwave_candidate_rows(rows, config)
    assessment = assess_heatwave(details, config)
    assert rows["case_id"].nunique() == 16
    assert len(rows) == 48
    assert set(assessment["method"]) == set(config["heatwave"]["candidates"])
    assert details.groupby("method").size().eq(48).all()


def test_rain_candidate_search_uses_development_only() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    rows = load_rain_rows(ROOT, "development")
    details = rain_candidate_rows(rows, config)
    assessment = assess_rain(details, config)
    assert set(details["dataset_split"]) == {"development"}
    assert "v1_base" in set(assessment["method"])
    assert "v2_base" in set(assessment["method"])
    assert all(name.startswith("v2_kg_") for name in set(assessment["method"]) - {"v1_base", "v2_base"})
