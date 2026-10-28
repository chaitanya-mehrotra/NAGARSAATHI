import httpx
import pytest
from app.adapters.storage import build_media_storage
from app.adapters.supabase_media import SupabaseMedia
from app.adapters.local_media import LocalMedia
from app.database import create_database_engine, effective_url
from app.demo_seed import require_local_demo
from app.settings import Settings
from pydantic import ValidationError

KEY = "ab" * 16 + "/original"
HOSTED = "postgresql+psycopg://postgres.abc:pw@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"


def settings(**changes) -> Settings:
    base = {
        "_env_file": None,
        "app_mode": "demo",
        "storage_backend": "supabase",
        "supabase_url": "https://abc.supabase.co",
        "supabase_service_role_key": "sb_secret_opaque",
    }
    return Settings(**{**base, **changes})


def store(handler, **changes) -> tuple[SupabaseMedia, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.Client(
        base_url="https://abc.supabase.co/storage/v1", transport=httpx.MockTransport(record)
    )
    return SupabaseMedia(settings(**changes), client), seen


def test_put_read_delete_use_the_private_bucket_paths():
    media, seen = store(lambda r: httpx.Response(200, content=b"photo"))
    media.put(KEY, b"photo")
    assert media.read(KEY) == b"photo"
    media.delete(KEY)
    assert [(r.method, r.url.path) for r in seen] == [
        ("POST", f"/storage/v1/object/complaint-photos/{KEY}"),
        ("GET", f"/storage/v1/object/authenticated/complaint-photos/{KEY}"),
        ("DELETE", f"/storage/v1/object/complaint-photos/{KEY}"),
    ]
    assert seen[0].headers["x-upsert"] == "false"


def test_missing_object_and_duplicate_map_to_file_errors():
    media, _ = store(lambda r: httpx.Response(404, json={"error": "not_found"}))
    with pytest.raises(FileNotFoundError):
        media.read(KEY)
    media.delete(KEY)  # deleting something already gone is fine
    legacy, _ = store(lambda r: httpx.Response(400, json={"error": "not_found"}))
    with pytest.raises(FileNotFoundError):
        legacy.read(KEY)
    dup, _ = store(lambda r: httpx.Response(400, json={"statusCode": "409", "error": "Duplicate"}))
    with pytest.raises(FileExistsError):
        dup.put(KEY, b"x")


def test_failures_are_oserrors_so_the_api_answers_503():
    broken, _ = store(lambda r: httpx.Response(500))
    for call in (lambda: broken.put(KEY, b"x"), lambda: broken.read(KEY), lambda: broken.delete(KEY)):
        with pytest.raises(OSError):
            call()

    def offline(request):
        raise httpx.ConnectError("down")

    down, _ = store(offline)
    with pytest.raises(OSError):
        down.read(KEY)
    assert down.ping() is False


def test_only_server_generated_keys_are_accepted():
    media, _ = store(lambda r: httpx.Response(200))
    for bad in ["../secrets", "abc/original", ("ab" * 16) + "/other.png", "/" + KEY]:
        with pytest.raises(ValueError):
            media.read(bad)


def test_credentials_header_depends_on_key_style():
    opaque = SupabaseMedia(settings())
    assert opaque.client.headers["apikey"] == "sb_secret_opaque"
    assert "authorization" not in opaque.client.headers
    jwt_like = SupabaseMedia(settings(supabase_service_role_key="aaa.bbb.ccc"))
    assert jwt_like.client.headers["authorization"] == "Bearer aaa.bbb.ccc"


def test_ping_reflects_bucket_reachability():
    ok, _ = store(lambda r: httpx.Response(200, json={"id": "complaint-photos"}))
    assert ok.ping() is True
    gone, _ = store(lambda r: httpx.Response(404))
    assert gone.ping() is False


def test_supabase_backend_needs_url_and_key(tmp_path):
    with pytest.raises(ValidationError, match="SUPABASE_URL"):
        settings(supabase_url="")
    with pytest.raises(ValidationError, match="SERVICE_ROLE_KEY"):
        settings(supabase_service_role_key="")
    assert isinstance(build_media_storage(settings()), SupabaseMedia)
    local = Settings(_env_file=None, app_mode="demo", storage_root=tmp_path)
    assert isinstance(build_media_storage(local), LocalMedia)
    assert "sb_secret_opaque" not in repr(settings())  # the key never shows up in logs


def test_hosted_databases_require_tls_but_local_ones_do_not():
    hosted = effective_url(settings(database_url=HOSTED))
    assert hosted.query["sslmode"] == "require"
    explicit = effective_url(settings(database_url=HOSTED + "?sslmode=verify-full"))
    assert explicit.query["sslmode"] == "verify-full"
    local = effective_url(settings(database_url="postgresql://u:p@127.0.0.1:5432/x_demo"))
    assert "sslmode" not in local.query
    engine = create_database_engine(settings(database_url=HOSTED))
    assert engine.url.query["sslmode"] == "require"
    engine.dispose()


def test_hosted_demo_seed_needs_an_explicit_opt_in():
    with pytest.raises(ValueError, match="Demo"):
        require_local_demo(settings(database_url=HOSTED))
    require_local_demo(settings(database_url=HOSTED, allow_hosted_demo_seed=True))
