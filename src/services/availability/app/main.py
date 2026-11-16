import logging
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError, TimeoutError as DatabaseTimeout
from sqlalchemy.orm import Session

from labreserve_observability.database import DatabaseCollector
from labreserve_observability.http import install_metrics
from labreserve_auth import Principal, require_admin
from labreserve_messaging.events import make_event
from labreserve_messaging.storage import enqueue
from .accounts import resolve_session
from .auth import router as auth_router
from .database import SessionLocal, get_session
from .metrics import business_metrics
from .models import AllocationRecord, LabRecord, Outbox, TimeSlotRecord, messaging_tables
from .schemas import Lab, LabCreate, TimeSlot, TimeSlotCreate
from .weather import WeatherResponse, WeatherService


app = FastAPI(
    title="LabReserve - Availability Service",
    description="Laboratori e fasce orarie persistenti in PostgreSQL.",
    version="development",
)
DbSession = Annotated[Session, Depends(get_session)]
Admin = Annotated[Principal, Depends(require_admin)]
app.state.resolve_auth_session = resolve_session
app.include_router(auth_router)
install_metrics(app, "availability", DatabaseCollector("availability", SessionLocal, messaging_tables, business_metrics))
weather_service = WeatherService(registry=app.state.metrics_registry)
logger = logging.getLogger(__name__)


@app.exception_handler(OperationalError)
@app.exception_handler(DatabaseTimeout)
async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("Database non disponibile: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database temporaneamente non disponibile"})


@app.get("/health", tags=["Sistema"])
def health() -> dict[str, str]:
    
    return {"status": "ok", "service": "availability", "mode": "postgresql"}


@app.get("/ready", tags=["Sistema"])
def ready(session: DbSession) -> dict[str, str]:
    
    session.execute(select(1))
    return {"status": "ready", "database": "available"}


@app.get("/labs", response_model=list[Lab], tags=["Laboratori"])
def list_labs(session: DbSession, include_removed: bool = False) -> list[LabRecord]:
    
    query = select(LabRecord).order_by(LabRecord.id)
    if not include_removed:
        query = query.where(LabRecord.deleted_at.is_(None))
    return list(session.scalars(query).all())


@app.get("/weather", response_model=WeatherResponse, tags=["Campus"],
         responses={503: {"model": WeatherResponse, "description": "Provider non disponibile e cache assente o scaduta"}})
def campus_weather(response: Response, day: Annotated[date | None, Query(alias="date")] = None) -> WeatherResponse:
    
    result = weather_service.get(day)
    response.headers["Cache-Control"] = "no-store"
    if result.status == "unavailable":
        response.status_code = 503
        response.headers["Retry-After"] = str(result.retry_after_seconds)
    return result


@app.post(
    "/labs",
    response_model=Lab,
    status_code=201,
    responses={409: {"description": "Nome del laboratorio gia utilizzato"}},
    tags=["Laboratori"],
)
def create_lab(payload: LabCreate, session: DbSession, admin: Admin) -> LabRecord:
    
    lab = LabRecord(**payload.model_dump())
    session.add(lab)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "uq_labs_name":
            raise HTTPException(status_code=409, detail="Nome del laboratorio gia utilizzato") from exc
        raise
    return lab


@app.delete("/labs/{lab_id}", status_code=204, tags=["Laboratori"],
            responses={404: {"description": "Laboratorio inesistente"}})
def delete_lab(lab_id: int, session: DbSession, admin: Admin) -> Response:
    
    lab = session.get(LabRecord, lab_id, with_for_update=True)
    if lab is None:
        raise HTTPException(status_code=404, detail="Laboratorio non trovato")
    if lab.deleted_at is None:
        
        
        slots = session.scalars(select(TimeSlotRecord).where(TimeSlotRecord.lab_id == lab_id)
                                .order_by(TimeSlotRecord.id).with_for_update()).all()
        lab.deleted_at = datetime.now(UTC)
        allocations = session.scalars(select(AllocationRecord).where(
            AllocationRecord.slot_id.in_([slot.id for slot in slots]),
            (AllocationRecord.status == "ALLOCATED") |
            ((AllocationRecord.status == "REJECTED") & AllocationRecord.reason.in_(["FULL", "QUEUED"]))
        ).order_by(AllocationRecord.booking_id)).all()
        for allocation in allocations:
            enqueue(session, Outbox, make_event("seat.revoked", "availability", {
                "booking_id": allocation.booking_id, "user_id": allocation.user_id,
                "slot_id": allocation.slot_id, "attempt": allocation.attempt,
                "queue_ticket": allocation.queue_ticket, "reason": "LAB_REMOVED",
            }))
        session.commit()
    return Response(status_code=204)


@app.get(
    "/labs/{lab_id}/slots",
    response_model=list[TimeSlot],
    responses={404: {"description": "Laboratorio inesistente"}},
    tags=["Disponibilita"],
)
def list_slots(lab_id: int, session: DbSession, include_removed: bool = False) -> list[TimeSlotRecord]:
    
    lab = session.get(LabRecord, lab_id)
    if lab is None or (lab.deleted_at is not None and not include_removed):
        raise HTTPException(status_code=404, detail="Laboratorio non trovato")

    query = select(TimeSlotRecord).where(TimeSlotRecord.lab_id == lab_id).order_by(TimeSlotRecord.starts_at)
    return list(session.scalars(query).all())


@app.post(
    "/labs/{lab_id}/slots",
    response_model=TimeSlot,
    status_code=201,
    responses={
        404: {"description": "Laboratorio inesistente"},
        409: {"description": "Fascia sovrapposta a una gia presente"},
    },
    tags=["Disponibilita"],
)
def create_slot(lab_id: int, payload: TimeSlotCreate, session: DbSession, admin: Admin) -> TimeSlotRecord:
    
    lab = session.get(LabRecord, lab_id, with_for_update=True)
    if lab is None or lab.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Laboratorio non trovato")

    slot = TimeSlotRecord(lab_id=lab_id, capacity=lab.capacity, **payload.model_dump())
    session.add(slot)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "ex_slots_no_overlap":
            raise HTTPException(status_code=409, detail="La fascia si sovrappone a una gia presente") from exc
        raise
    return slot
