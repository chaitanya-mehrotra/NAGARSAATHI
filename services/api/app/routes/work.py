import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import text

from app.domain.enums import Role
from app.domain.issue_locks import category_locks
from app.domain.issue_review import action_lock, audit, replay
from app.domain.issues import event, summary
from app.domain.priority import queue_refresh
from app.intake import verify_stored_media
from app.intake_schemas import Actor
from app.issue_schemas import IssueSummary
from app.routes.intake import CurrentActor
from app.schemas import Contract

router = APIRouter(prefix="/api/v1/work")


class WorkAction(Contract):
    request_id: UUID
    expected_version: int = Field(ge=1)
    action: Literal["start", "submit_repair", "verify", "reject", "archive", "reopen"]
    reason: str = Field(min_length=5, max_length=1000)
    media_ids: list[UUID] = Field(default_factory=list, max_length=3)


def operator(actor: Actor, row: Any) -> bool:
    return row["assigned_operator_id"] == actor.id and any(
        g.role == Role.OPERATOR and (g.area_id is None or g.area_id == row["area_id"])
        for g in actor.grants
    )


@router.get("", response_model=list[IssueSummary])
def tasks(request: Request, actor: CurrentActor) -> list[IssueSummary]:
    if not actor.has_role(Role.OPERATOR):
        raise HTTPException(403, "Operator permission required")
    with request.app.state.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT * FROM issues WHERE assigned_operator_id=:id "
                "AND status IN ('assigned','in_progress','resolution_pending','reopened') "
                "ORDER BY first_accepted_at,id LIMIT 50"
            ),
            {"id": actor.id},
        ).mappings()
        return [summary(connection, r["id"]) for r in rows if operator(actor, r)]


@router.get("/{issue_id}")
def detail(issue_id: UUID, request: Request, actor: CurrentActor) -> dict[str, Any]:
    with request.app.state.engine.connect() as connection:
        row = (
            connection.execute(text("SELECT * FROM issues WHERE id=:id"), {"id": issue_id})
            .mappings()
            .one_or_none()
        )
        if row is None or not (actor.can_review(row["area_id"]) or operator(actor, row)):
            raise HTTPException(404, "Work issue not found")
        records = (
            connection.execute(
                text("SELECT * FROM resolution_records WHERE issue_id=:id ORDER BY repaired_at,id"),
                {"id": issue_id},
            )
            .mappings()
            .all()
        )
        history = (
            connection.execute(
                text(
                    "SELECT action,reason,created_at FROM issue_events "
                    "WHERE issue_id=:id ORDER BY created_at,id"
                ),
                {"id": issue_id},
            )
            .mappings()
            .all()
        )
        return {
            "issue": summary(connection, issue_id),
            "archived_at": row["archived_at"],
            "repairs": [dict(r) for r in records],
            "events": [dict(r) for r in history],
        }


@router.post("/{issue_id}", response_model=IssueSummary)
def action(issue_id: UUID, body: WorkAction, request: Request, actor: CurrentActor) -> IssueSummary:
    with request.app.state.engine.begin() as connection:
        action_lock(connection, body.request_id)
        initial = (
            connection.execute(text("SELECT * FROM issues WHERE id=:id"), {"id": issue_id})
            .mappings()
            .one_or_none()
        )
        if initial is None or not (
            actor.can_review(initial["area_id"]) or operator(actor, initial)
        ):
            raise HTTPException(404, "Work issue not found")
        category_locks(connection, initial["pilot_id"], [initial["category_code"]])
        row = (
            connection.execute(
                text("SELECT * FROM issues WHERE id=:id FOR UPDATE"), {"id": issue_id}
            )
            .mappings()
            .one()
        )
        is_operator = operator(actor, row)
        if body.action in {"start", "submit_repair"}:
            if not is_operator:
                raise HTTPException(403, "Only the assigned area operator can do this")
        elif not actor.can_review(row["area_id"]):
            raise HTTPException(403, "Reviewer permission required")
        if replay(connection, actor, issue_id, "work_action", body):
            return summary(connection, issue_id)
        if body.expected_version != row["row_version"]:
            raise HTTPException(409, "Issue changed. Reload before continuing.")
        allowed = {
            "start": {"assigned", "reopened"},
            "submit_repair": {"in_progress"},
            "verify": {"resolution_pending"},
            "reject": {"resolution_pending"},
            "archive": {"resolved"},
            "reopen": {"resolved"},
        }
        if row["status"] not in allowed[body.action]:
            raise HTTPException(409, "Forbidden work transition")
        states = {
            "start": "in_progress",
            "submit_repair": "resolution_pending",
            "verify": "resolved",
            "reject": "in_progress",
            "archive": "resolved",
            "reopen": "reopened",
        }
        if body.action == "submit_repair":
            if not body.media_ids or len(set(body.media_ids)) != len(body.media_ids):
                raise HTTPException(422, "Attach one to three distinct repair photos")
            photos = (
                connection.execute(
                    text("SELECT * FROM media WHERE id=ANY(:ids) ORDER BY id FOR UPDATE"),
                    {"ids": body.media_ids},
                )
                .mappings()
                .all()
            )
            if len(photos) != len(body.media_ids) or any(p["owner_id"] != actor.id for p in photos):
                raise HTTPException(404, "Repair photo not found")
            for photo in photos:
                if (
                    photo["report_id"]
                    or photo["repair_issue_id"]
                    or photo["processing_state"] != "ready"
                    or photo["expires_at"] <= datetime.now(UTC)
                ):
                    raise HTTPException(409, "Repair photo is attached, incomplete or expired")
                verify_stored_media(request.app.state.media_storage, photo)
            connection.execute(
                text("UPDATE media SET repair_issue_id=:issue WHERE id=ANY(:ids)"),
                {"issue": issue_id, "ids": body.media_ids},
            )
            connection.execute(
                text("""INSERT INTO resolution_records(issue_id,repaired_at,operator_id,
              notes,evidence_media_ids,verification_state,issue_revision)
              VALUES(:id,now(),:operator,:notes,CAST(:media AS jsonb),'pending',:revision)"""),
                {
                    "id": issue_id,
                    "operator": actor.id,
                    "notes": body.reason,
                    "media": json.dumps([str(v) for v in body.media_ids]),
                    "revision": row["row_version"] + 1,
                },
            )
        if body.action in {"verify", "reject"}:
            repair = (
                connection.execute(
                    text(
                        "SELECT * FROM resolution_records WHERE issue_id=:id "
                        "AND verification_state='pending' "
                        "ORDER BY repaired_at DESC,id DESC LIMIT 1 FOR UPDATE"
                    ),
                    {"id": issue_id},
                )
                .mappings()
                .one_or_none()
            )
            if repair is None:
                raise HTTPException(409, "No pending repair evidence")
            if body.action == "verify" and repair["issue_revision"] != row["row_version"]:
                raise HTTPException(
                    409, "New evidence arrived after repair. Reject and inspect again."
                )
            if body.action == "verify" and repair["operator_id"] == actor.id:
                raise HTTPException(403, "A different reviewer must verify the repair")
            if body.action == "verify":
                evidence = [UUID(value) for value in repair["evidence_media_ids"]]
                photos = (
                    connection.execute(
                        text(
                            "SELECT * FROM media WHERE repair_issue_id=:issue "
                            "AND id=ANY(CAST(:ids AS uuid[]))"
                        ),
                        {"issue": issue_id, "ids": evidence},
                    )
                    .mappings()
                    .all()
                )
                if not photos or len(photos) != len(evidence):
                    raise HTTPException(409, "Repair evidence is incomplete")
                for photo in photos:
                    verify_stored_media(request.app.state.media_storage, photo)
            connection.execute(
                text(
                    "UPDATE resolution_records SET verification_state=:state,"
                    "verifier_id=:actor,decided_at=now() WHERE id=:id"
                ),
                {
                    "id": repair["id"],
                    "actor": actor.id,
                    "state": "verified" if body.action == "verify" else "failed",
                },
            )
        connection.execute(
            text("""UPDATE issues SET status=:status,row_version=row_version+1,
          archived_at=CASE WHEN :action='archive' THEN now()
            WHEN :action='reopen' THEN NULL ELSE archived_at END,
          critical_override=CASE WHEN :action='verify' THEN false ELSE critical_override END,
          critical_review_due_at=CASE WHEN :action='verify' THEN NULL
            ELSE critical_review_due_at END
          WHERE id=:id"""),
            {"id": issue_id, "status": states[body.action], "action": body.action},
        )
        event(
            connection,
            issue_id,
            body.action,
            actor.id,
            body.reason,
            {"media_ids": [str(v) for v in body.media_ids]},
        )
        audit(connection, actor, issue_id, "work_action", body, issue_id, row["row_version"] + 1)
        if body.action not in {"verify", "archive"}:
            queue_refresh(connection, {**dict(row), "row_version": row["row_version"] + 1})
        return summary(connection, issue_id)
