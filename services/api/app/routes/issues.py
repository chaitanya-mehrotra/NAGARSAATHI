from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text

from app.domain.enums import Role
from app.domain.issue_review import link_decision, merge, split
from app.domain.issues import candidates as find_candidates
from app.domain.issues import summary
from app.intake import report_detail
from app.issue_schemas import (
    Candidate,
    DuplicateReview,
    IssueDetail,
    IssueSummary,
    LinkDecision,
    MergeDecision,
    SplitDecision,
)
from app.routes.intake import CurrentActor

router = APIRouter(prefix="/api/v1")


def staff(actor: CurrentActor) -> None:
    if not (actor.has_role(Role.REVIEWER) or actor.has_role(Role.ADMIN)):
        raise HTTPException(403, "Reviewer permission is required")


@router.get("/issues", response_model=list[IssueSummary])
def issue_list(
    request: Request,
    actor: CurrentActor,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: UUID | None = None,
    reference: str | None = Query(default=None, max_length=128),
) -> list[IssueSummary]:
    staff(actor)
    grants = [g for g in actor.grants if g.role in {Role.REVIEWER, Role.ADMIN}]
    with request.app.state.engine.connect() as connection:
        ids = (
            connection.execute(
                text("""
          SELECT id FROM issues WHERE (:global OR area_id=ANY(CAST(:areas AS uuid[])))
            AND (CAST(:cursor AS uuid) IS NULL OR id>:cursor)
            AND (CAST(:reference AS text) IS NULL OR public_reference=:reference)
          ORDER BY id LIMIT :limit
        """),
                {
                    "global": any(g.area_id is None for g in grants),
                    "areas": [g.area_id for g in grants if g.area_id],
                    "cursor": cursor,
                    "reference": reference,
                    "limit": limit,
                },
            )
            .scalars()
            .all()
        )
        return [summary(connection, item) for item in ids]


@router.get("/issues/nearby", response_model=list[IssueSummary])
def nearby(
    request: Request,
    actor: CurrentActor,
    longitude: Annotated[float, Query(ge=-180, le=180)],
    latitude: Annotated[float, Query(ge=-90, le=90)],
    category: str,
) -> list[IssueSummary]:
    with request.app.state.engine.connect() as connection:
        ids = (
            connection.execute(
                text("""
          SELECT i.id FROM issues i JOIN categories c ON c.code=i.category_code
          WHERE i.category_code=:category AND i.status IN
            ('open','assigned','in_progress','resolution_pending','reopened') AND i.report_count>0
            AND ST_DWithin(i.geom,ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,
                           c.duplicate_radius_m)
          ORDER BY i.id LIMIT 20
        """),
                {"category": category, "lon": longitude, "lat": latitude},
            )
            .scalars()
            .all()
        )
        return [summary(connection, item) for item in ids]


@router.get("/issues/{issue_id}", response_model=IssueDetail)
def issue_detail(issue_id: UUID, request: Request, actor: CurrentActor) -> IssueDetail:
    staff(actor)
    with request.app.state.engine.connect() as connection:
        area = connection.execute(
            text("SELECT area_id FROM issues WHERE id=:id"), {"id": issue_id}
        ).scalar_one_or_none()
        if area is None or not actor.can_review(area):
            raise HTTPException(404, "Issue not found")
        reports = (
            connection.execute(
                text("""
          SELECT r.id,r.area_id FROM reports r JOIN issue_report_links l ON l.report_id=r.id
          WHERE l.issue_id=:id AND l.active ORDER BY r.received_at,r.id
        """),
                {"id": issue_id},
            )
            .mappings()
            .all()
        )
        events = (
            connection.execute(
                text("""
          SELECT action,reason,evidence,created_at FROM issue_events
          WHERE issue_id=:id ORDER BY created_at,id
        """),
                {"id": issue_id},
            )
            .mappings()
            .all()
        )
        return IssueDetail(
            **summary(connection, issue_id).model_dump(),
            reports=[
                report_detail(connection, row["id"], actor)
                for row in reports
                if actor.can_review(row["area_id"])
            ],
            events=[dict(row) for row in events],
        )


@router.get("/reviews/duplicates", response_model=list[DuplicateReview])
def duplicate_inbox(request: Request, actor: CurrentActor) -> list[DuplicateReview]:
    staff(actor)
    grants = [g for g in actor.grants if g.role in {Role.REVIEWER, Role.ADMIN}]
    with request.app.state.engine.connect() as connection:
        reports = (
            connection.execute(
                text("""
          SELECT * FROM reports WHERE state='awaiting_review' AND validation_status='accepted'
            AND area_id IS NOT NULL AND (:global OR area_id=ANY(CAST(:areas AS uuid[])))
          ORDER BY received_at,id LIMIT 50
        """),
                {
                    "global": any(g.area_id is None for g in grants),
                    "areas": [g.area_id for g in grants if g.area_id],
                },
            )
            .mappings()
            .all()
        )
        result = []
        for report in reports:
            rows = find_candidates(connection, report)
            candidates = [
                Candidate(
                    id=row["id"],
                    issue=summary(connection, row["id"]),
                    distance_m=row["distance_m"],
                    kind="recurrence" if row["status"] == "resolved" else "nearby",
                    asset_conflict=row["asset_conflict"],
                    issue_revision=row["row_version"],
                    report_revision=report["content_revision"],
                )
                for row in rows
                if actor.can_review(row["area_id"])
            ]
            result.append(
                DuplicateReview(
                    report=report_detail(connection, report["id"], actor),
                    candidates=candidates,
                    needs_cross_area_admin=any(not actor.can_review(r["area_id"]) for r in rows),
                )
            )
        return result


@router.post("/reviews/duplicates/{report_id}/decision", response_model=IssueSummary | None)
def duplicate_decision(
    report_id: UUID, body: LinkDecision, request: Request, actor: CurrentActor
) -> IssueSummary | None:
    staff(actor)
    with request.app.state.engine.begin() as connection:
        result = link_decision(connection, report_id, actor, body)
        return None if body.action == "clarify" else summary(connection, result)


@router.post("/issues/{issue_id}/merge", response_model=IssueSummary)
def merge_issues(
    issue_id: UUID, body: MergeDecision, request: Request, actor: CurrentActor
) -> IssueSummary:
    staff(actor)
    with request.app.state.engine.begin() as connection:
        return merge(connection, issue_id, actor, body)


@router.post("/issues/{issue_id}/split", response_model=IssueSummary)
def split_issue(
    issue_id: UUID, body: SplitDecision, request: Request, actor: CurrentActor
) -> IssueSummary:
    staff(actor)
    with request.app.state.engine.begin() as connection:
        return split(connection, issue_id, actor, body)
