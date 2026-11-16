import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, TimeoutError as DatabaseTimeout
from sqlalchemy.orm import Session

from labreserve_messaging.events import EventData, make_event
from labreserve_messaging.storage import enqueue
from labreserve_observability.database import DatabaseCollector
from labreserve_observability.http import install_metrics
from labreserve_auth import Principal, own_record, own_user, require_user
from .database import SessionLocal, get_session
from .metrics import business_metrics
from .models import ACTIVE, Outbox, WaitingEntry, messaging_tables
from .saga import dispatch, entry_data, lock_slot
from .schemas import WaitingItem

app = FastAPI(title="LabReserve - Waiting List Service", version="development")
DbSession = Annotated[Session, Depends(get_session)]
User = Annotated[Principal, Depends(require_user)]
install_metrics(app, "waiting-list", DatabaseCollector("waiting-list", SessionLocal, messaging_tables, business_metrics))


@app.exception_handler(OperationalError)
@app.exception_handler(DatabaseTimeout)
async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).warning("Database non disponibile: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database temporaneamente non disponibile"})


@app.get("/health", tags=["Sistema"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "waiting-list"}


@app.get("/ready", tags=["Sistema"])
def ready(session: DbSession) -> dict[str, str]:
    session.execute(select(1))
    return {"status": "ready", "database": "available"}


def ranked_query():
    positions = select(WaitingEntry.booking_id, func.row_number().over(
        partition_by=WaitingEntry.slot_id, order_by=WaitingEntry.queue_ticket).label("position")
    ).where(WaitingEntry.status.in_(ACTIVE)).subquery()
    return select(WaitingEntry, positions.c.position).outerjoin(positions, positions.c.booking_id == WaitingEntry.booking_id)


@app.get("/waiting-list", response_model=list[WaitingItem], tags=["Lista d'attesa"])
def list_entries(session: DbSession, principal: User, user_id: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    include_history: bool = False, limit: Annotated[int, Query(ge=1, le=200)] = 100):
    user = own_user(principal, user_id)
    query = ranked_query().where(WaitingEntry.user_id == user, WaitingEntry.queue_ticket.is_not(None))
    if not include_history:
        query = query.where(WaitingEntry.status.in_((*ACTIVE, "WITHDRAWING")))
    rows = session.execute(query.order_by(WaitingEntry.enqueued_at, WaitingEntry.booking_id).limit(limit)).all()
    return [WaitingItem.model_validate(entry).model_copy(update={"position": position}) for entry, position in rows]


@app.get("/waiting-list/{entry_id}", response_model=WaitingItem, tags=["Lista d'attesa"])
def get_entry(entry_id: UUID, session: DbSession, principal: User):
    row = session.execute(ranked_query().where(WaitingEntry.booking_id == entry_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Voce della lista non trovata")
    own_record(principal, row[0], "Voce della lista non trovata")
    return WaitingItem.model_validate(row[0]).model_copy(update={"position": row[1]})


@app.delete("/waiting-list/{entry_id}", response_model=WaitingItem, status_code=202, tags=["Lista d'attesa"])
def withdraw_entry(entry_id: UUID, response: Response, session: DbSession, principal: User):
    entry = own_record(principal, session.get(WaitingEntry, entry_id), "Voce della lista non trovata")
    state = lock_slot(session, entry.slot_id)
    entry = session.scalar(select(WaitingEntry).where(WaitingEntry.booking_id == entry_id)
        .with_for_update().execution_options(populate_existing=True))
    if entry.status in {"CONFIRMED", "REJECTED"}:
        raise HTTPException(status_code=409, detail="La prenotazione ha gia un esito; usare le API Booking")
    if entry.status == "WITHDRAWN":
        response.status_code = 200
    elif entry.status != "WITHDRAWING":
        entry.status = "WITHDRAWING"
        payload = EventData.model_validate(entry_data(entry, state, "USER_CANCELLED"))
        enqueue(session, Outbox, make_event("waiting.withdraw_requested", "waiting-list", payload))
        if state.inflight_booking_id == entry.booking_id:
            state.inflight_booking_id = None
        dispatch(session, state, payload)
    session.commit()
    return WaitingItem.model_validate(entry)
