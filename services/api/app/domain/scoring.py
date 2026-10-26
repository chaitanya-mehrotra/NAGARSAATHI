import math

from app.priority_schemas import Policy, Score, ScoreInputs


def clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def score(inputs: ScoreInputs, policy: Policy) -> Score:
    category = policy.categories[inputs.category]
    raw_age = (inputs.as_of - inputs.first_accepted_at).total_seconds() / 3600
    age = max(0, raw_age)
    flags = []
    if inputs.recent_reporters >= 5:
        flags.append("reporter_burst_review_pending")
    if raw_age < 0:
        flags.append("future_first_accepted_at")
    if inputs.eligible_reporters == 0:
        flags.append("no_eligible_reporters")
    if not inputs.coverage_complete:
        flags.append("location_context_unknown")
    if inputs.urgency_override is None:
        flags.append("urgency_review_pending")
    if inputs.critical_override and (
        inputs.critical_review_due_at is None or inputs.critical_review_due_at <= inputs.as_of
    ):
        flags.append("critical_review_overdue")
    location = (
        max(
            [0.5 if inputs.major_road else 0.0]
            + [
                clamp(1 - d / policy.poi_radius_m)
                for d in (inputs.school_distance_m, inputs.hospital_distance_m)
                if d is not None
            ]
        )
        if inputs.coverage_complete
        else 0.5
    )
    factors = {
        "S": clamp(
            inputs.severity_override if inputs.severity_override is not None else category.severity
        ),
        "A": clamp(age / category.target_hours),
        "R": clamp(math.log(max(1, inputs.eligible_reporters)) / math.log(10)),
        "L": location,
        "U": clamp(inputs.urgency_override if inputs.urgency_override is not None else 0.5),
    }
    contributions = {key: 100 * policy.weights[key] * value for key, value in factors.items()}
    zone_weight = getattr(inputs, "zone_traffic_weight", 1.0) or 1.0
    if zone_weight > 1.0:
        flags.append(f"traffic_heavy_zone_boost_{int(round((zone_weight - 1.0) * 100))}_pct")
    base_sum = sum(contributions.values())
    total = round(min(100.0, max(0.0, base_sum * zone_weight)), 2)
    return Score(
        score=total,
        band="critical"
        if inputs.critical_override
        else "high"
        if total >= 70
        else "medium"
        if total >= 40
        else "low",
        factors=factors,
        contributions=contributions,
        flags=flags,
        age_hours=age,
        overdue=age >= category.target_hours,
        urgency_source="reviewer" if inputs.urgency_override is not None else "provisional",
    )
