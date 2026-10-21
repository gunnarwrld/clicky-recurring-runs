"""Run a deterministic HTTP demo and print the output used in session.txt."""

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="clicky-demo-") as folder:
        os.environ["CLICKY_DEMO_DB"] = str(Path(folder) / "demo.sqlite3")
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            print("1. Create an hourly project digest")
            created = client.post(
                "/schedules",
                json={
                    "title": "Project digest",
                    "prompt": "Summarize new project updates.",
                    "every_minutes": 60,
                    "starts_at": "2026-10-21T10:00:00Z",
                },
            ).json()
            print(json.dumps({key: created[key] for key in ("id", "title", "enabled", "next_run_at")}, indent=2))

            print("\n2. Tick the scheduler at 12:05 UTC")
            tick = client.post(
                "/scheduler/tick", json={"at": "2026-10-21T12:05:00Z"}
            ).json()
            print(json.dumps({"count": tick["count"], "occurrences": [run["occurrence_at"] for run in tick["created"]]}, indent=2))

            print("\n3. Tick again at the same time")
            repeated = client.post(
                "/scheduler/tick", json={"at": "2026-10-21T12:05:00Z"}
            ).json()
            print(json.dumps({"count": repeated["count"], "stored_runs": len(client.get("/runs").json())}, indent=2))


if __name__ == "__main__":
    main()
