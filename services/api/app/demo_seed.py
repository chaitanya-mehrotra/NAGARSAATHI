import json
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml
from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url

from app.domain.geography import geometry_json, verify_area_partition
from app.settings import PROJECT_ROOT, Settings


def demo_id(value: str) -> UUID:
    return uuid5(NAMESPACE_URL, "nagarsaathi-demo:" + value)


def require_local_demo(settings: Settings) -> None:
    url = make_url(settings.database_url)
    if settings.app_mode not in {"demo", "test"} or url.host not in {
        "localhost",
        "127.0.0.1",
        "db",
    }:
        raise ValueError("Demo seeding is restricted to local demo/test databases")
    if not url.database or not url.database.endswith(("_demo", "_test")):
        raise ValueError("Demo/test database names must end in _demo or _test")


def seed_foundation(
    connection: Connection, settings: Settings, config_root: Path = PROJECT_ROOT
) -> UUID:
    require_local_demo(settings)
    pilot_feature = json.loads((config_root / "config/pilot.geojson").read_text())["features"][0]
    pilot = pilot_feature["properties"]
    pilot_id = demo_id(pilot["code"] + ":" + pilot["boundary_version"])
    existing = connection.execute(
        text("""
        SELECT ST_Equals(geom,ST_SetSRID(ST_GeomFromGeoJSON(:geometry),4326))
        FROM pilots WHERE id = :id
    """),
        {"id": pilot_id, "geometry": geometry_json(pilot_feature)},
    ).scalar_one_or_none()
    if existing is False:
        raise ValueError("Changed boundary geometry requires a new boundary_version")
    connection.execute(
        text("""
        INSERT INTO pilots (id,code,name,timezone,geom,boundary_version,synthetic,provenance)
        VALUES (:id,:code,:name,:timezone,ST_SetSRID(ST_GeomFromGeoJSON(:geometry),4326),
                :version,true,CAST(:provenance AS jsonb)) ON CONFLICT (id) DO NOTHING
    """),
        {
            "id": pilot_id,
            "code": pilot["code"],
            "name": pilot["name"],
            "timezone": pilot["timezone"],
            "geometry": geometry_json(pilot_feature),
            "version": pilot["boundary_version"],
            "provenance": json.dumps(pilot),
        },
    )
    for feature in json.loads((config_root / "config/areas.geojson").read_text())["features"]:
        props = feature["properties"]
        if props["boundary_version"] != pilot["boundary_version"]:
            raise ValueError("Area boundary version does not match pilot")
        area_id = demo_id(str(pilot_id) + ":" + props["code"])
        unchanged = connection.execute(
            text("""
            SELECT ST_Equals(geom,ST_SetSRID(ST_GeomFromGeoJSON(:geometry),4326))
            FROM areas WHERE id = :id
        """),
            {"id": area_id, "geometry": geometry_json(feature)},
        ).scalar_one_or_none()
        if unchanged is False:
            raise ValueError("Changed area geometry requires a new boundary_version")
        connection.execute(
            text("""
            INSERT INTO areas (id,pilot_id,code,display_name,geom,boundary_version,
                               provenance,effective_from)
            VALUES (:id,:pilot,:code,:name,ST_SetSRID(ST_GeomFromGeoJSON(:geometry),4326),
                    :version,CAST(:provenance AS jsonb),'2026-10-03T00:00:00Z')
            ON CONFLICT (id) DO NOTHING
        """),
            {
                "id": area_id,
                "pilot": pilot_id,
                "code": props["code"],
                "name": props["name"],
                "geometry": geometry_json(feature),
                "version": props["boundary_version"],
                "provenance": json.dumps(props),
            },
        )
    partition = verify_area_partition(connection, pilot_id)
    if not partition["exact_coverage"] or not partition["no_interior_overlap"]:
        raise ValueError("Service areas must cover the pilot without gaps or interior overlap")
    categories = yaml.safe_load((config_root / "config/categories.yaml").read_text())
    for category in categories["categories"]:
        connection.execute(
            text("""
            INSERT INTO categories (code,label,department_tag,default_severity,
                target_resolution_hours,duplicate_radius_m,requires_manual_categorisation,
                auto_merge_allowed,rule_version)
            VALUES (:code,:label,:department_tag,:default_severity,:target_resolution_hours,
                :duplicate_radius_m,:requires_manual_categorisation,:auto_merge_allowed,:version)
            ON CONFLICT (code) DO NOTHING
        """),
            {**category, "version": categories["version"]},
        )
    snapshot = json.loads((config_root / "fixtures/poi-snapshot.geojson").read_text())
    metadata = snapshot["properties"]
    snapshot_id = demo_id(metadata["version"])
    connection.execute(
        text("""
        INSERT INTO poi_snapshots (id,version,coverage,source,source_date,synthetic,
                                  coverage_complete,coverage_notes)
        SELECT :id,:version,ST_Multi(ST_Buffer(geom::geography,:margin)::geometry),
               :source,:date,true,:complete,:notes FROM pilots WHERE id = :pilot
        ON CONFLICT (id) DO NOTHING
    """),
        {
            "id": snapshot_id,
            "pilot": pilot_id,
            "version": metadata["version"],
            "margin": metadata["margin_m"],
            "source": metadata["source"],
            "date": metadata["source_date"],
            "complete": metadata["coverage_complete"],
            "notes": metadata["coverage_notes"],
        },
    )
    for feature in snapshot["features"]:
        props = feature["properties"]
        connection.execute(
            text("""
            INSERT INTO pois (id,snapshot_id,source_id,name,type,geom,synthetic)
            SELECT :id,:snapshot,:source,:name,:type,
                   ST_SetSRID(ST_GeomFromGeoJSON(:geometry),4326)::geography,true
            FROM poi_snapshots WHERE id = :snapshot
              AND ST_Covers(coverage,ST_SetSRID(ST_GeomFromGeoJSON(:geometry),4326))
              AND NOT EXISTS(SELECT 1 FROM pois WHERE id=:id)
            ON CONFLICT (id) DO NOTHING
        """),
            {
                "id": demo_id(metadata["version"] + ":" + props["source_id"]),
                "snapshot": snapshot_id,
                "source": props["source_id"],
                "name": props["name"],
                "type": props["type"],
                "geometry": geometry_json(feature),
            },
        )
    seed_identities(connection, settings, pilot_id)
    from app.domain.priority import seed_priority

    seed_priority(connection, pilot_id, snapshot_id)
    return pilot_id


def seed_identities(connection: Connection, settings: Settings, pilot_id: UUID) -> None:
    require_local_demo(settings)
    fixture = json.loads((PROJECT_ROOT / "fixtures/identities.json").read_text())
    scopes = json.loads((PROJECT_ROOT / "fixtures/identity-scopes.json").read_text())["scopes"]
    for identity in fixture["identities"]:
        user_id: UUID | None = connection.execute(
            text("""
            INSERT INTO users (id,auth_subject,display_name) VALUES (:id,:subject,:name)
            ON CONFLICT (auth_subject) DO NOTHING
            RETURNING id
        """),
            {
                "id": demo_id(identity["subject"]),
                "subject": identity["subject"],
                "name": identity["display_name"],
            },
        ).scalar_one_or_none()
        if user_id is None:
            continue
        # Provision once: rerunning the seed never grants a role to an existing user.
        for role in identity["roles"]:
            for code in scopes.get(identity["subject"], [None]):
                area_id = (
                    None
                    if code is None
                    else connection.execute(
                        text("SELECT id FROM areas WHERE pilot_id=:pilot AND code=:code"),
                        {"pilot": pilot_id, "code": code},
                    ).scalar_one()
                )
                connection.execute(
                    text("""
                    INSERT INTO user_roles (user_id,role,area_id)
                    VALUES (:user,:role,:area)
                """),
                    {"user": user_id, "role": role, "area": area_id},
                )
