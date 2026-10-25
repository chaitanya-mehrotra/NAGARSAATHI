from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text

from app.domain.issue_locks import category_locks
from app.domain.issue_review import action_lock, audit, replay
from app.domain.issues import event, summary
from app.domain.priority import queue_refresh
from app.domain.staff_queue import area_summary, page
from app.issue_schemas import IssueSummary
from app.queue_schemas import AreaCategorySummary, Assignee, Assignment, QueueFilters, QueuePage
from app.routes.intake import CurrentActor
from app.routes.issues import staff

router = APIRouter(prefix="/api/v1")


@router.get("/staff/queue", response_model=QueuePage)
def queue(
    request: Request,
    actor: CurrentActor,
    filters: Annotated[QueueFilters, Depends()],
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> QueuePage:
    staff(actor)
    with (
        request.app.state.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection,
        connection.begin(),
    ):
        return page(connection, actor, filters, cursor, limit)


@router.get("/areas/summary", response_model=list[AreaCategorySummary])
def areas(request: Request, actor: CurrentActor) -> list[AreaCategorySummary]:
    staff(actor)
    with (
        request.app.state.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection,
        connection.begin(),
    ):
        return area_summary(connection, actor)


@router.get("/issues/{issue_id}/assignees", response_model=list[Assignee])
def assignees(issue_id: UUID, request: Request, actor: CurrentActor) -> list[Assignee]:
    staff(actor)
    with request.app.state.engine.connect() as connection:
        area = connection.execute(
            text("SELECT area_id FROM issues WHERE id=:id"), {"id": issue_id}
        ).scalar_one_or_none()
        if area is None or not actor.can_review(area):
            raise HTTPException(404, "Issue not found")
        rows = connection.execute(
            text("""
          SELECT DISTINCT u.id,u.display_name FROM users u JOIN user_roles r ON r.user_id=u.id
          WHERE u.active AND r.role='operator' AND (r.area_id IS NULL OR r.area_id=:area)
          ORDER BY u.display_name,u.id
        """),
            {"area": area},
        ).mappings()
        return [Assignee.model_validate(dict(row)) for row in rows]


@router.post("/issues/{issue_id}/assign", response_model=IssueSummary)
def assign(issue_id: UUID, body: Assignment, request: Request, actor: CurrentActor) -> IssueSummary:
    staff(actor)
    with request.app.state.engine.begin() as connection:
        action_lock(connection, body.request_id)
        initial = (
            connection.execute(text("SELECT * FROM issues WHERE id=:id"), {"id": issue_id})
            .mappings()
            .one_or_none()
        )
        if initial is None or not actor.can_review(initial["area_id"]):
            raise HTTPException(404, "Issue not found")
        category_locks(connection, initial["pilot_id"], [initial["category_code"]])
        row = (
            connection.execute(
                text("SELECT * FROM issues WHERE id=:id FOR UPDATE"), {"id": issue_id}
            )
            .mappings()
            .one()
        )
        if not actor.can_review(row["area_id"]):
            raise HTTPException(404, "Issue not found")
        if replay(connection, actor, issue_id, "assign_issue", body):
            return summary(connection, issue_id)
        if row["row_version"] != body.expected_version:
            raise HTTPException(409, "Issue changed. Reload before assigning.")
        if row["status"] not in {"open", "assigned", "reopened"}:
            raise HTTPException(409, "Only open, assigned or reopened issues can be assigned")
        if body.operator_id is not None:
            valid = connection.execute(
                text("""
              SELECT u.id FROM users u JOIN user_roles r ON r.user_id=u.id
              WHERE u.id=:id AND u.active AND r.role='operator'
                AND (r.area_id IS NULL OR r.area_id=:area) LIMIT 1
            """),
                {"id": body.operator_id, "area": row["area_id"]},
            ).scalar_one_or_none()
            if valid is None:
                raise HTTPException(422, "Choose an active operator with permission for this area")
        elif body.team:
            raise HTTPException(422, "Choose an operator before adding a team label")
        status = (
            "assigned"
            if body.operator_id
            else ("reopened" if row["status"] == "reopened" else "open")
        )
        connection.execute(
            text("""
          UPDATE issues SET assigned_operator_id=:operator,assigned_team=:team,status=:status,
            row_version=row_version+1 WHERE id=:id
        """),
            {
                "id": issue_id,
                "operator": body.operator_id,
                "team": body.team.strip() if body.team else None,
                "status": status,
            },
        )
        event(
            connection,
            issue_id,
            "assigned" if body.operator_id else "unassigned",
            actor.id,
            body.reason,
            {
                "operator_id": str(body.operator_id) if body.operator_id else None,
                "team": body.team,
                "previous_operator_id": str(row["assigned_operator_id"])
                if row["assigned_operator_id"]
                else None,
            },
        )
        audit(connection, actor, issue_id, "assign_issue", body, issue_id, row["row_version"] + 1)
        queue_refresh(connection, {**dict(row), "row_version": row["row_version"] + 1})
        return summary(connection, issue_id)
