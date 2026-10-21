# Clicky Recurring Runs

A small typed REST API for user-requested recurring agent work. It stores schedules in SQLite, queues every due occurrence, and prevents duplicate queue rows when scheduler ticks overlap.

## Why this demo

HeyClicky is a voice-first interface for AI agents on the Mac. Its public product updates show that recurring work is user initiated and visible, while its Trust page emphasizes user control. This demo explores one backend detail behind that kind of feature: turning an explicit schedule into reliable, inspectable run records without silently inferring when someone wants an agent to act.

The service does not connect to HeyClicky or call an AI model. It is a local, standalone portfolio demo.

## Run it

Python 3.9 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the generated OpenAPI explorer.

The SQLite file is created at `.data/heyclicky-demo.db`. Set `CLICKY_DEMO_DB=/path/to/file.sqlite3` to choose another location.

## API

- `POST /schedules` — create an explicit schedule. The first run defaults to one interval from creation; `starts_at` can set an exact timezone-aware start.
- `GET /schedules` — list schedules and their next run time.
- `POST /schedules/{id}/pause` — stop a schedule.
- `POST /schedules/{id}/resume` — resume it with a fresh interval, so missed work does not suddenly flood the queue.
- `POST /scheduler/tick` — enqueue due occurrences. Omit `at` to use the current UTC time; provide it to replay a deterministic clock in a demo.
- `GET /runs` — inspect queued runs, optionally filtered by `schedule_id`.
- `GET /healthz` — health check.

Ticks take a SQLite `BEGIN IMMEDIATE` write lock before checking due times. A unique `(schedule_id, occurrence_at)` constraint is the final guard against duplicate rows. Long outages are caught up in batches of at most 500 occurrences per tick.

## Example

Create a schedule:

```bash
curl -s http://127.0.0.1:8000/schedules \
  -H 'content-type: application/json' \
  -d '{"title":"Morning digest","prompt":"Summarize my project updates.","every_minutes":60}'
```

The schedule becomes due after one hour. Once due, ask the scheduler to enqueue it and inspect the queue:

```bash
curl -s -X POST http://127.0.0.1:8000/scheduler/tick -H 'content-type: application/json' -d '{}'
curl -s http://127.0.0.1:8000/runs
```

A second tick at the same time creates no duplicate run. See [`demo/session.txt`](demo/session.txt) for a captured API session.

## Tests

```bash
python -m pip install -r requirements.txt
pytest
```

The tests cover catch-up, repeated and concurrent ticks, pause/resume behavior, timezone validation, and missing schedules.

## Product references

- [HeyClicky careers](https://www.heyclicky.com/careers) — current roles and the team's emphasis on shipping quickly with attention to detail.
- [HeyClicky Trust](https://www.heyclicky.com/trust) — product control and privacy notes.
- [HeyClicky changelog](https://www.heyclicky.com/changelog) — public product changes, including routines and background agents.
- [Nilesh Rathore](https://nilesh.so/) — product engineer at HeyClicky; describes the goal as a simple voice interface for AI agents.
