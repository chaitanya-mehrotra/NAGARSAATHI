"""Generate the plan's explicitly synthetic pilot/areas and fictional POI fixtures."""

import json
from pathlib import Path
from typing import Any

from app.settings import PROJECT_ROOT


def polygon(west: float, south: float, east: float, north: float) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [
            [[west, south], [east, south], [east, north], [west, north], [west, south]]
        ],
    }


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    provenance = {
        "synthetic": True,
        "source": "implementation-plan-demo-rectangles",
        "boundary_version": "demo-envelope-v1",
    }
    write(
        PROJECT_ROOT / "config/pilot.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        **provenance,
                        "code": "bengaluru_southeast_v1",
                        "name": "Southeast Bengaluru pilot",
                        "timezone": "Asia/Kolkata",
                    },
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [polygon(77.60, 12.90, 77.69, 12.96)["coordinates"]],
                    },
                }
            ],
        },
    )
    areas = []
    for south, north, vertical in [(12.90, 12.93, "South"), (12.93, 12.96, "North")]:
        for west, east, horizontal in [
            (77.60, 77.63, "west"),
            (77.63, 77.66, " Central"),
            (77.66, 77.69, "east"),
        ]:
            name = vertical + horizontal
            areas.append(
                {
                    "type": "Feature",
                    "properties": {
                        **provenance,
                        "code": name.lower().replace(" ", "_"),
                        "name": name,
                    },
                    "geometry": polygon(west, south, east, north),
                }
            )
    write(PROJECT_ROOT / "config/areas.geojson", {"type": "FeatureCollection", "features": areas})
    write(
        PROJECT_ROOT / "fixtures/poi-snapshot.geojson",
        {
            "type": "FeatureCollection",
            "properties": {
                "version": "demo-pois-v1",
                "synthetic": True,
                "source": "fictional-test-fixtures",
                "source_date": "2026-10-03",
                "coverage_complete": False,
                "coverage_notes": "Fictional POIs only; no claim of real Bengaluru coverage",
                "margin_m": 500,
            },
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "source_id": "demo-school-west",
                        "name": "Demo school outside west boundary",
                        "type": "school",
                        "synthetic": True,
                    },
                    "geometry": {"type": "Point", "coordinates": [77.5997, 12.925]},
                },
                {
                    "type": "Feature",
                    "properties": {
                        "source_id": "demo-hospital",
                        "name": "Demo hospital",
                        "type": "hospital",
                        "synthetic": True,
                    },
                    "geometry": {"type": "Point", "coordinates": [77.65, 12.945]},
                },
                {
                    "type": "Feature",
                    "properties": {
                        "source_id": "demo-road",
                        "name": "Demo major road",
                        "type": "major_road",
                        "synthetic": True,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[77.61, 12.92], [77.68, 12.92]],
                    },
                },
            ],
        },
    )


if __name__ == "__main__":
    main()
