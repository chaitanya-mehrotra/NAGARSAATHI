from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_JWT_SECRET = "local_dev_jwt_secret_must_change_in_prod_32chars"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    app_mode: Literal["demo", "test", "production"] = "demo"
    auth_provider: Literal["demo", "oidc"] = "demo"
    validation_provider: Literal["fixture", "human_review", "yolo"] = "fixture"
    database_url: str = (
        "postgresql://nagarsaathi_demo:local_demo_only@127.0.0.1:55432/nagarsaathi_demo"
    )
    storage_root: Path = Path(".local/media")
    # "local" keeps photos on disk; "supabase" stores them in a private Supabase Storage bucket.
    storage_backend: Literal["local", "supabase"] = "local"
    supabase_url: str = ""
    supabase_service_role_key: SecretStr = SecretStr("")
    supabase_storage_bucket: str = "complaint-photos"
    db_pool_size: int = Field(default=5, ge=1, le=30)
    db_max_overflow: int = Field(default=5, ge=0, le=30)
    # Demo seeding normally refuses any database not named *_demo/_test on a local host. A hosted
    # demo database (for example Supabase, always named "postgres") must opt in explicitly.
    allow_hosted_demo_seed: bool = False
    config_file: Path = PROJECT_ROOT / "config/demo.yaml"
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    jwt_secret: str = DEFAULT_JWT_SECRET
    google_client_id: str = ""
    session_expire_hours: int = Field(default=72, ge=1, le=720)
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    boundaries_reviewed: bool = False
    category_rules_reviewed: bool = False
    yolo_model_path: Path = Path("models/nagarsaathi-combined-v3.pt")
    yolo_metadata_path: Path = Path("models/nagarsaathi-combined-v3.metadata.json")
    yolo_device: str = "cpu"
    upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=10 * 1024 * 1024)
    report_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1, le=25 * 1024 * 1024)
    image_max_pixels: int = Field(default=25_000_000, ge=1, le=25_000_000)
    upload_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    pilot_code: str = "bengaluru_southeast_v1"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        # Accept "a,b" from .env / compose as well as a JSON list.
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

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
        if self.app_mode == "production" and self.jwt_secret == DEFAULT_JWT_SECRET:
            raise ValueError("Production requires a non-default JWT_SECRET")
        if self.app_mode == "production":
            if not (self.oidc_issuer and self.oidc_audience and self.oidc_jwks_url):
                raise ValueError("Production requires OIDC issuer, audience and JWKS URL")
            if not (self.boundaries_reviewed and self.category_rules_reviewed):
                raise ValueError("Production requires reviewed boundaries and category rules")
        if self.storage_backend == "supabase":
            if not self.supabase_url.startswith("https://"):
                raise ValueError("Supabase storage needs SUPABASE_URL (https://<ref>.supabase.co)")
            if not self.supabase_service_role_key.get_secret_value():
                raise ValueError("Supabase storage needs SUPABASE_SERVICE_ROLE_KEY")
        if not self.storage_root.is_absolute():
            self.storage_root = PROJECT_ROOT / self.storage_root
        return self
