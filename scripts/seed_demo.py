from app.database import create_database_engine
from app.demo_seed import seed_foundation
from app.settings import Settings


def main() -> None:
    settings = Settings()
    engine = create_database_engine(settings)
    with engine.begin() as connection:
        pilot_id = seed_foundation(connection, settings)
    engine.dispose()
    print(f"Seeded synthetic pilot {pilot_id}, areas, categories and fictional POIs.")


if __name__ == "__main__":
    main()
