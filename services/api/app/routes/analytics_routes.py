"""Aggregated complaint statistics for the staff Reports page.

Every number is computed in SQL with the same status rule as the complaints list, and each
section says what it counts (see `notes`), so a chart can be traced back to its denominator.
"""

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

from app.domain.enums import Role
from app.domain.report_status import DISPLAY_STATUS_SQL, DISPLAY_STATUSES, REPORT_WITH_ISSUE_SQL
from app.routes.auth_routes import CurrentActor

router = APIRouter(prefix="/api/v1", tags=["Analytics"])

LOCAL = ZoneInfo("Asia/Kolkata")
MAX_DAYS = 366
BACKLOG_BUCKETS = ("0-2", "3-7", "8-30", "30+")


def _day(value: str, field: str) -> date | None:
    if not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(422, f"{field} must be a date like 2026-10-29") from None


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


@router.get("/analytics/summary")
def analytics_summary(
    request: Request,
    actor: CurrentActor,
    since: str = "",
    until: str = "",
    category: str = "",
    area: str = "",
) -> dict[str, Any]:
    if not (actor.has_role(Role.ADMIN) or actor.has_role(Role.NIGAM) or actor.has_role(Role.REVIEWER)):
        raise HTTPException(403, "Reviewer or administrator permission required")

    now = datetime.now(LOCAL)
    last = _day(until, "until") or now.date()
    first = _day(since, "since") or last - timedelta(days=29)
    if first > last:
        raise HTTPException(422, "since must not be after until")
    if (last - first).days >= MAX_DAYS:
        raise HTTPException(422, f"The range may cover at most {MAX_DAYS} days")
    granularity = "day" if (last - first).days < 31 else "week"

    params: dict[str, Any] = {"first": first, "last": last}
    report_where = [
        "r.deleted_at IS NULL",
        "(r.received_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN :first AND :last",
    ]
    issue_where = ["i.status <> 'merged'"]
    if category.strip():
        params["category"] = category.strip()
        report_where.append("r.claimed_category = :category")
        issue_where.append("i.category_code = :category")
    if area.strip():
        params["area"] = area.strip()
        report_where.append("ar.code = :area")
        issue_where.append("ia.code = :area")
    rw = " AND ".join(report_where)
    iw = " AND ".join(issue_where)
    base = f"{REPORT_WITH_ISSUE_SQL} LEFT JOIN areas ar ON ar.id = r.area_id"
    issue_base = "issues i JOIN areas ia ON ia.id = i.area_id"

    with request.app.state.engine.connect() as connection:
        run = lambda sql, extra=None: connection.execute(  # noqa: E731
            text(sql), {**params, **(extra or {})}
        ).mappings().all()

        totals = run(
            f"""SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE r.is_suspicious) AS flagged
                FROM {base} WHERE {rw}"""
        )[0]
        by_status_rows = run(
            f"SELECT {DISPLAY_STATUS_SQL} AS status, COUNT(*) AS n FROM {base} WHERE {rw} GROUP BY 1"
        )
        by_category_rows = run(
            f"""SELECT r.claimed_category AS category, COUNT(*) AS n
                FROM {base} WHERE {rw} GROUP BY 1 ORDER BY n DESC, 1"""
        )
        volume_rows = run(
            f"""SELECT date_trunc(:gran, r.received_at AT TIME ZONE 'Asia/Kolkata')::date AS bucket,
                       r.claimed_category AS category, COUNT(*) AS n
                FROM {base} WHERE {rw} GROUP BY 1, 2""",
            {"gran": granularity},
        )
        area_rows = run(
            f"""SELECT COALESCE(ar.code, 'unassigned') AS code,
                       COALESCE(ar.display_name, 'Unassigned') AS name,
                       COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE ({DISPLAY_STATUS_SQL}) IN ('open', 'in_progress')) AS open_n
                FROM {base} WHERE {rw} GROUP BY 1, 2 ORDER BY n DESC, 2 LIMIT 10"""
        )
        photo_rows = run(
            f"""SELECT COALESCE(v.decision, 'unchecked') AS decision, COUNT(*) AS n
                FROM {base}
                LEFT JOIN LATERAL (
                    SELECT decision FROM validation_results vr
                    WHERE vr.report_id = r.id ORDER BY vr.completed_at DESC LIMIT 1
                ) v ON TRUE
                WHERE {rw} GROUP BY 1"""
        )
        resolution_rows = run(
            f"""WITH done AS (
                    SELECT i.category_code,
                           EXTRACT(EPOCH FROM (
                               COALESCE((SELECT MAX(e.created_at) FROM issue_events e
                                         WHERE e.issue_id = i.id AND (e.to_state = 'resolved' OR e.action = 'verify')),
                                        i.updated_at) - i.first_accepted_at)) / 3600.0 AS hours
                    FROM {issue_base}
                    WHERE {iw} AND i.status = 'resolved'
                      AND (i.first_accepted_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN :first AND :last
                )
                SELECT d.category_code AS category, COUNT(*) AS n,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY GREATEST(d.hours, 0)) AS median_hours,
                       percentile_cont(0.9) WITHIN GROUP (ORDER BY GREATEST(d.hours, 0)) AS p90_hours,
                       COUNT(*) FILTER (WHERE d.hours <= c.target_resolution_hours) AS within_target,
                       MAX(c.target_resolution_hours) AS target_hours
                FROM done d JOIN categories c ON c.code = d.category_code
                GROUP BY 1 ORDER BY n DESC, 1"""
        )
        backlog_rows = run(
            f"""SELECT CASE WHEN age_days <= 2 THEN '0-2' WHEN age_days <= 7 THEN '3-7'
                            WHEN age_days <= 30 THEN '8-30' ELSE '30+' END AS bucket, COUNT(*) AS n
                FROM (SELECT FLOOR(EXTRACT(EPOCH FROM (now() - i.first_accepted_at)) / 86400) AS age_days
                      FROM {issue_base}
                      WHERE {iw} AND i.status NOT IN ('resolved')) t
                GROUP BY 1"""
        )
        top_rows = run(
            f"""SELECT i.id, i.public_reference, i.category_code, i.status, ia.display_name AS area_name,
                       i.first_accepted_at, i.report_count, ps.score, ps.band
                FROM {issue_base} LEFT JOIN priority_snapshots ps ON ps.id = i.current_priority_snapshot_id
                WHERE {iw} AND i.status NOT IN ('resolved')
                ORDER BY ps.score DESC NULLS LAST, i.first_accepted_at LIMIT 10"""
        )

    # Fill empty days/weeks so a quiet day shows as zero rather than being skipped.
    buckets: list[date] = []
    cursor = first if granularity == "day" else _monday(first)
    step = timedelta(days=1 if granularity == "day" else 7)
    while cursor <= last:
        buckets.append(cursor)
        cursor += step
    volume: dict[date, dict[str, int]] = {b: {} for b in buckets}
    for row in volume_rows:
        volume.setdefault(row["bucket"], {})[row["category"]] = row["n"]

    statuses = dict.fromkeys(DISPLAY_STATUSES, 0) | {r["status"]: r["n"] for r in by_status_rows}
    photo = {r["decision"]: r["n"] for r in photo_rows}
    checked = sum(n for key, n in photo.items() if key != "unchecked")
    backlog = dict.fromkeys(BACKLOG_BUCKETS, 0) | {r["bucket"]: r["n"] for r in backlog_rows}

    return {
        "as_of": now.isoformat(),
        "range": {"since": first.isoformat(), "until": last.isoformat(), "granularity": granularity},
        "filters": {"category": category.strip() or None, "area": area.strip() or None},
        "totals": {"reports": totals["total"], "flagged": totals["flagged"]},
        "by_status": statuses,
        "by_category": [{"category": r["category"], "count": r["n"]} for r in by_category_rows],
        "volume": [
            {"bucket": b.isoformat(), "total": sum(v.values()), "by_category": v}
            for b, v in sorted(volume.items())
        ],
        "areas": [
            {"code": r["code"], "name": r["name"], "count": r["n"], "open": r["open_n"]}
            for r in area_rows
        ],
        "photo_check": {
            "checked": checked,
            "unchecked": photo.get("unchecked", 0),
            "accepted": photo.get("accepted", 0),
            "needs_review": photo.get("needs_review", 0) + photo.get("error", 0),
            "flagged": totals["flagged"],
        },
        "resolution": [
            {
                "category": r["category"],
                "resolved": r["n"],
                "median_hours": round(float(r["median_hours"]), 1),
                "p90_hours": round(float(r["p90_hours"]), 1),
                "target_hours": float(r["target_hours"]),
                "within_target": r["within_target"],
            }
            for r in resolution_rows
        ],
        "backlog": [{"bucket": b, "count": backlog[b]} for b in BACKLOG_BUCKETS],
        "top_priorities": [
            {
                "id": str(r["id"]),
                "reference": r["public_reference"],
                "category": r["category_code"],
                "status": r["status"],
                "area": r["area_name"],
                "first_accepted_at": r["first_accepted_at"].isoformat(),
                "reports": r["report_count"],
                "score": None if r["score"] is None else round(float(r["score"]), 1),
                "band": r["band"],
            }
            for r in top_rows
        ],
        "notes": {
            "reports": "Reports received in the date range (pilot local days), excluding deleted ones.",
            "by_status": "Same reports, by the status shown in the complaints list.",
            "resolution": "Repair tasks first accepted in the range and now resolved; hours from acceptance to resolution.",
            "backlog": "Repair tasks not yet resolved right now, by age since acceptance. Ignores the date range.",
            "top_priorities": "Highest-scoring unresolved repair tasks right now. Ignores the date range.",
            "photo_check": "Latest automatic photo check per report in the range; flagged means held for human review.",
        },
    }
