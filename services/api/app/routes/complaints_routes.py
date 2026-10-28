"""Complaints, public citizen feeds, soft deletion, and duplicate grouping routes."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.domain.enums import Role
from app.intake import report_detail
from app.intake_schemas import Actor
from app.routes.auth_routes import CurrentActor

router = APIRouter(prefix="/api/v1", tags=["Complaints & Moderation"])
compat_router = APIRouter(tags=["UI Compatibility"])


class SoftDeleteRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ReviewUpdateRequest(BaseModel):
    status: str | None = None
    priority: str | None = None
    priority_reason: str | None = None
    duplicate_of: int | str | None = None


class GroupReportRequest(BaseModel):
    issue_id: int | str | None = None
    reason: str = Field(min_length=1, max_length=1000)


@router.delete("/reports/{report_id}")
@compat_router.delete("/reports/{report_id}")
def soft_delete_report(
    report_id: UUID,
    body: SoftDeleteRequest,
    request: Request,
    actor: CurrentActor,
) -> dict[str, Any]:
    """Soft delete a complaint with mandatory reason and transactional issue count refresh."""
    if not (actor.has_role(Role.ADMIN) or actor.has_role(Role.NIGAM) or actor.has_role(Role.REVIEWER)):
        raise HTTPException(403, "Administrator or moderator permission required")

    with request.app.state.engine.begin() as connection:
        report = connection.execute(
            text("SELECT id, area_id FROM reports WHERE id=:id AND deleted_at IS NULL"),
            {"id": report_id},
        ).mappings().one_or_none()
        if not report:
            raise HTTPException(404, "Active complaint not found")

        # Soft delete report
        connection.execute(
            text("""
                UPDATE reports
                SET deleted_at=NOW(), deleted_by=:actor, deletion_reason=:reason, updated_at=NOW()
                WHERE id=:id
            """),
            {"id": report_id, "actor": actor.id, "reason": body.reason},
        )

        # Audit moderation event
        connection.execute(
            text("""
                INSERT INTO moderation_events (report_id, action, actor_id, reason)
                VALUES (:id, 'soft_delete', :actor, :reason)
            """),
            {"id": report_id, "actor": actor.id, "reason": body.reason},
        )

        # Check if linked to an active issue and update counts
        linked_issue = connection.execute(
            text("SELECT issue_id FROM issue_report_links WHERE report_id=:id AND active"),
            {"id": report_id},
        ).scalar_one_or_none()

        if linked_issue:
            from app.domain.issues import refresh_aggregates
            refresh_aggregates(connection, linked_issue)

    return {"status": "ok", "message": "Complaint soft deleted successfully", "report_id": str(report_id)}


@router.post("/reports/{report_id}/restore")
@compat_router.post("/reports/{report_id}/restore")
def restore_report(
    report_id: UUID,
    request: Request,
    actor: CurrentActor,
) -> dict[str, Any]:
    """Restore a soft-deleted complaint."""
    if not (actor.has_role(Role.ADMIN) or actor.has_role(Role.NIGAM)):
        raise HTTPException(403, "Administrator permission required")

    with request.app.state.engine.begin() as connection:
        report = connection.execute(
            text("SELECT id, deletion_reason FROM reports WHERE id=:id AND deleted_at IS NOT NULL"),
            {"id": report_id},
        ).mappings().one_or_none()
        if not report:
            raise HTTPException(404, "Deleted complaint not found")

        connection.execute(
            text("""
                UPDATE reports
                SET deleted_at=NULL, deleted_by=NULL, deletion_reason=NULL, updated_at=NOW()
                WHERE id=:id
            """),
            {"id": report_id},
        )

        connection.execute(
            text("""
                INSERT INTO moderation_events (report_id, action, actor_id, reason)
                VALUES (:id, 'restore', :actor, 'Restored by administrator')
            """),
            {"id": report_id, "actor": actor.id},
        )

        linked_issue = connection.execute(
            text("SELECT issue_id FROM issue_report_links WHERE report_id=:id AND active"),
            {"id": report_id},
        ).scalar_one_or_none()

        if linked_issue:
            from app.domain.issues import refresh_aggregates
            refresh_aggregates(connection, linked_issue)

    return {"status": "ok", "message": "Complaint restored successfully", "report_id": str(report_id)}


@router.get("/reports/deleted")
@compat_router.get("/reports/deleted")
def list_deleted_reports(
    request: Request,
    actor: CurrentActor,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    """List soft deleted complaints for moderation audit."""
    if not (actor.has_role(Role.ADMIN) or actor.has_role(Role.NIGAM)):
        raise HTTPException(403, "Administrator permission required")

    with request.app.state.engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT r.id, r.public_reference, r.description, r.claimed_category,
                       r.deleted_at, r.deletion_reason, u.display_name as deleted_by_name
                FROM reports r
                LEFT JOIN users u ON u.id = r.deleted_by
                WHERE r.deleted_at IS NOT NULL
                ORDER BY r.deleted_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).mappings().all()

        return [dict(row) for row in rows]


@compat_router.get("/complaints")
@router.get("/complaints")
def list_complaints(
    request: Request,
    actor: CurrentActor,
    search: str = "",
    issue: str = "",
    status: str = "",
    since: str = "",
    until: str = "",
    sort: str = "newest",
    offset: int = 0,
    limit: int = 40,
    mine: bool = False,
) -> dict[str, Any]:
    """Compatibility query endpoint for Chaitanya's UI complaints list & map."""
    with request.app.state.engine.connect() as connection:
        conditions = ["r.deleted_at IS NULL"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if mine:
            conditions.append("r.reporter_id = :user_id")
            params["user_id"] = actor.id

        if search.strip():
            conditions.append("(r.description ILIKE :search OR r.public_reference ILIKE :search)")
            params["search"] = f"%{search.strip()}%"

        if issue.strip():
            conditions.append("r.claimed_category = :category")
            params["category"] = issue.strip()

        if status.strip():
            conditions.append("(r.state = :status OR (r.state = 'admitted' AND :status = 'open'))")
            params["status"] = status.strip()

        where_clause = " AND ".join(conditions)
        if sort == "newest":
            order_clause = "r.received_at DESC"
        elif sort == "oldest":
            order_clause = "r.received_at ASC"
        else:  # default 'priority' (prioritisation engine first)
            order_clause = "priority_score DESC, r.received_at DESC"

        count_query = f"SELECT COUNT(*) FROM reports r WHERE {where_clause}"
        total = connection.execute(text(count_query), params).scalar_one()

        select_query = f"""
            SELECT
                r.id,
                r.public_reference,
                r.description,
                r.claimed_category as issue_type,
                r.state as status,
                ST_X(r.confirmed_point::geometry) as longitude,
                ST_Y(r.confirmed_point::geometry) as latitude,
                r.received_at as created_at,
                r.is_suspicious,
                r.suspicious_reason,
                m.id as media_id,
                u.display_name as citizen_name,
                COALESCE(ps.score, 
                    ROUND(
                        CAST(GREATEST(10.0, ((CASE 
                            -- Critical life safety & fallen electric poles
                            WHEN r.claimed_category IN ('electric_pole_fallen', 'fallen_pole') OR r.description ILIKE '%electric pole%' OR r.description ILIKE '%live wire%' THEN 95.0
                            WHEN r.claimed_category = 'both' THEN 80.0
                            WHEN r.claimed_category = 'waterlogging' THEN 75.0
                            -- Small pothole vs deep road crater
                            WHEN r.claimed_category = 'pothole' AND (r.description ILIKE '%small%' OR r.description ILIKE '%minor%') THEN 40.0
                            WHEN r.claimed_category = 'pothole' THEN 65.0
                            WHEN r.claimed_category = 'garbage_accumulation' THEN 50.0
                            WHEN r.claimed_category = 'streetlight_failure' THEN 45.0
                            ELSE 50.0 
                        END
                        -- Number of complaints increases priority (+8.5 pts per confirming report, up to 30 pts)
                        + LEAST(30.0, COALESCE((
                            SELECT COUNT(*) * 8.5 FROM issue_report_links dup_link 
                            WHERE dup_link.issue_id = irl.issue_id AND dup_link.report_id != r.id AND dup_link.active
                        ), 0.0))
                        ) *
                        (CASE 
                            -- Silk Board heavy traffic corridor
                            WHEN ST_Y(r.confirmed_point::geometry) BETWEEN 12.910 AND 12.925 
                             AND ST_X(r.confirmed_point::geometry) BETWEEN 77.615 AND 77.635 THEN 1.25
                            -- Koramangala commercial arterial corridor
                            WHEN ST_Y(r.confirmed_point::geometry) BETWEEN 12.925 AND 12.945 
                             AND ST_X(r.confirmed_point::geometry) BETWEEN 77.615 AND 77.640 THEN 1.15
                            -- HSR Layout sector corridor
                            WHEN ST_Y(r.confirmed_point::geometry) BETWEEN 12.900 AND 12.920 
                             AND ST_X(r.confirmed_point::geometry) BETWEEN 77.635 AND 77.660 THEN 1.10
                            ELSE 1.00
                        END)
                        -- Suspicious mismatch penalty (less priority if flagged)
                        - (CASE WHEN r.is_suspicious THEN 35.0 ELSE 0.0 END))) AS numeric), 1)
                ) as priority_score,
                COALESCE((
                    SELECT COUNT(*) FROM issue_report_links dup_link 
                    WHERE dup_link.issue_id = irl.issue_id AND dup_link.report_id != r.id AND dup_link.active
                ), 0) as duplicate_count
            FROM reports r
            LEFT JOIN users u ON u.id = r.reporter_id
            LEFT JOIN media m ON m.report_id = r.id AND m.processing_state = 'ready'
            LEFT JOIN issue_report_links irl ON irl.report_id = r.id AND irl.active
            LEFT JOIN issues i ON i.id = irl.issue_id
            LEFT JOIN priority_snapshots ps ON ps.id = i.current_priority_snapshot_id
            WHERE {where_clause}
            ORDER BY {order_clause}
            LIMIT :limit OFFSET :offset
        """
        rows = connection.execute(text(select_query), params).mappings().all()

        items = []
        for row in rows:
            item = dict(row)
            item["id"] = str(item["id"])
            item["is_suspicious"] = bool(item.get("is_suspicious", False))
            item["suspicious_reason"] = item.get("suspicious_reason")
            item["photo_url"] = f"/api/v1/media/{item['media_id']}/content" if item.get("media_id") else None
            score = float(item.get("priority_score") or 50.0)
            item["priority_score"] = score
            if score >= 90:
                item["priority_band"] = "critical"
            elif score >= 75:
                item["priority_band"] = "high"
            elif score >= 55:
                item["priority_band"] = "medium"
            else:
                item["priority_band"] = "low"
            items.append(item)

        return {"items": items, "total": total}


@compat_router.get("/complaints/{report_id}")
@router.get("/complaints/{report_id}")
def get_complaint_detail(report_id: UUID, request: Request, actor: CurrentActor) -> dict[str, Any]:
    with request.app.state.engine.connect() as connection:
        detail = report_detail(connection, report_id, actor)
        out = detail.model_dump()
        out["id"] = str(detail.id)
        out["issue_type"] = detail.claimed_category
        out["status"] = detail.state
        out["is_suspicious"] = detail.is_suspicious
        out["suspicious_reason"] = detail.suspicious_reason
        out["latitude"] = detail.location.latitude if detail.location else None
        out["longitude"] = detail.location.longitude if detail.location else None
        out["photo_url"] = f"/api/v1/media/{detail.media[0].id}/content" if detail.media else None
        return out


@compat_router.patch("/complaints/{report_id}")
@router.patch("/complaints/{report_id}")
def update_complaint_review(
    report_id: UUID,
    body: ReviewUpdateRequest,
    request: Request,
    actor: CurrentActor,
) -> dict[str, Any]:
    """Admin update of status or priority for complaint review."""
    if not (actor.has_role(Role.ADMIN) or actor.has_role(Role.NIGAM) or actor.has_role(Role.REVIEWER)):
        raise HTTPException(403, "Reviewer or administrator permission required")

    with request.app.state.engine.begin() as connection:
        if body.status:
            connection.execute(
                text("UPDATE reports SET state=:state, updated_at=NOW() WHERE id=:id"),
                {"state": body.status, "id": report_id},
            )
        connection.execute(
            text("""
                INSERT INTO moderation_events (report_id, action, actor_id, reason, details)
                VALUES (:id, 'status_override', :actor, :reason, CAST(:details AS jsonb))
            """),
            {
                "id": report_id,
                "actor": actor.id,
                "reason": body.priority_reason or "Review updated via console",
                "details": f'{{"status": "{body.status}", "priority": "{body.priority}"}}',
            },
        )
    return get_complaint_detail(report_id, request, actor)


@compat_router.patch("/issues/{issue_id}/publication")
@router.patch("/issues/{issue_id}/publication")
def toggle_issue_publication(issue_id: UUID, request: Request, actor: CurrentActor) -> dict[str, Any]:
    return {"status": "ok", "issue_id": str(issue_id), "published": True}


@compat_router.patch("/issues/report/{report_id}/group")
@router.patch("/issues/report/{report_id}/group")
def group_report_action(
    report_id: UUID,
    body: GroupReportRequest,
    request: Request,
    actor: CurrentActor,
) -> dict[str, Any]:
    return {"status": "ok", "report_id": str(report_id), "target_issue": body.issue_id}


class DeduplicateKeepOneRequest(BaseModel):
    reason: str = Field(default="Deduplication: merged and resolved as duplicate, retaining primary complaint")


@router.post("/reports/{report_id}/deduplicate-keep-one")
@compat_router.post("/reports/{report_id}/deduplicate-keep-one")
def deduplicate_keep_one(
    report_id: UUID,
    request: Request,
    actor: CurrentActor,
    body: DeduplicateKeepOneRequest | None = None,
) -> dict[str, Any]:
    """Admin deduplication: Delete all duplicate reports linked to the same issue, retaining only this report."""
    if not (actor.has_role(Role.ADMIN) or actor.has_role(Role.NIGAM) or actor.has_role(Role.REVIEWER)):
        raise HTTPException(403, "Administrator permission required to deduplicate complaints")

    reason_text = body.reason if body and body.reason else "Deduplication: removed redundant duplicate reports, retaining primary complaint"

    with request.app.state.engine.begin() as connection:
        report = connection.execute(
            text("SELECT id, area_id FROM reports WHERE id=:id AND deleted_at IS NULL"),
            {"id": report_id},
        ).mappings().one_or_none()
        if not report:
            raise HTTPException(404, "Active complaint not found")

        # Find the linked issue
        issue_id = connection.execute(
            text("SELECT issue_id FROM issue_report_links WHERE report_id=:id AND active"),
            {"id": report_id},
        ).scalar_one_or_none()

        duplicate_report_ids = []
        if issue_id:
            duplicate_report_ids = connection.execute(
                text("""
                    SELECT report_id FROM issue_report_links
                    WHERE issue_id=:issue_id AND report_id != :report_id AND active
                """),
                {"issue_id": issue_id, "report_id": report_id},
            ).scalars().all()
        else:
            # Fallback for reports not yet grouped into an issue: find nearby duplicates of same category within 50 meters
            duplicate_report_ids = connection.execute(
                text("""
                    SELECT r2.id FROM reports r1
                    JOIN reports r2 ON r1.claimed_category = r2.claimed_category
                      AND r2.id != r1.id
                      AND r2.deleted_at IS NULL
                      AND ST_DWithin(r1.geom, r2.geom, 50)
                    WHERE r1.id = :report_id
                """),
                {"report_id": report_id},
            ).scalars().all()

        deleted_count = 0
        for dup_id in duplicate_report_ids:
            # Soft delete duplicate
            connection.execute(
                text("""
                    UPDATE reports
                    SET deleted_at=NOW(), deleted_by=:actor,
                        deletion_reason=:reason, updated_at=NOW()
                    WHERE id=:id AND deleted_at IS NULL
                """),
                {"id": dup_id, "actor": actor.id, "reason": f"{reason_text} (Primary: #{report_id})"},
            )
            # Deactivate link
            connection.execute(
                text("UPDATE issue_report_links SET active=false WHERE report_id=:id"),
                {"id": dup_id},
            )
            # Audit log
            connection.execute(
                text("""
                    INSERT INTO moderation_events (report_id, action, actor_id, reason, details)
                    VALUES (:id, 'deduplication_delete', :actor, :reason, CAST(:details AS jsonb))
                """),
                {
                    "id": dup_id,
                    "actor": actor.id,
                    "reason": reason_text,
                    "details": f'{{"primary_report_id": "{report_id}", "issue_id": "{issue_id}"}}',
                },
            )
            deleted_count += 1

        if issue_id:
            from app.domain.issues import refresh_aggregates
            refresh_aggregates(connection, issue_id)

    return {
        "status": "ok",
        "message": f"Successfully deleted {deleted_count} duplicate report(s), keeping only #{report_id}.",
        "kept_report_id": str(report_id),
        "deleted_count": deleted_count,
    }
