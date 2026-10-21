"""Small SQLite store with atomic due-run creation and occurrence deduplication."""

import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_DB = Path(__file__).resolve().parents[1] / ".data" / "heyclicky-demo.db"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(timezone.utc)


def encode_time(value: datetime) -> str:
    return as_utc(value).isoformat(timespec="microseconds")


def decode_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def connect() -> sqlite3.Connection:
    path = Path(os.environ.get("CLICKY_DEMO_DB", str(DEFAULT_DB)))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def initialize() -> None:
    with closing(connect()) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                prompt TEXT NOT NULL,
                every_minutes INTEGER NOT NULL CHECK (every_minutes BETWEEN 1 AND 43200),
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                created_at TEXT NOT NULL,
                next_run_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                schedule_id TEXT NOT NULL REFERENCES schedules(id),
                occurrence_at TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('queued')),
                UNIQUE (schedule_id, occurrence_at)
            );

            CREATE INDEX IF NOT EXISTS runs_schedule_occurrence
                ON runs (schedule_id, occurrence_at);
            """
        )


def schedule_payload(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "prompt": row["prompt"],
        "every_minutes": row["every_minutes"],
        "enabled": bool(row["enabled"]),
        "created_at": decode_time(row["created_at"]),
        "next_run_at": decode_time(row["next_run_at"]),
    }


def run_payload(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "schedule_id": row["schedule_id"],
        "occurrence_at": decode_time(row["occurrence_at"]),
        "prompt": row["prompt"],
        "status": row["status"],
    }


def create_schedule(data: Any, now: datetime) -> Dict[str, Any]:
    now = as_utc(now)
    first_run = as_utc(data.starts_at) if data.starts_at else now + timedelta(minutes=data.every_minutes)
    schedule_id = str(uuid.uuid4())
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO schedules
               (id, title, prompt, every_minutes, enabled, created_at, next_run_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (
                schedule_id,
                data.title,
                data.prompt,
                data.every_minutes,
                encode_time(now),
                encode_time(first_run),
            ),
        )
        row = connection.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        connection.commit()
        return schedule_payload(row)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def list_schedules() -> List[Dict[str, Any]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM schedules ORDER BY created_at, id"
        ).fetchall()
        return [schedule_payload(row) for row in rows]


def get_schedule(schedule_id: str) -> Optional[Dict[str, Any]]:
    with closing(connect()) as connection:
        row = connection.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        return schedule_payload(row) if row else None


def change_schedule(schedule_id: str, enabled: bool, now: datetime) -> Optional[Dict[str, Any]]:
    now = as_utc(now)
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        if row is None:
            connection.rollback()
            return None
        if enabled:
            next_run = now + timedelta(minutes=row["every_minutes"])
            connection.execute(
                "UPDATE schedules SET enabled = 1, next_run_at = ? WHERE id = ?",
                (encode_time(next_run), schedule_id),
            )
        else:
            connection.execute("UPDATE schedules SET enabled = 0 WHERE id = ?", (schedule_id,))
        updated = connection.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        connection.commit()
        return schedule_payload(updated)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def enqueue_due(at: datetime, max_occurrences: int = 500) -> List[Dict[str, Any]]:
    """Create one queued row for each due occurrence in a single write transaction."""
    at = as_utc(at)
    connection = connect()
    created: List[Dict[str, Any]] = []
    processed = 0
    try:
        # Serializes competing scheduler ticks before checking due times.
        connection.execute("BEGIN IMMEDIATE")
        schedules = connection.execute(
            "SELECT * FROM schedules WHERE enabled = 1 AND next_run_at <= ? ORDER BY next_run_at, id",
            (encode_time(at),),
        ).fetchall()
        for schedule in schedules:
            next_run = decode_time(schedule["next_run_at"])
            interval = timedelta(minutes=schedule["every_minutes"])
            while next_run <= at and processed < max_occurrences:
                run_id = str(uuid.uuid4())
                cursor = connection.execute(
                    """INSERT INTO runs (id, schedule_id, occurrence_at, prompt, status)
                       VALUES (?, ?, ?, ?, 'queued')
                       ON CONFLICT (schedule_id, occurrence_at) DO NOTHING""",
                    (
                        run_id,
                        schedule["id"],
                        encode_time(next_run),
                        schedule["prompt"],
                    ),
                )
                if cursor.rowcount:
                    row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
                    created.append(run_payload(row))
                next_run += interval
                processed += 1
            connection.execute(
                "UPDATE schedules SET next_run_at = ? WHERE id = ?",
                (encode_time(next_run), schedule["id"]),
            )
            if processed >= max_occurrences:
                break
        connection.commit()
        return created
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def list_runs(schedule_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    with closing(connect()) as connection:
        if schedule_id:
            rows = connection.execute(
                "SELECT * FROM runs WHERE schedule_id = ? ORDER BY occurrence_at, id LIMIT ?",
                (schedule_id, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY occurrence_at, id LIMIT ?", (limit,)
            ).fetchall()
        return [run_payload(row) for row in rows]
