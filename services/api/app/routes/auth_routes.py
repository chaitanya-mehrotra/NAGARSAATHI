"""Authentication routes for NAGARSAATHI V2 — Exclusively Google Sign-In & Session Management."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text

from app.auth import create_access_token, load_actor
from app.domain.enums import Role
from app.intake_schemas import Actor
from app.schemas import Contract

router = APIRouter(prefix="/api/v1", tags=["Authentication & Google Accounts"])
compat_router = APIRouter(tags=["Frontend Compatibility"])
bearer = HTTPBearer(auto_error=False)


def authenticated(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Actor:
    if credentials is None or len(credentials.credentials) > 8192:
        raise HTTPException(401, "A bearer identity token is required")
    subject = request.app.state.tokens.subject(credentials.credentials)
    with request.app.state.engine.connect() as connection:
        return load_actor(connection, subject, request.app.state.settings.app_mode in {"demo", "test"})


CurrentActor = Annotated[Actor, Depends(authenticated)]


class GoogleAuthRequest(BaseModel):
    credential: str | None = Field(default=None, max_length=8192)  # Google ID token


class UserProfile(Contract):
    id: UUID
    name: str
    email: str
    role: str
    created_at: datetime


class AuthResponse(Contract):
    access_token: str
    token_type: str = "Bearer"
    user: UserProfile


def normalize_email(email: str) -> str:
    return email.strip().lower()


def demo_enabled(request: Request) -> bool:
    return request.app.state.settings.app_mode in {"demo", "test"}


def verify_google_credential(credential: str, audience: str) -> dict[str, str]:
    """Verify signature, audience, issuer and expiry of a Google ID token."""
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as err:
        raise HTTPException(503, "Install google-auth to enable Google sign-in") from err
    try:
        claims = id_token.verify_oauth2_token(credential, google_requests.Request(), audience)
    except ValueError as err:
        raise HTTPException(401, "Google sign-in could not be verified") from err
    except Exception as err:
        raise HTTPException(503, "Google sign-in is temporarily unavailable") from err
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise HTTPException(401, "Google token issuer is not trusted")
    if claims.get("email_verified") is not True or not isinstance(claims.get("email"), str):
        raise HTTPException(401, "A verified Google email address is required")
    email = normalize_email(claims["email"])
    name = str(claims.get("name") or email.split("@")[0]).strip()[:100] or "Citizen"
    return {"email": email, "name": name, "sub": f"google:{claims['sub']}"}


@router.get("/auth/options")
@compat_router.get("/auth/options")
def auth_options(request: Request) -> dict[str, Any]:
    return {
        "google_client_id": request.app.state.settings.google_client_id or None,
        "demo_enabled": demo_enabled(request),
    }


@router.post("/auth/google", response_model=AuthResponse)
@compat_router.post("/auth/google", response_model=AuthResponse)
def google_sign_in(body: GoogleAuthRequest, request: Request) -> AuthResponse:
    """Citizen sign-in. Only a Google-signed ID token is accepted; never a bare email."""
    audience = request.app.state.settings.google_client_id
    if not audience:
        raise HTTPException(503, "Google sign-in is not configured (set GOOGLE_CLIENT_ID)")
    if not body.credential:
        raise HTTPException(400, "A Google credential is required")
    google_data = verify_google_credential(body.credential, audience)
    email = google_data["email"]
    name = google_data["name"]
    auth_sub = google_data["sub"]

    with request.app.state.engine.begin() as connection:
        user = connection.execute(
            text("""
                SELECT id, auth_subject, display_name, email, COALESCE(role, 'citizen') as user_role, created_at, active
                FROM users WHERE auth_subject=:sub OR email=:email
            """),
            {"sub": auth_sub, "email": email},
        ).mappings().first()

        if user:
            if not user["active"]:
                raise HTTPException(403, "Account has been deactivated. Contact administration.")
            if user["user_role"] != "citizen":
                raise HTTPException(403, "Staff accounts cannot sign in with Google")
            user_id = user["id"]
            user_role = user["user_role"]
            created_at = user["created_at"]
            name = user["display_name"]
            connection.execute(
                text("UPDATE users SET auth_subject=:sub, email_verified=true WHERE id=:id"),
                {"sub": auth_sub, "id": user_id},
            )
        else:
            user_id = uuid4()
            user_role = "citizen"
            created_at = datetime.now(UTC)
            connection.execute(
                text("""
                    INSERT INTO users (id, auth_subject, display_name, email, role, email_verified, active)
                    VALUES (:id, :sub, :name, :email, 'citizen', true, true)
                """),
                {"id": user_id, "sub": auth_sub, "name": name, "email": email},
            )
            connection.execute(
                text("INSERT INTO user_roles (user_id, role) VALUES (:user_id, 'citizen')"),
                {"user_id": user_id},
            )

    token = create_access_token(
        subject=auth_sub,
        secret=request.app.state.settings.jwt_secret,
        email=email,
        role=user_role,
        expires_delta=timedelta(hours=request.app.state.settings.session_expire_hours),
    )
    user_profile = UserProfile(
        id=user_id, name=name, email=email, role=user_role, created_at=created_at
    )
    return AuthResponse(access_token=token, user=user_profile)


class DemoLoginRequest(BaseModel):
    account_type: str = Field(default="admin", description="'admin' for platform administrator, 'citizen' for citizen")


class StandardLoginRequest(BaseModel):
    email: EmailStr
    password: str | None = None


@router.post("/auth/demo-login", response_model=AuthResponse)
@compat_router.post("/auth/demo-login", response_model=AuthResponse)
def demo_login(body: DemoLoginRequest, request: Request) -> AuthResponse:
    """One-click demo authentication; exists only when APP_MODE is demo/test."""
    if not demo_enabled(request):
        raise HTTPException(404, "Not found")
    is_admin = body.account_type.lower() in {"admin", "nigam", "reviewer"}
    email = "admin@nagarsaathi.gov.in" if is_admin else "citizen@gmail.com"
    name = "Nagar Saathi Administrator" if is_admin else "Citizen Saathi"
    role = "admin" if is_admin else "citizen"
    auth_sub = f"demo:{role}"

    with request.app.state.engine.begin() as connection:
        user = connection.execute(
            text("SELECT id, auth_subject, display_name, email, COALESCE(role, 'citizen') as user_role, created_at, active FROM users WHERE email=:email"),
            {"email": email},
        ).mappings().one_or_none()

        if user:
            user_id = user["id"]
            user_role = role
            created_at = user["created_at"]
            connection.execute(
                text("UPDATE users SET auth_subject=:sub, role=:role, active=true WHERE id=:id"),
                {"sub": auth_sub, "role": role, "id": user_id},
            )
            # Ensure appropriate role grant in user_roles
            connection.execute(
                text("DELETE FROM user_roles WHERE user_id=:id"),
                {"id": user_id},
            )
            connection.execute(
                text("INSERT INTO user_roles (user_id, role) VALUES (:id, :role)"),
                {"id": user_id, "role": role},
            )
        else:
            user_id = uuid4()
            user_role = role
            created_at = datetime.now(UTC)
            connection.execute(
                text("""
                    INSERT INTO users (id, auth_subject, display_name, email, role, email_verified, active)
                    VALUES (:id, :sub, :name, :email, :role, true, true)
                """),
                {"id": user_id, "sub": auth_sub, "name": name, "email": email, "role": role},
            )
            connection.execute(
                text("INSERT INTO user_roles (user_id, role) VALUES (:id, :role)"),
                {"id": user_id, "role": role},
            )

    token = create_access_token(
        subject=auth_sub,
        secret=request.app.state.settings.jwt_secret,
        email=email,
        role=user_role,
    )
    user_profile = UserProfile(
        id=user_id,
        name=name,
        email=email,
        role=user_role,
        created_at=created_at,
    )
    return AuthResponse(access_token=token, user=user_profile)


@router.post("/auth/login", response_model=AuthResponse)
@compat_router.post("/auth/login", response_model=AuthResponse)
def standard_login(body: StandardLoginRequest, request: Request) -> AuthResponse:
    """Password sign-in is not implemented; only the two fixed demo accounts, demo mode only."""
    if not demo_enabled(request):
        raise HTTPException(401, "Password sign-in is not enabled. Use Google sign-in.")
    email = normalize_email(body.email)
    if email == "admin@nagarsaathi.gov.in":
        return demo_login(DemoLoginRequest(account_type="admin"), request)
    if email == "citizen@gmail.com":
        return demo_login(DemoLoginRequest(account_type="citizen"), request)
    raise HTTPException(401, "Unknown demo account")


@router.get("/auth/me", response_model=UserProfile)
@compat_router.get("/auth/me", response_model=UserProfile)
def auth_me(actor: CurrentActor, request: Request) -> UserProfile:
    with request.app.state.engine.connect() as connection:
        user = connection.execute(
            text("SELECT id, display_name, email, COALESCE(role, 'citizen') as user_role, created_at FROM users WHERE id=:id"),
            {"id": actor.id},
        ).mappings().one()

    return UserProfile(
        id=user["id"],
        name=user["display_name"],
        email=user["email"] or f"{user['id']}@citizen.local",
        role=user["user_role"],
        created_at=user["created_at"],
    )


@router.post("/auth/logout")
@compat_router.post("/auth/logout")
def logout() -> dict[str, str]:
    return {"status": "ok", "message": "Signed out"}


@compat_router.get("/metrics")
@router.get("/metrics")
def get_metrics(request: Request) -> dict[str, Any]:
    """Returns aggregated platform metrics for overview counters."""
    with request.app.state.engine.connect() as connection:
        counts = connection.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE deleted_at IS NULL) as total_reports,
                COUNT(*) FILTER (WHERE deleted_at IS NULL AND state='admitted') as admitted_reports,
                COUNT(*) FILTER (WHERE deleted_at IS NULL AND state='rejected') as rejected_reports,
                COUNT(*) FILTER (WHERE deleted_at IS NULL AND state='awaiting_review') as pending_reports,
                COUNT(*) FILTER (WHERE deleted_at IS NULL AND is_suspicious = true) as suspicious_reports
            FROM reports
        """)).mappings().one()

        issue_counts = connection.execute(text("""
            SELECT
                COUNT(*) as total_issues,
                COUNT(*) FILTER (WHERE status='resolved') as resolved_issues,
                COUNT(*) FILTER (WHERE status IN ('open', 'assigned', 'in_progress', 'resolution_pending')) as active_issues
            FROM issues
        """)).mappings().one()

        category_counts = connection.execute(text("""
            SELECT claimed_category, COUNT(*) as count
            FROM reports WHERE deleted_at IS NULL
            GROUP BY claimed_category
        """)).mappings().all()

    return {
        "reports": {
            "total": counts["total_reports"],
            "admitted": counts["admitted_reports"],
            "rejected": counts["rejected_reports"],
            "pending": counts["pending_reports"],
            "suspicious": counts["suspicious_reports"],
        },
        "issues": {
            "total": issue_counts["total_issues"],
            "resolved": issue_counts["resolved_issues"],
            "active": issue_counts["active_issues"],
        },
        "categories": {row["claimed_category"]: row["count"] for row in category_counts},
    }
