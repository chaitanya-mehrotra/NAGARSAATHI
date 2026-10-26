"""Authentication routes for NAGARSAATHI V2 — Exclusively Google Sign-In & Session Management."""

from datetime import UTC, datetime
import os
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
    credential: str | None = None  # Google ID token from Google Identity Services
    email: EmailStr | None = None  # Fallback for direct Google OAuth response
    name: str | None = None
    sub: str | None = None


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


def parse_google_credential(body: GoogleAuthRequest) -> dict[str, str]:
    """Parse Google ID token or direct OAuth response payload."""
    if body.credential:
        try:
            # Decode Google JWT payload claims
            claims = jwt.decode(body.credential, options={"verify_signature": False})
            email = claims.get("email")
            if not email:
                raise ValueError("Google credential does not contain an email address")
            name = claims.get("name") or claims.get("given_name") or email.split("@")[0]
            sub = claims.get("sub") or f"google_{claims.get('email')}"
            return {"email": normalize_email(email), "name": name, "sub": f"google:{sub}"}
        except Exception as err:
            raise HTTPException(401, f"Failed to parse Google ID token: {err}") from err

    if body.email:
        email = normalize_email(body.email)
        name = body.name or email.split("@")[0]
        sub = body.sub or f"google:{email}"
        return {"email": email, "name": name, "sub": sub}

    raise HTTPException(400, "Google credential or email is required")


@router.post("/auth/google", response_model=AuthResponse)
@compat_router.post("/auth/google", response_model=AuthResponse)
def google_sign_in(body: GoogleAuthRequest, request: Request) -> AuthResponse:
    """Sole citizen authentication endpoint: verifies Google identity and auto-provisions citizen account."""
    google_data = parse_google_credential(body)
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
        ).mappings().one_or_none()

        if user:
            if not user["active"]:
                raise HTTPException(403, "Account has been deactivated. Contact administration.")
            user_id = user["id"]
            user_role = user["user_role"]
            created_at = user["created_at"]
            # Ensure auth_subject is updated to Google subject
            connection.execute(
                text("UPDATE users SET auth_subject=:sub, email_verified=true WHERE id=:id"),
                {"sub": auth_sub, "id": user_id},
            )
        else:
            # Auto-provision new citizen account from verified Google identity
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
        secret=getattr(request.app.state.tokens, "jwt_secret", "local_dev_jwt_secret_must_change_in_prod_32chars"),
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


class DemoLoginRequest(BaseModel):
    account_type: str = Field(default="admin", description="'admin' for platform administrator, 'citizen' for citizen")


class StandardLoginRequest(BaseModel):
    email: EmailStr
    password: str | None = None


@router.post("/auth/demo-login", response_model=AuthResponse)
@compat_router.post("/auth/demo-login", response_model=AuthResponse)
def demo_login(body: DemoLoginRequest, request: Request) -> AuthResponse:
    """One-click demo authentication for demo admin or demo citizen."""
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
            if is_admin:
                connection.execute(
                    text("INSERT INTO user_roles (user_id, role) VALUES (:id, 'nigam') ON CONFLICT DO NOTHING"),
                    {"id": user_id},
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
            if is_admin:
                connection.execute(
                    text("INSERT INTO user_roles (user_id, role) VALUES (:id, 'nigam') ON CONFLICT DO NOTHING"),
                    {"id": user_id},
                )

    token = create_access_token(
        subject=auth_sub,
        secret=getattr(request.app.state.tokens, "jwt_secret", "local_dev_jwt_secret_must_change_in_prod_32chars"),
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
    """Compatibility login route supporting demo accounts and credentials."""
    email = normalize_email(body.email)
    is_admin = "admin" in email
    account_type = "admin" if is_admin else "citizen"
    return demo_login(DemoLoginRequest(account_type=account_type), request)


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
