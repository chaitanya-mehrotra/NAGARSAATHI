import json
import shutil
from pathlib import Path
from uuid import UUID

import pytest
from app.demo_seed import seed_foundation
from app.domain.geography import IssuePoint, assign_area, verify_area_partition
from app.settings import PROJECT_ROOT, Settings
from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text


def pilot_id(db: Connection) -> UUID:
    return db.exec_driver_sql("SELECT id FROM pilots").scalar_one()


@pytest.mark.parametrize(
    "lon,lat,expected",
    [
        (77.615, 12.915, "southwest"),
        (77.645, 12.915, "south_central"),
        (77.675, 12.915, "southeast"),
        (77.615, 12.945, "northwest"),
        (77.645, 12.945, "north_central"),
        (77.675, 12.945, "northeast"),
        (77.63, 12.915, "south_central"),
        (77.66, 12.915, "south_central"),
        (77.615, 12.93, "northwest"),
        (77.63, 12.93, "north_central"),
        (77.66, 12.93, "north_central"),
        (77.60, 12.90, "southwest"),
        (77.69, 12.90, "southeast"),
        (77.60, 12.96, "northwest"),
        (77.69, 12.96, "northeast"),
    ],
)
def test_centres_shared_edges_and_corners_assign_one_owner(
    db: Connection, lon: float, lat: float, expected: str
) -> None:
    point = IssuePoint(longitude=lon, latitude=lat, confirmed=True)
    for _ in range(3):
        result = assign_area(db, pilot_id(db), point)
        assert result.state == "located"
        assert result.area_code == expected
        assert result.area_id is not None
        assert result.boundary_version == "demo-envelope-v1"


@pytest.mark.parametrize(
    "lon,lat",
    [
        (77.5999, 12.92),
        (77.6901, 12.92),
        (77.65, 12.8999),
        (77.65, 12.9601),
        (12.915, 77.615),  # Swapped latitude/longitude must never be silently corrected.
    ],
)
def test_outside_and_swapped_points_are_not_admitted(
    db: Connection, lon: float, lat: float
) -> None:
    result = assign_area(db, pilot_id(db), IssuePoint(longitude=lon, latitude=lat, confirmed=True))
    assert result.state == "out_of_scope"
    assert result.area_id is None


@pytest.mark.parametrize(
    "point,reason",
    [
        (IssuePoint(), "missing_coordinates"),
        (IssuePoint(longitude=77.615), "missing_coordinates"),
        (IssuePoint(longitude=77.615, latitude=12.915), "pin_not_confirmed"),
        (
            IssuePoint(longitude=77.63, latitude=12.915, confirmed=True, uncertainty_m=20),
            "uncertainty_crosses_boundary",
        ),
    ],
)
def test_missing_unconfirmed_and_uncertain_points_require_review(
    db: Connection, point: IssuePoint, reason: str
) -> None:
    result = assign_area(db, pilot_id(db), point)
    assert result.state == "needs_review"
    assert result.reason == reason
    assert result.area_id is None


@pytest.mark.parametrize(
    "values",
    [
        {"longitude": 181.0},
        {"latitude": 91.0},
        {"longitude": float("nan")},
        {"latitude": float("inf")},
        {"longitude": True},
        {"uncertainty_m": -1},
    ],
)
def test_invalid_coordinates_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        IssuePoint.model_validate(values)


def test_exact_partition_and_fictional_poi_margin(db: Connection) -> None:
    assert verify_area_partition(db, pilot_id(db)) == {
        "area_count": 6,
        "exact_coverage": True,
        "no_interior_overlap": True,
    }
    assert db.exec_driver_sql("SELECT bool_and(synthetic) FROM pois").scalar_one() is True
    assert db.exec_driver_sql("""
        SELECT NOT ST_Covers(p.geom,poi.geom::geometry), ST_Covers(s.coverage,poi.geom::geometry)
        FROM pois poi JOIN poi_snapshots s ON s.id=poi.snapshot_id CROSS JOIN pilots p
        WHERE poi.source_id='demo-school-west'
    """).one() == (True, True)
    assert db.exec_driver_sql("SELECT coverage_complete FROM poi_snapshots").scalar_one() is False


def test_twenty_metres_uses_geography_units(db: Connection) -> None:
    result = db.exec_driver_sql("""
        WITH origin AS (SELECT ST_GeogFromText('SRID=4326;POINT(77.63 12.93)') AS geom)
        SELECT ST_Distance(geom,ST_Project(geom,20,0)),
               ST_DWithin(geom,ST_Project(geom,19.9,0),20),
               ST_DWithin(geom,ST_Project(geom,20.1,0),20) FROM origin
    """).one()
    assert result[0] == pytest.approx(20, abs=0.001)
    assert result[1:] == (True, False)


def copy_config(tmp_path: Path) -> Path:
    shutil.copytree(PROJECT_ROOT / "config", tmp_path / "config")
    shutil.copytree(PROJECT_ROOT / "fixtures", tmp_path / "fixtures")
    return tmp_path


@pytest.mark.parametrize("fault", ["gap", "overlap"])
def test_invalid_area_config_is_rejected_transactionally(
    db: Connection, spatial_database: tuple[Engine, Settings], tmp_path: Path, fault: str
) -> None:
    root = copy_config(tmp_path)
    pilot = json.loads((root / "config/pilot.geojson").read_text())
    pilot["features"][0]["properties"]["boundary_version"] = "broken-" + fault
    (root / "config/pilot.geojson").write_text(json.dumps(pilot))
    areas = json.loads((root / "config/areas.geojson").read_text())
    for feature in areas["features"]:
        feature["properties"]["boundary_version"] = "broken-" + fault
    if fault == "gap":
        areas["features"].pop()
    else:
        areas["features"][0]["geometry"]["coordinates"][0][1][0] = 77.64
        areas["features"][0]["geometry"]["coordinates"][0][2][0] = 77.64
    (root / "config/areas.geojson").write_text(json.dumps(areas))
    with pytest.raises(ValueError, match="without gaps or interior overlap"), db.begin_nested():
        seed_foundation(db, spatial_database[1], root)
    assert db.execute(text("SELECT count(*) FROM pilots")).scalar_one() == 1


def test_changed_geometry_requires_new_boundary_version(
    db: Connection, spatial_database: tuple[Engine, Settings], tmp_path: Path
) -> None:
    root = copy_config(tmp_path)
    areas = json.loads((root / "config/areas.geojson").read_text())
    areas["features"][0]["geometry"]["coordinates"][0][1][0] = 77.631
    (root / "config/areas.geojson").write_text(json.dumps(areas))
    with pytest.raises(ValueError, match="new boundary_version"), db.begin_nested():
        seed_foundation(db, spatial_database[1], root)


def test_repeated_seed_is_idempotent(
    db: Connection, spatial_database: tuple[Engine, Settings]
) -> None:
    first = seed_foundation(db, spatial_database[1])
    assert seed_foundation(db, spatial_database[1]) == first
    assert db.exec_driver_sql("SELECT count(*) FROM areas").scalar_one() == 6
    assert db.exec_driver_sql("SELECT count(*) FROM categories").scalar_one() == 5
    assert db.exec_driver_sql("SELECT count(*) FROM pois").scalar_one() == 3
