from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    app_mode: Literal["demo", "test", "production"] = "demo"
    auth_provider: Literal["demo", "oidc"] = "demo"
    validation_provider: Literal["fixture", "human_review"] = "fixture"
    database_url: str = (
        "postgresql://nagarsaathi_demo:local_demo_only@127.0.0.1:55432/nagarsaathi_demo"
    )
    storage_root: Path = Path(".local/media")
    config_file: Path = PROJECT_ROOT / "config/demo.yaml"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    boundaries_reviewed: bool = False
    category_rules_reviewed: bool = False
    upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=10 * 1024 * 1024)
    report_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1, le=25 * 1024 * 1024)
    image_max_pixels: int = Field(default=25_000_000, ge=1, le=25_000_000)
    upload_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    pilot_code: str = "bengaluru_southeast_v1"

    @model_validator(mode="after")
    def reject_unsafe_production(self) -> Self:
        if self.app_mode == "production" and (
            self.auth_provider == "demo" or self.validation_provider == "fixture"
        ):
            raise ValueError("Production forbids demo auth and fixture validation")
        if self.auth_provider == "oidc":
            if not (self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url):
                raise ValueError("OIDC requires issuer, audience and JWKS URL")
            if not (
                self.oidc_issuer.startswith("https://")
                and self.oidc_jwks_url.startswith("https://")
            ):
                raise ValueError("OIDC issuer and JWKS URL must use HTTPS")
        if self.app_mode == "production":
            if not (self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url):
                raise ValueError("Production requires OIDC issuer, audience and JWKS URL")
            if not (self.boundaries_reviewed and self.category_rules_reviewed):
                raise ValueError("Production requires reviewed boundaries and category rules")
        if not self.storage_root.is_absolute():
            self.storage_root = PROJECT_ROOT / self.storage_root
        return self
