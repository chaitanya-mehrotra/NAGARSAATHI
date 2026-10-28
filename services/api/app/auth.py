from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
from typing import Any, Protocol

import jwt
from fastapi import HTTPException
from jwt import PyJWKClient
from sqlalchemy import Connection, text

from app.domain.enums import Role
from app.intake_schemas import Actor, RoleGrant
from app.settings import PROJECT_ROOT, Settings


def hash_password(password: str) -> str:
    """Hash password using salted scrypt with standard security parameters."""
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=16384, r=8, p=1).hex()
    return f"{salt}:{digest}"


def verify_password(password: str, stored: str | None) -> bool:
    """Verify password against stored salt:digest using constant-time comparison."""
    if not stored or ":" not in stored:
        return False
    try:
        salt, digest = stored.split(":", 1)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(actual, digest)
    except Exception:
        return False


def create_access_token(
    subject: str,
    secret: str,
    email: str | None = None,
    role: str = "citizen",
    expires_delta: timedelta = timedelta(hours=72),
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "iss": "nagarsaathi-v2",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


class TokenVerifier(Protocol):
    def subject(self, token: str) -> str: ...


class OIDCTokens:
    """Strict OIDC verifier: signature, issuer, audience, expiry and a non-empty string subject.

    Roles in the token are never trusted; authorization comes from the database. A JWKS outage
    is a 503, never an authenticated request.
    """

    def __init__(self, settings: Settings, jwks: Any | None = None) -> None:
        self.settings = settings
        self.jwks = jwks or PyJWKClient(settings.oidc_jwks_url, timeout=3, lifespan=300)

    def subject(self, token: str) -> str:
        try:
            if jwt.get_unverified_header(token).get("alg") not in {"RS256", "ES256"}:
                raise HTTPException(401, "Invalid or expired authorization token")
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                issuer=self.settings.oidc_issuer,
                audience=self.settings.oidc_audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except HTTPException:
            raise
        except jwt.PyJWKClientConnectionError as err:
            raise HTTPException(503, "Identity provider is unavailable") from err
        except jwt.PyJWTError as err:
            raise HTTPException(401, "Invalid or expired authorization token") from err
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise HTTPException(401, "Invalid or expired authorization token")
        return sub


class MultiTokenVerifier:
    """Unified token verifier supporting local HS256 JWTs, OIDC, and demo fixtures."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.jwt_secret = settings.jwt_secret
        self.demo_subjects: set[str] = set()
        self.oidc = OIDCTokens(settings) if settings.oidc_jwks_url else None

        if settings.app_mode in {"demo", "test"}:
            try:
                import json

                fixture_path = PROJECT_ROOT / "fixtures/identities.json"
                if fixture_path.exists():
                    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                    self.demo_subjects = {ident["subject"] for ident in fixture.get("identities", [])}
            except Exception:
                pass

    def subject(self, token: str) -> str:
        # 1. Check demo token subject
        if self.demo_subjects and token in self.demo_subjects:
            return token

        # 2. Asymmetric tokens belong to the configured OIDC provider only
        try:
            algorithm = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError as err:
            raise HTTPException(401, "Invalid or expired authorization token") from err
        if algorithm in {"RS256", "ES256"} and self.oidc is not None:
            return self.oidc.subject(token)

        # 3. Local HS256 session token issued by this API
        try:
            claims = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=["HS256"],
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as err:
            raise HTTPException(401, "Invalid or expired authorization token") from err
        sub = claims.get("sub")
        if isinstance(sub, str) and sub:
            return sub
        raise HTTPException(401, "Invalid or expired authorization token")


class DemoTokens:
    def __init__(self, settings: Settings) -> None:
        import json

        if settings.app_mode not in {"demo", "test"}:
            raise ValueError("Demo identities are forbidden outside demo/test mode")
        fixture = json.loads((PROJECT_ROOT / "fixtures/identities.json").read_text(encoding="utf-8"))
        self.subjects = {identity["subject"] for identity in fixture["identities"]}

    def subject(self, token: str) -> str:
        if token not in self.subjects:
            raise HTTPException(401, "Invalid demo identity")
        return token


def load_actor(connection: Connection, subject: str, synthetic: bool) -> Actor:
    user = (
        connection.execute(
            text("""
                SELECT id, display_name, COALESCE(role, 'citizen') as user_role, email
                FROM users
                WHERE (auth_subject=:subject OR id::text=:subject OR email=:subject) AND active
            """),
            {"subject": subject},
        )
        .mappings()
        .one_or_none()
    )
    if user is None:
        raise HTTPException(401, "Identity is not provisioned or has been disabled")

    grants_rows = (
        connection.execute(
            text("""
                SELECT r.role, r.area_id, a.code AS area_code FROM user_roles r
                LEFT JOIN areas a ON a.id=r.area_id WHERE r.user_id=:user
                ORDER BY r.role, a.code
            """),
            {"user": user["id"]},
        )
        .mappings()
        .all()
    )

    grants = [RoleGrant.model_validate(dict(grant)) for grant in grants_rows]

    # If user_roles table has no explicit entry, populate from users.role column
    user_role_str = user["user_role"]
    if not grants:
        mapped_role = Role.CITIZEN
        if user_role_str in {Role.ADMIN, Role.REVIEWER, Role.OPERATOR, Role.NIGAM}:
            mapped_role = Role(user_role_str)
        grants.append(RoleGrant(role=mapped_role, area_id=None, area_code=None))

    return Actor(
        id=user["id"],
        subject=subject,
        display_name=user["display_name"],
        synthetic=synthetic,
        grants=grants,
    )
