from app.adapters.interfaces import PhotoValidator
from app.adapters.validation import FixtureValidator, HumanReviewValidator
from app.database import create_database_engine
from app.domain.priority import schedule_age_refresh
from app.health import check_database
from app.jobs import process_once
from app.settings import Settings
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError


TRANSIENT_DATABASE_ERRORS = (OperationalError, InterfaceError, PoolTimeoutError)


def run_loop(engine, validator, *, sleep=None, max_backoff=30.0, should_stop=lambda: False):
    """Process jobs until stopped. A dropped or unreachable database is retried with backoff.

    Hosted databases drop connections now and then (idle timeouts, pooler restarts, network
    changes). The worker must survive that: an interrupted job's lease expires and is reclaimed.
    Only connection-level errors are retried; anything else still stops the worker loudly.
    """
    import time

    sleep = sleep or time.sleep
    delay = 1.0
    while not should_stop():
        try:
            schedule_age_refresh(engine)
            busy = process_once(engine, validator)
        except TRANSIENT_DATABASE_ERRORS as error:
            print(
                f"Database unavailable ({error.__class__.__name__}); retrying in {delay:.0f}s",
                flush=True,
            )
            engine.dispose()  # drop connections the server has already closed
            sleep(delay)
            delay = min(delay * 2, max_backoff)
            continue
        delay = 1.0
        if not busy:
            sleep(1)


def main() -> None:
    import argparse

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
            run_loop(engine, validator)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
