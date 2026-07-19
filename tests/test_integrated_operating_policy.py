from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_integrated_policy_preserves_rule_and_truth_boundaries() -> None:
    policy = yaml.safe_load(
        (ROOT / "configs/integrated_operating_policy_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert policy["hazards"]["heavy_rain"]["base_rule_status"] == "frozen"
    assert policy["hazards"]["heavy_rain"]["knowledge_shadow_may_override_base"] is False
    assert policy["hazards"]["heatwave"]["base_rule_status"] == "draft_blocked"
    assert policy["hazards"]["heatwave"]["benchmark_is_deployable"] is False
    assert policy["hazards"]["heatwave"]["independent_evaluation"] == (
        "sealed_not_opened"
    )
    assert policy["reporting"]["forecast_truth_access"] == "forbidden"
    assert policy["decision"]["official_heatwave_rule"] == "none"
