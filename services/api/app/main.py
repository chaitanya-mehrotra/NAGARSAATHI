from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import yaml
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from starlette.exceptions import HTTPException
from starlette.responses import Response

from app.adapters.local_media import LocalMedia
from app.auth import MultiTokenVerifier, TokenVerifier
from app.database import create_database_engine
from app.health import check_database, check_storage
from app.routes.auth_routes import compat_router as auth_compat_router, router as auth_router
from app.routes.complaints_routes import compat_router as complaints_compat_router, router as complaints_router
from app.routes.intake import router
from app.routes.issues import router as issues_router
from app.routes.priority import router as priority_router
from app.routes.reviews import router as reviews_router
from app.routes.staff_queue import router as staff_queue_router
from app.routes.work import router as work_router
from app.schemas import ErrorResponse, HealthResponse, PublicConfig
from app.settings import Settings


def create_app(
    settings: Settings | None = None,
    database_probe: Callable[[Settings], bool] = check_database,
    engine: Engine | None = None,
    token_verifier: TokenVerifier | None = None,
) -> FastAPI:
    current = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.public_config = PublicConfig.model_validate(
            yaml.safe_load(current.config_file.read_text(encoding="utf-8"))
        ).model_copy(update={"auth_provider": current.auth_provider})
        try:
            yield
        finally:
            if engine is None:
                application.state.engine.dispose()

    application = FastAPI(title="NAGARSAATHI API", version="0.2.0", lifespan=lifespan)
    application.state.settings = current
    application.state.engine = engine or create_database_engine(current)
    application.state.tokens = token_verifier or MultiTokenVerifier(current)
    application.state.media_storage = LocalMedia(current.storage_root)
    application.include_router(auth_router)
    application.include_router(auth_compat_router)
    application.include_router(complaints_router)
    application.include_router(complaints_compat_router)
    application.include_router(router)
    application.include_router(reviews_router)
    application.include_router(issues_router)
    application.include_router(priority_router)
    application.include_router(staff_queue_router)
    application.include_router(work_router)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=current.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @application.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.headers.get("authorization"):
            response.headers["Cache-Control"] = "private, no-store"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
            for item in error.errors()
        ]
        body = ErrorResponse(
            code="validation_error",
            message="Check the submitted fields",
            field_errors=fields,
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=422, content=body.model_dump())

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        body = ErrorResponse(
            code="not_found" if error.status_code == 404 else "http_error",
            message=str(error.detail),
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=error.status_code, content=body.model_dump())

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        body = ErrorResponse(
            code="internal_error",
            message="An unexpected error occurred",
            request_id=request.state.request_id,
        )
        return JSONResponse(
            status_code=500,
            content=body.model_dump(),
            headers={"X-Request-ID": body.request_id},
        )

    @application.get("/api/v1/health/live", response_model=HealthResponse)
    def live() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.get(
        "/api/v1/health/ready",
        response_model=HealthResponse,
        responses={503: {"model": HealthResponse}},
    )
    def ready(response: Response) -> HealthResponse:
        checks = {
            "postgis": database_probe(current),
            "storage": check_storage(current.storage_root),
        }
        is_ready = all(checks.values())
        response.status_code = 200 if is_ready else 503
        return HealthResponse(status="ready" if is_ready else "not_ready", checks=checks)

    @application.get("/api/v1/config/public", response_model=PublicConfig)
    def public_config(request: Request) -> PublicConfig:
        return PublicConfig.model_validate(request.app.state.public_config)

    @application.get("/api/v1/config/boundaries")
    def boundaries() -> dict[str, object]:
        import json

        return dict(json.loads((current.config_file.parent / "areas.geojson").read_text()))

    return application


app = create_app()
