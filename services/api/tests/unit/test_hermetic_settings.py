from app.settings import Settings


def test_tests_ignore_hosted_services_from_dotenv():
    settings = Settings()  # reads .env, then the environment pinned by tests/conftest.py
    assert settings.storage_backend == "local"
    assert settings.allow_hosted_demo_seed is False
    assert settings.supabase_url == ""
