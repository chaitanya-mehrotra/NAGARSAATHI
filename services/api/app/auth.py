from typing import Protocol

import jwt
from fastapi import HTTPException
from jwt import PyJWKClient
from sqlalchemy import Connection, text

from app.intake_schemas import Actor, RoleGrant
from app.settings import PROJECT_ROOT, Settings


class TokenVerifier(Protocol):
    def subject(self, token: str) -> str: ...


class DemoTokens:
    def __init__(self, settings: Settings) -> None:
        import json

        if settings.app_mode not in {"demo", "test"}:
            raise ValueError("Demo identities are forbidden outside demo/test mode")
        fixture = json.loads((PROJECT_ROOT / "fixtures/identities.json").read_text())
        self.subjects = {identity["subject"] for identity in fixture["identities"]}

    def subject(self, token: str) -> str:
        if token not in self.subjects:
            raise HTTPException(401, "Invalid demo identity")
        return token


class OIDCTokens:
    def __init__(self, settings: Settings, jwks: PyJWKClient | None = None) -> None:
        self.settings = settings
        self.jwks = jwks or PyJWKClient(settings.oidc_jwks_url, timeout=3, lifespan=300)

    def subject(self, token: str) -> str:
        try:
            header = jwt.get_unverified_header(token)
            # Algorithms are an application allowlist, never selected from token claims.
            if header.get("alg") not in {"RS256", "ES256"}:
                raise jwt.InvalidAlgorithmError()
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                issuer=self.settings.oidc_issuer,
                audience=self.settings.oidc_audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            subject = claims["sub"]
            if not isinstance(subject, str) or not subject:
                raise jwt.InvalidTokenError("Missing subject")
            return subject
        except jwt.PyJWKClientConnectionError as error:
            raise HTTPException(503, "Identity verification temporarily unavailable") from error
        except jwt.PyJWTError as error:
            raise HTTPException(401, "Invalid or expired identity token") from error


def load_actor(connection: Connection, subject: str, synthetic: bool) -> Actor:
    user = (
        connection.execute(
            text("SELECT id,display_name FROM users WHERE auth_subject=:subject AND active"),
            {"subject": subject},
        )
        .mappings()
        .one_or_none()
    )
    if user is None:
        raise HTTPException(401, "Identity is not provisioned or has been disabled")
    grants = (
        connection.execute(
            text("""
        SELECT r.role,r.area_id,a.code AS area_code FROM user_roles r
        LEFT JOIN areas a ON a.id=r.area_id WHERE r.user_id=:user
        ORDER BY r.role,a.code
    """),
            {"user": user["id"]},
        )
        .mappings()
        .all()
    )
    return Actor(
        id=user["id"],
        subject=subject,
        display_name=user["display_name"],
        synthetic=synthetic,
        grants=[RoleGrant.model_validate(dict(grant)) for grant in grants],
    )
