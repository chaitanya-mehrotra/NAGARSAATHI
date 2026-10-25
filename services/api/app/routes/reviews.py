from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from app.domain.enums import Role
from app.intake import report_detail
from app.intake_schemas import ReportDetail
from app.review import ReviewDecision, decide
from app.routes.intake import CurrentActor

router = APIRouter(prefix="/api/v1")


@router.get("/reviews", response_model=list[ReportDetail])
def inbox(request: Request, actor: CurrentActor) -> list[ReportDetail]:
    grants = [grant for grant in actor.grants if grant.role in {Role.ADMIN, Role.REVIEWER}]
    if not grants:
        raise HTTPException(403, "Reviewer permission is required")
    global_scope = any(grant.area_id is None for grant in grants)
    areas = [grant.area_id for grant in grants if grant.area_id is not None]
    with request.app.state.engine.connect() as connection:
        ids = (
            connection.execute(
                text("""
            SELECT id FROM reports
            WHERE state IN ('submitted','awaiting_review','processing_failed')
              AND (:global OR area_id=ANY(CAST(:areas AS uuid[])))
            ORDER BY received_at,id LIMIT 50
        """),
                {"global": global_scope, "areas": areas},
            )
            .scalars()
            .all()
        )
        return [report_detail(connection, item, actor) for item in ids]


@router.post("/reviews/{report_id}/decision", response_model=ReportDetail)
def review(
    report_id: UUID, body: ReviewDecision, request: Request, actor: CurrentActor
) -> ReportDetail:
    if not (actor.has_role(Role.REVIEWER) or actor.has_role(Role.ADMIN)):
        raise HTTPException(403, "Reviewer permission is required")
    with request.app.state.engine.begin() as connection:
        return decide(connection, report_id, actor, body)
