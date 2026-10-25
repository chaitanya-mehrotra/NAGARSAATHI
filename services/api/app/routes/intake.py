from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from app.adapters.local_media import decode_photo
from app.auth import load_actor
from app.domain.enums import Role
from app.intake import report_detail, submit_report, upload_receipt, verify_stored_media
from app.intake_schemas import Actor, ReportDetail, ReportPage, ReportSubmission, UploadReceipt

router = APIRouter(prefix="/api/v1")
bearer = HTTPBearer(auto_error=False)


def authenticated(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Actor:
    if credentials is None or len(credentials.credentials) > 8192:
        raise HTTPException(401, "A bearer identity token is required")
    subject = request.app.state.tokens.subject(credentials.credentials)
    with request.app.state.engine.connect() as connection:
        return load_actor(connection, subject, request.app.state.settings.auth_provider == "demo")


CurrentActor = Annotated[Actor, Depends(authenticated)]


def citizen(actor: Actor) -> None:
    if not actor.has_role(Role.CITIZEN):
        raise HTTPException(403, "Citizen permission is required")


@router.get("/me", response_model=Actor)
def me(actor: CurrentActor) -> Actor:
    return actor


@router.post(
    "/uploads",
    response_model=UploadReceipt,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                "image/png": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
)
async def upload(request: Request, actor: CurrentActor) -> UploadReceipt:
    if not (actor.has_role(Role.CITIZEN) or actor.has_role(Role.OPERATOR)):
        raise HTTPException(403, "Citizen or operator permission required")
    settings = request.app.state.settings
    declared = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if declared not in {"image/jpeg", "image/png"}:
        raise HTTPException(415, "Send JPEG or PNG bytes as the request body")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > settings.upload_max_bytes:
            raise HTTPException(413, "Photo exceeds the upload byte limit")
        content.extend(chunk)
    # Decode and local filesystem/SQL work outside the async event loop.
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(persist_upload, request, actor, bytes(content), declared)


def persist_upload(request: Request, actor: Actor, content: bytes, mime: str) -> UploadReceipt:
    settings = request.app.state.settings
    photo = decode_photo(content, mime, settings)
    media_id = uuid4()
    original_key, display_key = f"{media_id.hex}/original", f"{media_id.hex}/display.jpg"
    storage = request.app.state.media_storage
    written: list[str] = []
    try:
        storage.put(original_key, content)
        written.append(original_key)
        storage.put(display_key, photo.derivative)
        written.append(display_key)
        with request.app.state.engine.begin() as connection:
            row = (
                connection.execute(
                    text("""
                INSERT INTO media (id,owner_id,storage_key,original_sha256,derivative_sha256,
                  mime,width,height,byte_size,derivative_key,processing_state,expires_at)
                VALUES (:id,:owner,:original,:hash,:display_hash,:mime,:width,:height,:size,
                  :display,'uploaded',:expires) RETURNING *
            """),
                    {
                        "id": media_id,
                        "owner": actor.id,
                        "original": original_key,
                        "display": display_key,
                        "hash": photo.original_hash,
                        "display_hash": photo.derivative_hash,
                        "mime": photo.mime,
                        "width": photo.width,
                        "height": photo.height,
                        "size": len(content),
                        "expires": datetime.now(UTC)
                        + timedelta(seconds=settings.upload_ttl_seconds),
                    },
                )
                .mappings()
                .one()
            )
            receipt = upload_receipt(row)
        return receipt
    except Exception:
        for key in written:
            storage.delete(key)
        raise


@router.post("/uploads/{media_id}/complete", response_model=UploadReceipt)
def complete(media_id: UUID, request: Request, actor: CurrentActor) -> UploadReceipt:
    if not (actor.has_role(Role.CITIZEN) or actor.has_role(Role.OPERATOR)):
        raise HTTPException(403, "Citizen or operator permission required")
    with request.app.state.engine.begin() as connection:
        row = (
            connection.execute(
                text("SELECT * FROM media WHERE id=:id AND owner_id=:user FOR UPDATE"),
                {"id": media_id, "user": actor.id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise HTTPException(404, "Photo not found")
        if row["report_id"] is not None or row["repair_issue_id"] is not None:
            return upload_receipt(row)
        if row["expires_at"] <= datetime.now(UTC):
            raise HTTPException(410, "Upload expired; upload the photo again")
        original = verify_stored_media(request.app.state.media_storage, row)
        decode_photo(original, row["mime"], request.app.state.settings)
        updated = (
            connection.execute(
                text("""
            UPDATE media SET completed_at=COALESCE(completed_at,now()),processing_state='ready'
            WHERE id=:id RETURNING *
        """),
                {"id": media_id},
            )
            .mappings()
            .one()
        )
        return upload_receipt(updated)


@router.post("/reports", response_model=ReportDetail, status_code=201)
def submit(
    body: ReportSubmission,
    request: Request,
    actor: CurrentActor,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128, pattern=r"^[!-~]+$")],
) -> ReportDetail:
    citizen(actor)
    with request.app.state.engine.begin() as connection:
        return submit_report(
            connection,
            actor,
            body,
            idempotency_key,
            request.app.state.settings,
            request.app.state.media_storage,
        )


@router.get("/reports/mine", response_model=ReportPage)
def mine(
    request: Request,
    actor: CurrentActor,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ReportPage:
    with request.app.state.engine.connect() as connection:
        if cursor is not None:
            owned = connection.execute(
                text("SELECT id FROM reports WHERE id=:id AND reporter_id=:user"),
                {"id": cursor, "user": actor.id},
            ).scalar_one_or_none()
            if owned is None:
                raise HTTPException(404, "Cursor not found")
        rows = (
            connection.execute(
                text("""
            SELECT id FROM reports WHERE reporter_id=:user AND
              (CAST(:cursor AS uuid) IS NULL OR (received_at,id) <
                (SELECT received_at,id FROM reports WHERE id=:cursor))
            ORDER BY received_at DESC,id DESC LIMIT :limit
        """),
                {"user": actor.id, "cursor": cursor, "limit": limit + 1},
            )
            .scalars()
            .all()
        )
        return ReportPage(
            items=[report_detail(connection, item, actor) for item in rows[:limit]],
            next_cursor=rows[limit - 1] if len(rows) > limit else None,
        )


@router.get("/reports/{report_id}", response_model=ReportDetail)
def detail(report_id: UUID, request: Request, actor: CurrentActor) -> ReportDetail:
    with request.app.state.engine.connect() as connection:
        return report_detail(connection, report_id, actor)


@router.get("/media/{media_id}/content", response_class=Response)
def media_content(media_id: UUID, request: Request, actor: CurrentActor) -> Response:
    with request.app.state.engine.connect() as connection:
        row = (
            connection.execute(
                text("""
            SELECT m.owner_id,m.report_id,m.derivative_key,m.derivative_sha256,r.area_id
            FROM media m LEFT JOIN reports r ON r.id=m.report_id WHERE m.id=:id
        """),
                {"id": media_id},
            )
            .mappings()
            .one_or_none()
        )
        repair_allowed = False
        if row is not None:
            repair = (
                connection.execute(
                    text(
                        "SELECT i.* FROM issues i JOIN media m "
                        "ON m.repair_issue_id=i.id WHERE m.id=:id"
                    ),
                    {"id": media_id},
                )
                .mappings()
                .one_or_none()
            )
            if repair is not None:
                from app.routes.work import operator

                repair_allowed = actor.can_review(repair["area_id"]) or operator(actor, repair)
        if row is None or (
            row["owner_id"] != actor.id
            and not repair_allowed
            and (row["report_id"] is None or not actor.can_review(row["area_id"]))
        ):
            raise HTTPException(404, "Photo not found")
        try:
            content = request.app.state.media_storage.read(row["derivative_key"])
        except OSError as error:
            raise HTTPException(503, "Photo storage is temporarily unavailable") from error
        import hashlib

        if hashlib.sha256(content).hexdigest() != row["derivative_sha256"]:
            raise HTTPException(503, "Stored photo integrity check failed")
        return Response(
            content,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "inline; filename=photo.jpg",
            },
        )
