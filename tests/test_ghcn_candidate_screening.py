from scripts.screen_ghcn_candidates import build_daily_rows, point_in_geometry, point_in_ring


def test_point_in_ring() -> None:
    ring = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
    assert point_in_ring(1.0, 1.0, ring)
    assert not point_in_ring(3.0, 1.0, ring)


def test_polygon_hole_and_multipolygon() -> None:
    outer = [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [0.0, 0.0]]
    hole = [[1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 2.0], [1.0, 1.0]]
    polygon = {"type": "Polygon", "coordinates": [outer, hole]}
    assert point_in_geometry(3.0, 3.0, polygon)
    assert not point_in_geometry(1.5, 1.5, polygon)

    second = [[10.0, 10.0], [11.0, 10.0], [11.0, 11.0], [10.0, 10.0]]
    multipolygon = {"type": "MultiPolygon", "coordinates": [[outer], [second]]}
    assert point_in_geometry(10.25, 10.25, multipolygon)


def test_daily_summary_keeps_region_and_station_count() -> None:
    stations = {
        "SA1": {"region_id": "SA-04"},
        "SA2": {"region_id": "SA-04"},
    }
    observations = {
        ("SA1", "20200701", "TMAX"): 45.0,
        ("SA2", "20200701", "TMAX"): 47.0,
    }
    assert build_daily_rows(observations, stations) == [
        {
            "region_id": "SA-04",
            "date": "20200701",
            "element": "TMAX",
            "station_count": 2,
            "minimum": 45.0,
            "maximum": 47.0,
        }
    ]
