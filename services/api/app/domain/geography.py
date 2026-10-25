import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text


class IssuePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False, strict=True)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False, strict=True)
    confirmed: bool = False
    uncertainty_m: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class AreaAssignment(BaseModel):
    state: Literal["located", "out_of_scope", "needs_review"]
    reason: str
    area_id: UUID | None = None
    area_code: str | None = None
    boundary_version: str | None = None


def assign_area(connection: Connection, pilot_id: UUID, point: IssuePoint) -> AreaAssignment:
    """Assign an already confirmed canonical pin, never infer position from address text."""
    if point.longitude is None or point.latitude is None:
        return AreaAssignment(state="needs_review", reason="missing_coordinates")
    if not point.confirmed:
        return AreaAssignment(state="needs_review", reason="pin_not_confirmed")
    rows = (
        connection.execute(
            text("""
        WITH point AS (SELECT ST_SetSRID(ST_MakePoint(:lon, :lat),4326) AS geom)
        SELECT p.boundary_version, ST_Covers(p.geom, point.geom) AS in_pilot,
               a.id AS area_id, a.code AS area_code
        FROM pilots p CROSS JOIN point
        LEFT JOIN LATERAL (
            SELECT id, code FROM areas
            WHERE pilot_id = p.id AND boundary_version = p.boundary_version
              AND effective_to IS NULL AND ST_Covers(geom, point.geom)
            ORDER BY code COLLATE "C" LIMIT 1
        ) a ON true
        WHERE p.id = :pilot AND p.enabled
    """),
            {"pilot": pilot_id, "lon": point.longitude, "lat": point.latitude},
        )
        .mappings()
        .all()
    )
    if not rows:
        return AreaAssignment(state="needs_review", reason="pilot_unavailable")
    row = rows[0]
    if not row["in_pilot"]:
        return AreaAssignment(
            state="out_of_scope", reason="outside_pilot", boundary_version=row["boundary_version"]
        )
    if row["area_id"] is None:
        return AreaAssignment(
            state="needs_review",
            reason="area_configuration_gap",
            boundary_version=row["boundary_version"],
        )
    if point.uncertainty_m is not None and point.uncertainty_m > 0:
        # A buffer crossing the assigned boundary is not a certain owning location.
        covered: bool = connection.execute(
            text("""
            SELECT ST_Covers(geom::geography,
                ST_Buffer(ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,:radius))
            FROM areas WHERE id = :area
        """),
            {
                "lon": point.longitude,
                "lat": point.latitude,
                "radius": point.uncertainty_m,
                "area": row["area_id"],
            },
        ).scalar_one()
        if not covered:
            return AreaAssignment(
                state="needs_review",
                reason="uncertainty_crosses_boundary",
                boundary_version=row["boundary_version"],
            )
    return AreaAssignment(
        state="located",
        reason="confirmed_pin",
        area_id=row["area_id"],
        area_code=row["area_code"],
        boundary_version=row["boundary_version"],
    )


def verify_area_partition(connection: Connection, pilot_id: UUID) -> dict[str, Any]:
    result = (
        connection.execute(
            text("""
        WITH selected AS (
            SELECT a.geom FROM areas a JOIN pilots p ON p.id = a.pilot_id
            WHERE p.id = :pilot AND a.boundary_version = p.boundary_version
              AND a.effective_to IS NULL
        ), combined AS (SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom FROM selected)
        SELECT (SELECT count(*) FROM selected) AS area_count,
          ST_Equals(p.geom, combined.geom) AS exact_coverage,
          NOT EXISTS (
            SELECT 1 FROM areas a JOIN areas b ON a.id < b.id AND a.pilot_id = b.pilot_id
            WHERE a.pilot_id = p.id AND a.effective_to IS NULL AND b.effective_to IS NULL
              AND ST_Area(ST_Intersection(a.geom,b.geom)) > 0
          ) AS no_interior_overlap
        FROM pilots p CROSS JOIN combined WHERE p.id = :pilot
    """),
            {"pilot": pilot_id},
        )
        .mappings()
        .one()
    )
    return dict(result)


def nearby_issue_ids(
    connection: Connection, pilot_id: UUID, category: str, point: IssuePoint, radius_m: float
) -> list[UUID]:
    """Radius retrieval only; it never merges issues and never filters by owning area."""
    if point.longitude is None or point.latitude is None or not point.confirmed:
        raise ValueError("A confirmed point is required")
    if not 0 <= radius_m <= 500:
        raise ValueError("Radius must be between 0 and 500 metres")
    return list(
        connection.execute(
            text("""
        SELECT id FROM issues WHERE pilot_id = :pilot AND category_code = :category
          AND status IN ('open','assigned','in_progress','resolution_pending','reopened')
          AND ST_DWithin(geom,ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,:radius)
        ORDER BY id
    """),
            {
                "pilot": pilot_id,
                "category": category,
                "lon": point.longitude,
                "lat": point.latitude,
                "radius": radius_m,
            },
        ).scalars()
    )


def geometry_json(feature: dict[str, Any]) -> str:
    return json.dumps(feature["geometry"])
