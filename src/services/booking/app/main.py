import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError, TimeoutError as DatabaseTimeout
from sqlalchemy.orm import Session

from labreserve_observability.database import DatabaseCollector
from labreserve_observability.http import install_metrics
from labreserve_auth import Principal, own_record, own_user, require_admin, require_user
from .database import SessionLocal, get_session
from .metrics import business_metrics
from .models import BlockedUser, BookingRecord, messaging_tables
from .saga import emit, request_cancellation
from .schemas import Booking, BookingCreate, UserDeactivation

app = FastAPI(title="LabReserve - Booking Service", version="development",
    description="Prenotazioni asincrone con Kafka e Saga coordinata da Booking.")
DbSession = Annotated[Session, Depends(get_session)]
User = Annotated[Principal, Depends(require_user)]
Admin = Annotated[Principal, Depends(require_admin)]
install_metrics(app, "booking", DatabaseCollector("booking", SessionLocal, messaging_tables, business_metrics))
TIMEOUT_SECONDS = int(os.environ.get("BOOKING_TIMEOUT_SECONDS", "60"))
if not 5 <= TIMEOUT_SECONDS <= 300:
    raise ValueError("BOOKING_TIMEOUT_SECONDS deve essere compreso tra 5 e 300")


@app.exception_handler(OperationalError)
@app.exception_handler(DatabaseTimeout)
async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).warning("Database non disponibile: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database temporaneamente non disponibile"})


@app.get("/health", tags=["Sistema"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "booking"}


@app.get("/ready", tags=["Sistema"])
def ready(session: DbSession) -> dict[str, str]:
    session.execute(select(1))
    return {"status": "ready", "database": "available"}


@app.post("/bookings", response_model=Booking, status_code=202, tags=["Prenotazioni"],
    responses={200: {"description": "Richiesta gia elaborata"}, 409: {"description": "Chiave riutilizzata o prenotazione attiva gia presente"}})
def create_booking(payload: BookingCreate, response: Response, session: DbSession, principal: User,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> BookingRecord:
    key = idempotency_key.strip()
    user_id = own_user(principal, payload.user_id)
    if not key:
        raise HTTPException(status_code=422, detail="Idempotency-Key non puo essere vuota")
    lock_user(session, user_id)
    if session.get(BlockedUser, user_id) is not None:
        raise HTTPException(403, "Questo account è stato eliminato.")
    identifier = uuid4()
    inserted = session.scalar(insert(BookingRecord).values(
        id=identifier, user_id=user_id, slot_id=payload.slot_id, idempotency_key=key,
        status="PENDING", attempt=1, deadline_at=datetime.now(UTC) + timedelta(seconds=TIMEOUT_SECONDS),
    ).on_conflict_do_nothing().returning(BookingRecord.id))
    if inserted is None:
        existing = session.scalar(select(BookingRecord).where(BookingRecord.user_id == user_id,
            BookingRecord.idempotency_key == key))
        if existing is None:
            raise HTTPException(status_code=409, detail="Prenotazione attiva gia presente per utente e fascia")
        if existing.slot_id != payload.slot_id:
            raise HTTPException(status_code=409, detail="Idempotency-Key gia usata con dati diversi")
        response.status_code = 202 if existing.status in {"PENDING", "CANCELLING"} else 200
        response.headers["Location"] = f"/bookings/{existing.id}"
        return existing
    booking = session.get(BookingRecord, identifier)
    emit(session, booking, "seat.reserve")
    session.commit()
    response.headers["Location"] = f"/bookings/{booking.id}"
    return booking


@app.get("/bookings", response_model=list[Booking], tags=["Prenotazioni"])
def list_bookings(session: DbSession, principal: User, user_id: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100) -> list[BookingRecord]:
    user = own_user(principal, user_id)
    return list(session.scalars(select(BookingRecord).where(BookingRecord.user_id == user)
        .order_by(BookingRecord.created_at.desc()).limit(limit)).all())


@app.get("/bookings/{booking_id}", response_model=Booking, tags=["Prenotazioni"])
def get_booking(booking_id: UUID, session: DbSession, principal: User) -> BookingRecord:
    booking = own_record(principal, session.get(BookingRecord, booking_id), "Prenotazione non trovata")
    return booking


@app.delete("/bookings/{booking_id}", response_model=Booking, status_code=202, tags=["Prenotazioni"])
def cancel_booking(booking_id: UUID, response: Response, session: DbSession, principal: User) -> BookingRecord:
    booking = own_record(principal, session.get(BookingRecord, booking_id, with_for_update=True), "Prenotazione non trovata")
    request_cancellation(session, booking, "USER_CANCELLED")
    if booking.status == "CANCELLED":
        response.status_code = 200
    session.commit()
    return booking


def lock_user(session, user_id):
    
    
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:user_id, 217))"), {"user_id": user_id})


@app.post("/admin/deactivate-user", tags=["Amministrazione"])
def deactivate_user(payload: UserDeactivation, session: DbSession, admin: Admin):
    if payload.user_id == admin.user_id:
        raise HTTPException(403, "L'account amministratore non può essere eliminato.")
    lock_user(session, payload.user_id)
    session.execute(insert(BlockedUser).values(user_id=payload.user_id).on_conflict_do_nothing())
    bookings = session.scalars(select(BookingRecord).where(BookingRecord.user_id == payload.user_id,
        BookingRecord.status.in_(["PENDING", "CONFIRMED", "WAITLISTED", "CANCELLING"]))
        .order_by(BookingRecord.id).with_for_update()).all()
    for booking in bookings:
        request_cancellation(session, booking, "ACCOUNT_DELETED")
    session.commit()
    return {"cancellations": len(bookings)}
