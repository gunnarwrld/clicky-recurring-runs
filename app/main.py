from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, status

from . import store
from .models import RunRead, ScheduleCreate, ScheduleRead, TickRequest, TickResponse

@asynccontextmanager
async def lifespan(_app):
    store.initialize()
    yield


app = FastAPI(
    title="Clicky Recurring Runs",
    description="A local demo API for explicit recurring agent work with idempotent run creation.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz", tags=["system"])
def health() -> dict:
    return {"status": "ok"}


@app.post("/schedules", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
def create_schedule(payload: ScheduleCreate) -> ScheduleRead:
    now = datetime.now(timezone.utc)
    try:
        return store.create_schedule(payload, now)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.get("/schedules", response_model=List[ScheduleRead])
def list_schedules() -> List[ScheduleRead]:
    return store.list_schedules()


@app.post("/schedules/{schedule_id}/pause", response_model=ScheduleRead)
def pause_schedule(schedule_id: str) -> ScheduleRead:
    updated = store.change_schedule(schedule_id, enabled=False, now=datetime.now(timezone.utc))
    if updated is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return updated


@app.post("/schedules/{schedule_id}/resume", response_model=ScheduleRead)
def resume_schedule(schedule_id: str) -> ScheduleRead:
    updated = store.change_schedule(schedule_id, enabled=True, now=datetime.now(timezone.utc))
    if updated is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return updated


@app.post("/scheduler/tick", response_model=TickResponse)
def scheduler_tick(payload: TickRequest = TickRequest()) -> TickResponse:
    at = payload.at or datetime.now(timezone.utc)
    try:
        created = store.enqueue_due(at)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"evaluated_at": at, "created": created, "count": len(created)}


@app.get("/runs", response_model=List[RunRead])
def list_runs(
    schedule_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> List[RunRead]:
    if schedule_id and store.get_schedule(schedule_id) is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return store.list_runs(schedule_id=schedule_id, limit=limit)
