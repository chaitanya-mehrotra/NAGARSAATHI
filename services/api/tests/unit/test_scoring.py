import random
from datetime import UTC, datetime, timedelta

import pytest
from app.domain.scoring import score
from app.priority_schemas import CategoryPolicy, Policy, ScoreInputs
from pydantic import ValidationError

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)
POLICY = Policy(
    version="unit-v1", categories={"pothole": CategoryPolicy(severity=0.6, target_hours=72)}
)


def inputs(**changes):
    return ScoreInputs.model_validate(
        {
            "as_of": NOW,
            "first_accepted_at": NOW - timedelta(hours=36),
            "category": "pothole",
            "eligible_reporters": 1,
            "school_distance_m": 50,
            "coverage_complete": True,
            "urgency_override": 0.5,
            **changes,
        }
    )


@pytest.mark.parametrize("n,age,expected", [(1, 36, 51), (10, 36, 66), (10, 72, 76)])
def test_exact_worked_examples(n, age, expected):
    result = score(
        inputs(eligible_reporters=n, first_accepted_at=NOW - timedelta(hours=age)), POLICY
    )
    assert result.score == expected
    assert sum(result.contributions.values()) == pytest.approx(expected)


@pytest.mark.parametrize(
    "weights",
    [
        {"S": 1},
        {"S": 0.36, "A": 0.2, "R": 0.15, "L": 0.2, "U": 0.1},
        {"S": float("nan"), "A": 0.2, "R": 0.15, "L": 0.2, "U": 0.1},
    ],
)
def test_bad_weights_rejected(weights):
    with pytest.raises(ValidationError):
        Policy(version="bad-v1", weights=weights, categories=POLICY.categories)


def test_clamps_future_age_zero_reporters_and_missing_context():
    result = score(
        inputs(
            first_accepted_at=NOW + timedelta(hours=20),
            eligible_reporters=0,
            severity_override=20,
            urgency_override=-20,
            coverage_complete=False,
        ),
        POLICY,
    )
    assert result.factors == {"S": 1, "A": 0, "R": 0, "L": 0.5, "U": 0}
    assert {"future_first_accepted_at", "no_eligible_reporters", "location_context_unknown"} <= set(
        result.flags
    )
    absent = score(inputs(school_distance_m=None, hospital_distance_m=None), POLICY)
    unknown = score(inputs(school_distance_m=None, coverage_complete=False), POLICY)
    assert absent.factors["L"] == 0 and unknown.factors["L"] == 0.5


def test_location_max_not_sum_urgency_pending_and_critical_expiry():
    result = score(
        inputs(
            hospital_distance_m=20,
            major_road=True,
            urgency_override=None,
            critical_override=True,
            critical_review_due_at=NOW - timedelta(hours=1),
        ),
        POLICY,
    )
    assert result.factors["L"] == 0.9 and result.band == "critical"
    assert {"urgency_review_pending", "critical_review_overdue"} <= set(result.flags)
    assert score(inputs(first_accepted_at=NOW - timedelta(hours=200)), POLICY).overdue
    assert score(inputs(first_accepted_at=NOW - timedelta(hours=200)), POLICY).factors["A"] == 1


def test_monotonicity_randomized_fixed_context_and_reporter_cap():
    rng = random.Random(6)
    for _ in range(500):
        n = rng.randint(1, 100)
        age = rng.uniform(0, 500)
        base = inputs(eligible_reporters=n, first_accepted_at=NOW - timedelta(hours=age))
        start = score(base, POLICY).score
        assert score(base.model_copy(update={"eligible_reporters": n + 1}), POLICY).score >= start
        assert (
            score(
                base.model_copy(
                    update={"first_accepted_at": base.first_accepted_at - timedelta(hours=1)}
                ),
                POLICY,
            ).score
            >= start
        )
        assert all(0 <= f <= 1 for f in score(base, POLICY).factors.values())
    assert score(inputs(eligible_reporters=10), POLICY).factors["R"] == 1
    assert score(inputs(eligible_reporters=10000), POLICY).factors["R"] == 1


def test_severity_override_preserves_baseline_and_model_confidence_is_not_input():
    assert score(inputs(severity_override=0.25), POLICY).factors["S"] == 0.25
    assert POLICY.categories["pothole"].severity == 0.6
    with pytest.raises(ValidationError):
        inputs(model_confidence=0.99)
    with pytest.raises(ValidationError):
        inputs(as_of=NOW.replace(tzinfo=None))


def test_burst_is_review_flag_and_does_not_change_score():
    ordinary = score(inputs(eligible_reporters=5), POLICY)
    burst = score(inputs(eligible_reporters=5, recent_reporters=5), POLICY)
    assert "reporter_burst_review_pending" in burst.flags
    assert ordinary.score == burst.score
