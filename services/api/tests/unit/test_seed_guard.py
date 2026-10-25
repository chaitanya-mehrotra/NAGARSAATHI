import pytest
from app.demo_seed import require_local_demo
from app.settings import Settings


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:public-demo@localhost/production",
        "postgresql://user:public-demo@remote.example.invalid/nagarsaathi_demo",
    ],
)
def test_demo_seed_refuses_arbitrary_database_targets(url: str) -> None:
    with pytest.raises(ValueError, match="Demo"):
        require_local_demo(Settings(_env_file=None, app_mode="demo", database_url=url))
