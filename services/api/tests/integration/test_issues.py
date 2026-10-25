import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from app.demo_seed import seed_foundation
from app.domain.issues import admit, process_admission_once
from app.main import create_app
from app.settings import PROJECT_ROOT, Settings
from conftest import migrate, temporary_database
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_intake import auth, body, submit, upload

ADMIN = auth("demo-admin")


@pytest.fixture
def issue_api(tmp_path):
    with temporary_database() as (engine, base):
        migrate(engine, "head")
        with engine.begin() as connection:
            seed_foundation(connection, base)
        settings = Settings(
            _env_file=None,
            app_mode="test",
            database_url=base.database_url,
            storage_root=tmp_path / "media",
        )
        with TestClient(
            create_app(settings, engine=engine), raise_server_exceptions=False
        ) as client:
            yield client, engine


def image():
    output = BytesIO()
    Image.new("RGB", (12, 8), tuple(uuid4().bytes[:3])).save(output, "PNG")
    return output.getvalue()


def accepted(
    api,
    lon=77.615,
    lat=12.915,
    subject="demo-citizen",
    category="pothole",
    content=None,
    asset=None,
    admission=True,
):
    client, engine = api
    media = upload(client, subject, content or image())
    payload = body(media, lon, lat)
    payload["claimed_category"] = category
    response = submit(client, payload, subject)
    assert response.status_code == 201, response.text
    record = response.json()
    decision = {
        "expected_revision": record["content_revision"],
        "request_id": str(uuid4()),
        "decision": "accepted",
        "category": category,
        "reason": "Inspected synthetic evidence",
        "trusted_asset_id": asset,
    }
    response = client.post(f"/api/v1/reviews/{record['id']}/decision", json=decision, headers=ADMIN)
    assert response.status_code == 200, response.text
    record = response.json()
    if admission:
        with engine.begin() as connection:
            admit(connection, UUID(record["id"]), record["content_revision"])
    return client.get(f"/api/v1/reports/{record['id']}", headers=auth(subject)).json()


def choose(client, record, action, issue=None, headers=ADMIN):
    payload = {
        "expected_revision": record["content_revision"],
        "request_id": str(uuid4()),
        "action": action,
        "reason": "Compared location and physical defect evidence",
    }
    if issue:
        payload.update(issue_id=issue["id"], expected_issue_version=issue["row_version"])
    return client.post(
        f"/api/v1/reviews/duplicates/{record['id']}/decision", json=payload, headers=headers
    )


def issue(client, record):
    response = client.get(f"/api/v1/issues/{record['issue_id']}", headers=ADMIN)
    assert response.status_code == 200, response.text
    return response.json()


def test_nearby_different_defects_remain_separate_and_same_defect_links(issue_api):
    client, _ = issue_api
    first = accepted(issue_api)
    second = accepted(issue_api, lon=77.61507)
    assert first["state"] == "admitted" and second["state"] == "awaiting_review"
    inbox = client.get("/api/v1/reviews/duplicates", headers=ADMIN).json()
    candidate = inbox[0]["candidates"][0]
    assert 0 < candidate["distance_m"] < 20 and not candidate["asset_conflict"]
    assert choose(client, second, "new").status_code == 200
    third = accepted(issue_api, lon=77.61502, subject="demo-citizen-2")
    target = issue(client, first)
    linked = choose(client, third, "link", target)
    assert linked.status_code == 200, linked.text
    assert linked.json()["report_count"] == 2
    assert linked.json()["eligible_reporter_count"] == 2
    assert len(client.get("/api/v1/issues", headers=ADMIN).json()) == 2
    assert client.get(f"/api/v1/issues/{first['issue_id']}", headers=auth()).status_code == 403
    nearby = client.get(
        "/api/v1/issues/nearby?longitude=77.615&latitude=12.915&category=pothole", headers=auth()
    ).json()
    assert len(nearby) == 2 and "reports" not in nearby[0]


def test_cross_area_candidate_requires_scope_on_both_and_keeps_issue_owner(issue_api):
    client, _ = issue_api
    first = accepted(issue_api, lon=77.63004)
    second = accepted(issue_api, lon=77.62996)
    assert second["state"] == "awaiting_review"
    inbox = client.get("/api/v1/reviews/duplicates", headers=auth("demo-reviewer")).json()
    assert inbox[0]["needs_cross_area_admin"] and inbox[0]["candidates"] == []
    target = issue(client, first)
    assert choose(client, second, "link", target, auth("demo-reviewer")).status_code == 403
    result = choose(client, second, "link", target)
    assert result.status_code == 200, result.text
    assert result.json()["area_code"] == first["area_code"] != second["area_code"]


def test_same_photo_far_away_is_reviewed_and_repeated_reporter_is_not_extra_support(issue_api):
    client, _ = issue_api
    content = image()
    first = accepted(issue_api, content=content)
    far = accepted(issue_api, lon=77.62, content=content)
    assert far["review_reason"] == "reused_photo_conflicting_location" and far["evidence_reused"]
    same = accepted(issue_api, content=content)
    target = issue(client, first)
    response = choose(client, same, "link", target)
    assert response.status_code == 200, response.text
    assert response.json()["report_count"] == 2
    assert response.json()["eligible_reporter_count"] == 1


def add_asset(engine, code, lon, name):
    with engine.begin() as connection:
        return str(
            connection.execute(
                text("""
          INSERT INTO assets(source_asset_id,category_code,area_id,geom,source)
          SELECT :name,:code,id,ST_SetSRID(ST_MakePoint(:lon,12.915),4326)::geography,
                 'test_inventory'
          FROM areas WHERE code='southwest' RETURNING id
        """),
                {"name": name, "code": code, "lon": lon},
            ).scalar_one()
        )


def test_trusted_asset_conflict_blocks_link_and_merge(issue_api):
    client, engine = issue_api
    a = add_asset(engine, "pothole", 77.615, "A")
    b = add_asset(engine, "pothole", 77.61503, "B")
    first = accepted(issue_api, asset=a)
    second = accepted(issue_api, lon=77.61503, asset=b)
    assert second["state"] == "admitted" and first["issue_id"] != second["issue_id"]
    c = accepted(issue_api, asset=a)
    assert choose(client, c, "link", issue(client, second)).status_code == 409
    left, right = issue(client, first), issue(client, second)
    response = client.post(
        f"/api/v1/issues/{left['id']}/merge",
        headers=ADMIN,
        json={
            "request_id": str(uuid4()),
            "expected_version": left["row_version"],
            "target_id": right["id"],
            "expected_target_version": right["row_version"],
            "reason": "Attempt conflicting asset merge",
        },
    )
    assert response.status_code == 409


def test_only_enabled_trusted_unique_asset_can_auto_link(issue_api):
    client, engine = issue_api
    asset = add_asset(engine, "pothole", 77.615, "A")
    first = accepted(issue_api, asset=asset)
    pending = accepted(issue_api, asset=asset)
    assert pending["state"] == "awaiting_review"
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE categories SET auto_merge_allowed=true WHERE code='pothole'"
        )
    automatic = accepted(issue_api, asset=asset)
    assert automatic["issue_id"] == first["issue_id"]
    assert automatic["link_method"] == "asset_match"


def test_resolved_issue_creates_reviewed_recurrence_and_old_active_issues_still_match(issue_api):
    client, engine = issue_api
    first = accepted(issue_api)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE issues SET first_accepted_at=now()-interval '5 years' WHERE id=:id"),
            {"id": first["issue_id"]},
        )
    old = accepted(issue_api)
    assert old["state"] == "awaiting_review"
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE issues SET status='resolved',row_version=row_version+1 WHERE id=:id"),
            {"id": first["issue_id"]},
        )
    later = accepted(issue_api)
    target = issue(client, first)
    assert choose(client, later, "link", target).status_code == 409
    response = choose(client, later, "recurrence", target)
    assert response.status_code == 200, response.text
    assert response.json()["recurrence_parent_id"] == first["issue_id"]
    assert response.json()["id"] != first["issue_id"]
    assert issue(client, first)["status"] == "resolved"


def test_ten_concurrent_admissions_create_one_issue_and_nine_review_candidates(issue_api):
    client, engine = issue_api
    with ThreadPoolExecutor(max_workers=10) as pool:
        records = list(pool.map(lambda _: accepted(issue_api, admission=False), range(10)))

    def run(record):
        with engine.begin() as connection:
            admit(connection, UUID(record["id"]), record["content_revision"])

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(run, records))
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM issues").scalar_one() == 1
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM reports WHERE state='admitted'"
            ).scalar_one()
            == 1
        )
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM duplicate_candidates").scalar_one()
            == 9
        )


def test_candidate_version_conflict_does_not_link_stale_review(issue_api):
    client, engine = issue_api
    first = accepted(issue_api)
    second = accepted(issue_api)
    target = issue(client, first)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE issues SET row_version=row_version+1 WHERE id=:id"),
            {"id": first["issue_id"]},
        )
    assert choose(client, second, "link", target).status_code == 409
    assert client.get(f"/api/v1/reports/{second['id']}", headers=auth()).json()["issue_id"] is None


def merge_body(left, right):
    return {
        "request_id": str(uuid4()),
        "expected_version": left["row_version"],
        "target_id": right["id"],
        "expected_target_version": right["row_version"],
        "reason": "Reviewed the same physical defect and retained all evidence",
    }


def test_merge_split_preserve_alias_history_counts_and_idempotency(issue_api):
    client, engine = issue_api
    one = accepted(issue_api)
    two = accepted(issue_api, lon=77.6154, subject="demo-citizen-2")
    left, right = issue(client, one), issue(client, two)
    payload = merge_body(left, right)
    merged = client.post(f"/api/v1/issues/{left['id']}/merge", json=payload, headers=ADMIN)
    assert merged.status_code == 200, merged.text
    assert merged.json()["report_count"] == 2 and merged.json()["eligible_reporter_count"] == 2
    assert (
        client.post(f"/api/v1/issues/{left['id']}/merge", json=payload, headers=ADMIN).json()
        == merged.json()
    )
    alias = client.get(f"/api/v1/issues/{left['id']}", headers=ADMIN).json()
    assert alias["status"] == "merged" and alias["merged_into_id"] == right["id"]
    split_payload = {
        "request_id": str(uuid4()),
        "expected_version": merged.json()["row_version"],
        "report_ids": [one["id"]],
        "point": {"longitude": 77.615, "latitude": 12.915, "confirmed": True},
        "reason": "Evidence shows two distinct physical defects",
    }
    split = client.post(f"/api/v1/issues/{right['id']}/split", json=split_payload, headers=ADMIN)
    assert split.status_code == 200, split.text
    assert split.json()["report_count"] == 1
    assert (
        client.post(f"/api/v1/issues/{right['id']}/split", json=split_payload, headers=ADMIN).json()
        == split.json()
    )
    assert client.get(f"/api/v1/issues/{right['id']}", headers=ADMIN).json()["report_count"] == 1
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM reports").scalar_one() == 2
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM issue_report_links").scalar_one() == 4
        )
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM issue_report_links WHERE active"
            ).scalar_one()
            == 2
        )
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM jobs WHERE type='refresh_priority'"
            ).scalar_one()
            > 0
        )


def test_merge_failure_rolls_back_every_link_and_counter(issue_api):
    client, engine = issue_api
    one = accepted(issue_api)
    two = accepted(issue_api, lon=77.6154)
    left, right = issue(client, one), issue(client, two)
    with patch("app.domain.issue_review.refresh_aggregates", side_effect=RuntimeError("failure")):
        response = client.post(
            f"/api/v1/issues/{left['id']}/merge", json=merge_body(left, right), headers=ADMIN
        )
    assert response.status_code == 500
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM issue_report_links").scalar_one() == 2
        )
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM issues WHERE report_count=1 AND status='open'"
            ).scalar_one()
            == 2
        )


def test_reclassification_detaches_history_and_reenters_admission(issue_api):
    client, engine = issue_api
    original = accepted(issue_api)
    response = client.post(
        f"/api/v1/reviews/{original['id']}/decision",
        headers=ADMIN,
        json={
            "expected_revision": original["content_revision"],
            "request_id": str(uuid4()),
            "decision": "accepted",
            "category": "garbage_accumulation",
            "reason": "Evidence depicts rubbish not a pothole",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["issue_id"] is None
    with engine.begin() as connection:
        admit(connection, UUID(original["id"]), response.json()["content_revision"])
    current = client.get(f"/api/v1/reports/{original['id']}", headers=auth()).json()
    assert (
        current["canonical_category"] == "garbage_accumulation"
        and current["issue_id"] != original["issue_id"]
    )
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM issue_report_links").scalar_one() == 2
        )
    assert issue(client, original)["report_count"] == 0


def test_admission_worker_is_idempotent_and_link_removal_cannot_orphan_admitted_report(issue_api):
    client, engine = issue_api
    record = accepted(issue_api, admission=False)
    assert process_admission_once(engine)
    current = client.get(f"/api/v1/reports/{record['id']}", headers=auth()).json()
    assert current["state"] == "admitted", current
    with engine.begin() as connection:
        admit(connection, UUID(record["id"]), record["content_revision"])
    with pytest.raises(IntegrityError, match="active issue link"), engine.begin() as connection:
        connection.exec_driver_sql("UPDATE issue_report_links SET active=false,ended_at=now()")
    assert issue(client, current)["report_count"] == 1


def test_large_location_uncertainty_is_never_automatically_admitted(issue_api):
    client, engine = issue_api
    record = accepted(issue_api, admission=False)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE reports SET location_accuracy_m=200 WHERE id=:id"), {"id": record["id"]}
        )
        admit(connection, UUID(record["id"]), record["content_revision"])
    current = client.get(f"/api/v1/reports/{record['id']}", headers=auth()).json()
    assert (
        current["issue_id"] is None
        and current["review_reason"] == "location_quality_requires_review"
    )


def test_named_pair_candidate_recall_and_human_decisions_are_separate(issue_api):
    client, _ = issue_api
    catalog = json.loads((PROJECT_ROOT / "fixtures/duplicate-pairs.json").read_text())
    true_matches = retrieved = decisions = 0
    for pair in catalog["pairs"]:
        first = accepted(issue_api, lon=pair["first_longitude"])
        second = accepted(issue_api, lon=pair["second_longitude"])
        target = issue(client, first)
        if pair["same"]:
            true_matches += 1
            retrieved += int(second["state"] == "awaiting_review")
        assert (second["state"] == "awaiting_review") == pair["candidate"], pair["name"]
        if pair["candidate"]:
            response = choose(client, second, pair["decision"], target if pair["same"] else None)
            assert response.status_code == 200, (pair["name"], response.text)
            decisions += 1
        else:
            assert second["issue_id"] != first["issue_id"]
    assert retrieved == true_matches == 2
    assert decisions == 3


def test_citizen_hint_and_hazard_do_not_grant_linking_and_clarification_invalidates_job(issue_api):
    client, engine = issue_api
    first = accepted(issue_api)
    media = upload(client, content=image())
    payload = body(media)
    payload.update(suggested_issue_id=first["issue_id"], reported_hazard=True)
    record = submit(client, payload).json()
    assert record["reported_hazard"] and record["issue_id"] is None
    review = {
        "request_id": str(uuid4()),
        "expected_revision": record["content_revision"],
        "decision": "accepted",
        "category": "pothole",
        "reason": "Confirmed physical evidence",
    }
    response = client.post(f"/api/v1/reviews/{record['id']}/decision", json=review, headers=ADMIN)
    assert response.status_code == 200
    record = response.json()
    with engine.begin() as connection:
        admit(connection, UUID(record["id"]), record["content_revision"])
    assert choose(client, record, "link", issue(client, first), auth()).status_code == 403
    clarification = choose(client, record, "clarify")
    assert clarification.status_code == 200
    with engine.begin() as connection:
        admit(connection, UUID(record["id"]), record["content_revision"])
    current = client.get(f"/api/v1/reports/{record['id']}", headers=auth()).json()
    assert current["issue_id"] is None and current["validation_status"] == "needs_review"
    assert current["content_revision"] == record["content_revision"] + 1


def test_merge_and_split_scope_versions_and_proper_subset_are_enforced(issue_api):
    client, _ = issue_api
    first = accepted(issue_api)
    other = accepted(issue_api, lon=77.635)
    a, b = issue(client, first), issue(client, other)
    assert (
        client.post(
            f"/api/v1/issues/{a['id']}/merge", json=merge_body(a, b), headers=auth("demo-reviewer")
        ).status_code
        == 404
    )
    stale = merge_body(a, b)
    stale["expected_version"] += 1
    assert (
        client.post(f"/api/v1/issues/{a['id']}/merge", json=stale, headers=ADMIN).status_code == 409
    )
    merged = client.post(f"/api/v1/issues/{b['id']}/merge", json=merge_body(b, a), headers=ADMIN)
    assert merged.status_code == 200, merged.text
    payload = {
        "request_id": str(uuid4()),
        "expected_version": merged.json()["row_version"],
        "report_ids": [first["id"]],
        "point": {"longitude": 77.615, "latitude": 12.915, "confirmed": True},
        "reason": "Split independently reviewed defect",
    }
    # Report originating in another area prevents a scoped review from moving it.
    scoped = dict(payload, report_ids=[other["id"]])
    assert (
        client.post(
            f"/api/v1/issues/{a['id']}/split", json=scoped, headers=auth("demo-reviewer")
        ).status_code
        == 403
    )
    stale_split = dict(payload, expected_version=payload["expected_version"] + 1)
    assert (
        client.post(f"/api/v1/issues/{a['id']}/split", json=stale_split, headers=ADMIN).status_code
        == 409
    )
    entire = dict(payload, report_ids=[first["id"], other["id"]])
    assert (
        client.post(f"/api/v1/issues/{a['id']}/split", json=entire, headers=ADMIN).status_code
        == 409
    )
