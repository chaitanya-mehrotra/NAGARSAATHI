from unittest.mock import Mock

import pytest
import worker.__main__ as worker_main
from sqlalchemy.exc import OperationalError, ProgrammingError


def dropped():
    return OperationalError("SELECT 1", {}, Exception("server closed the connection unexpectedly"))


def run(monkeypatch, schedule, process, iterations):
    """Run the loop for a fixed number of iterations; returns (engine mock, recorded sleeps)."""
    engine, sleeps, count = Mock(), [], {"n": 0}
    monkeypatch.setattr(worker_main, "schedule_age_refresh", schedule)
    monkeypatch.setattr(worker_main, "process_once", process)

    def stop():
        count["n"] += 1
        return count["n"] > iterations

    worker_main.run_loop(engine, Mock(), sleep=sleeps.append, should_stop=stop)
    return engine, sleeps


def test_dropped_connections_are_retried_with_backoff_and_then_recover(monkeypatch):
    outcomes = iter([dropped(), dropped(), dropped(), True, False])

    def process(engine, validator):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    engine, sleeps = run(monkeypatch, lambda e: None, process, iterations=5)
    # three failures back off 1s, 2s, 4s; a busy cycle does not sleep; an idle cycle waits 1s
    assert sleeps == [1.0, 2.0, 4.0, 1]
    assert engine.dispose.call_count == 3  # dead pooled connections are discarded each time


def test_backoff_is_capped_and_resets_after_success(monkeypatch):
    failures = [dropped()] * 8
    outcomes = iter(failures + [True, dropped(), False])

    def process(engine, validator):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    _, sleeps = run(monkeypatch, lambda e: None, process, iterations=11)
    assert sleeps[:8] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
    assert sleeps[8] == 1.0  # after a success the delay starts over


def test_failure_in_the_age_refresh_is_also_retried(monkeypatch):
    calls = {"n": 0}

    def schedule(engine):
        calls["n"] += 1
        if calls["n"] == 1:
            raise dropped()

    _, sleeps = run(monkeypatch, schedule, lambda e, v: True, iterations=2)
    assert sleeps == [1.0]
    assert calls["n"] == 2


def test_real_bugs_are_not_swallowed(monkeypatch):
    def process(engine, validator):
        raise ProgrammingError("SELECT nope", {}, Exception("column does not exist"))

    with pytest.raises(ProgrammingError):
        run(monkeypatch, lambda e: None, process, iterations=3)
