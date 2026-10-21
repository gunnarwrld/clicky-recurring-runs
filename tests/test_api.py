from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    database = tmp_path / "test.sqlite3"
    monkeypatch.setenv("CLICKY_DEMO_DB", str(database))
    with TestClient(app) as test_client:
        yield test_client


def create_due_schedule(client, starts_at="2026-10-21T10:00:00Z"):
    response = client.post(
        "/schedules",
        json={
            "title": "Morning digest",
            "prompt": "Summarize the latest project updates.",
            "every_minutes": 60,
            "starts_at": starts_at,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_tick_catches_up_due_occurrences_once(client):
    schedule = create_due_schedule(client)

    first = client.post("/scheduler/tick", json={"at": "2026-10-21T12:05:00Z"})
    second = client.post("/scheduler/tick", json={"at": "2026-10-21T12:05:00Z"})

    assert first.status_code == 200
    assert first.json()["count"] == 3
    assert second.json()["count"] == 0
    runs = client.get("/runs", params={"schedule_id": schedule["id"]}).json()
    assert len(runs) == 3
    assert [run["occurrence_at"] for run in runs] == [
        "2026-10-21T10:00:00Z",
        "2026-10-21T11:00:00Z",
        "2026-10-21T12:00:00Z",
    ]


def test_concurrent_ticks_create_one_run_for_each_occurrence(client):
    create_due_schedule(client, starts_at="2026-10-21T12:00:00Z")
    tick = lambda: client.post("/scheduler/tick", json={"at": "2026-10-21T12:00:00Z"}).json()["count"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        created_counts = list(pool.map(lambda _: tick(), range(8)))

    assert sum(created_counts) == 1
    assert len(client.get("/runs").json()) == 1


def test_pause_stops_ticks_and_resume_starts_a_fresh_interval(client):
    schedule = create_due_schedule(client)
    paused = client.post("/schedules/{}/pause".format(schedule["id"]))
    assert paused.status_code == 200
    assert paused.json()["enabled"] is False

    tick = client.post("/scheduler/tick", json={"at": "2026-10-21T12:00:00Z"})
    assert tick.json()["count"] == 0

    resumed = client.post("/schedules/{}/resume".format(schedule["id"]))
    assert resumed.status_code == 200
    assert resumed.json()["enabled"] is True
    assert resumed.json()["next_run_at"] > datetime.now(timezone.utc).isoformat()


def test_schedule_rejects_timezone_free_start_time(client):
    response = client.post(
        "/schedules",
        json={
            "title": "Digest",
            "prompt": "Summarize updates.",
            "every_minutes": 30,
            "starts_at": "2026-10-21T12:00:00",
        },
    )
    assert response.status_code == 422


def test_unknown_schedule_returns_not_found(client):
    response = client.post("/schedules/missing/pause")
    assert response.status_code == 404
