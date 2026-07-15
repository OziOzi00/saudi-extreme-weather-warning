from pathlib import Path

import yaml

from scripts.audit_mazu_2025 import EXPECTED

def test_mazu_audit_covers_shared_v1_interface() -> None:
    assert set(EXPECTED) == {
        "daily_precip_total",
        "t2m_c",
        "tmax_c",
        "tmin_c",
        "wind10_speed",
        "pwat",
        "ivt",
        "wind850_speed",
        "wind_shear_850_200",
        "omega500",
        "geopotential_height500",
    }


def test_mazu_mapping_config_matches_audit_interface() -> None:
    root = Path(__file__).resolve().parents[1]
    mapping_path = root / "configs" / "indicator_mapping.yaml"
    config = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    assert set(config["mazu_2025_audit"]["field_mapping"]) == set(EXPECTED)
