from app.adapters.interfaces import PhotoValidator
from app.adapters.validation import FixtureValidator, HumanReviewValidator
from app.database import create_database_engine
from app.domain.priority import schedule_age_refresh
from app.health import check_database
from app.jobs import process_once
from app.settings import Settings


def main() -> None:
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description="Revision-aware validation, admission and priority refresh worker"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if settings.app_mode == "production":
        raise SystemExit("Production worker rollout gates are not implemented")
    if not check_database(settings):
        raise SystemExit("PostGIS is not ready. Start docker compose up -d --wait first.")
    if args.check:
        print("Worker dependency check passed.")
        return
    engine = create_database_engine(settings)
    if settings.validation_provider == "fixture":
        validator: PhotoValidator = FixtureValidator(settings)
    elif settings.validation_provider == "yolo":
        from app.adapters.yolo import YoloValidator

        validator = YoloValidator(settings, engine)
        validator.load()  # fail fast on a missing or mismatched checkpoint
        print(f"YOLO validator ready: {validator.metadata['model_version']}", flush=True)
    else:
        validator = HumanReviewValidator()
    try:
        if args.once:
            print("Processed one job." if process_once(engine, validator) else "No ready jobs.")
        else:
            print("Validation, admission and priority worker running; Ctrl+C stops it.", flush=True)
            while True:
                schedule_age_refresh(engine)
                if not process_once(engine, validator):
                    time.sleep(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
