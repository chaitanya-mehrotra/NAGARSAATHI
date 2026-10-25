from unittest.mock import patch
from uuid import uuid4

from test_intake import auth, upload
from test_issues import ADMIN, accepted, choose, image, issue
from test_issues import issue_api as issue_api


def assigned(api):
    client, _ = api
    report = accepted(api)
    current = issue(client, report)
    operator = client.get(f"/api/v1/issues/{current['id']}/assignees", headers=ADMIN).json()[0][
        "id"
    ]
    response = client.post(
        f"/api/v1/issues/{current['id']}/assign",
        headers=ADMIN,
        json={
            "operator_id": operator,
            "expected_version": current["row_version"],
            "request_id": str(uuid4()),
            "reason": "Assign repair fixture",
        },
    )
    assert response.status_code == 200, response.text
    return report, response.json()


def act(client, current, action, who="demo-operator", media=None):
    return client.post(
        f"/api/v1/work/{current['id']}",
        headers=auth(who),
        json={
            "request_id": str(uuid4()),
            "expected_version": current["row_version"],
            "action": action,
            "reason": "Inspected work lifecycle evidence",
            "media_ids": [media] if media else [],
        },
    )


def test_complete_verified_repair_archive_reopen_and_shared_status(issue_api):
    client, _ = issue_api
    report, current = assigned(issue_api)
    second = accepted(issue_api)
    assert choose(client, second, "link", current).status_code == 200
    current = issue(client, report)
    assert act(client, current, "verify", "demo-admin").status_code == 409
    assert act(client, current, "start", "demo-citizen").status_code == 404
    started = act(client, current, "start")
    assert started.status_code == 200, started.text
    current = started.json()
    photo = upload(client, "demo-operator", image())
    pending = act(client, current, "submit_repair", media=photo)
    assert pending.status_code == 200, pending.text
    current = pending.json()
    assert current["status"] == "resolution_pending"
    assert client.get("/api/v1/staff/queue", headers=ADMIN).json()["total_issues"] == 1
    assert act(client, current, "verify").status_code == 403
    verified = act(client, current, "verify", "demo-admin")
    assert verified.status_code == 200, verified.text
    current = verified.json()
    for r in [report, second]:
        assert (
            client.get(f"/api/v1/reports/{r['id']}", headers=auth()).json()["issue_status"]
            == "resolved"
        )
    archived = act(client, current, "archive", "demo-admin")
    assert archived.status_code == 200, archived.text
    history = client.get(f"/api/v1/work/{current['id']}", headers=ADMIN).json()
    assert history["archived_at"] and history["repairs"][0]["verification_state"] == "verified"
    assert client.get(f"/api/v1/media/{photo}/content", headers=ADMIN).status_code == 200
    assert client.get(f"/api/v1/media/{photo}/content", headers=auth()).status_code == 404
    recurrence = accepted(issue_api)
    assert choose(client, recurrence, "recurrence", issue(client, report)).status_code == 200
    assert (
        client.get("/api/v1/reports/" + recurrence["id"], headers=auth()).json()["issue_id"]
        != current["id"]
    )
    reopened = act(client, archived.json(), "reopen", "demo-admin")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "reopened"
    assert client.get(f"/api/v1/work/{current['id']}", headers=ADMIN).json()["archived_at"] is None


def test_new_evidence_invalidates_repair_failed_verification_and_access(issue_api):
    client, _ = issue_api
    report, current = assigned(issue_api)
    old = current
    current = act(client, current, "start").json()
    assert act(client, old, "start").status_code == 409
    assert act(client, current, "submit_repair").status_code == 422
    photo = upload(client, "demo-operator", image())
    current = act(client, current, "submit_repair", media=photo).json()
    with patch(
        "app.adapters.local_media.LocalMedia.read", side_effect=OSError("storage unavailable")
    ):
        assert act(client, current, "verify", "demo-admin").status_code == 503
    extra = accepted(issue_api)
    assert choose(client, extra, "link", current).status_code == 200
    current = issue(client, report)
    assert act(client, current, "verify", "demo-admin").status_code == 409
    rejected = act(client, current, "reject", "demo-admin")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "in_progress"
    assert (
        client.get(f"/api/v1/work/{current['id']}", headers=ADMIN).json()["repairs"][0][
            "verification_state"
        ]
        == "failed"
    )
    outsider = accepted(issue_api, lon=77.65)
    assert (
        client.get(
            f"/api/v1/work/{outsider['issue_id']}", headers=auth("demo-operator")
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/issues/{report['issue_id']}", headers=auth("demo-operator")
        ).status_code
        == 403
    )
