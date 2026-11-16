from datetime import UTC, datetime
from datetime import timedelta
import os

from sqlalchemy import select

from labreserve_messaging.events import Event, make_event
from labreserve_messaging.runtime import PermanentEventError
from labreserve_messaging.storage import enqueue

from .database import SessionLocal
from .models import BookingRecord, Outbox


def event_data(booking: BookingRecord) -> dict:
    return {"booking_id": booking.id, "user_id": booking.user_id, "slot_id": booking.slot_id,
        "attempt": booking.attempt, "reason": booking.reason,
        "queue_ticket": booking.queue_ticket, "promotion_id": booking.promotion_id}


def emit(session, booking: BookingRecord, event_type: str, cause=None) -> None:
    enqueue(session, Outbox, make_event(event_type, "booking", event_data(booking), cause))


def request_cancellation(session, booking: BookingRecord, reason: str, cause=None) -> bool:
    if booking.status in {"CANCELLED", "CANCELLING"}:
        return False
    booking.status = "CANCELLING"
    booking.reason = reason
    emit(session, booking, "seat.release", cause)
    emit(session, booking, "waiting.withdraw", cause)
    return True


def handle_event(session, event: Event) -> None:
    if event.producer == "waiting-list" and event.event_type in {"waiting.promote", "waiting.withdraw_requested"}:
        handle_waiting_command(session, event)
        return
    if event.producer != "availability" or event.event_type not in {"seat.reserved", "seat.rejected", "seat.released", "seat.revoked"}:
        raise PermanentEventError("Booking accetta solo esiti Availability")
    booking = session.get(BookingRecord, event.data.booking_id, with_for_update=True)
    if booking is None:
        raise PermanentEventError("Prenotazione inesistente")
    if booking.user_id != event.data.user_id or booking.slot_id != event.data.slot_id:
        raise PermanentEventError("Esito non coerente con la prenotazione")
    if event.event_type == "seat.revoked":
        if event.data.reason != "LAB_REMOVED":
            raise PermanentEventError("Revoca priva di motivazione valida")
        if booking.status in {"PENDING", "CONFIRMED", "WAITLISTED"}:
            request_cancellation(session, booking, "LAB_REMOVED", event.event_id)
        return
    if event.data.queue_ticket is not None:
        if booking.queue_ticket is not None and booking.queue_ticket != event.data.queue_ticket:
            raise PermanentEventError("Ticket non coerente con la prenotazione")
        booking.queue_ticket = event.data.queue_ticket
    if event.event_type == "seat.released":
        if booking.status == "CANCELLING":
            booking.status = "CANCELLED"
            emit(session, booking, "booking.cancelled", event.event_id)
        return
    if booking.status != "PENDING" or event.data.attempt != booking.attempt:
        return
    if booking.deadline_at <= datetime.now(UTC):
        request_cancellation(session, booking, "TIMEOUT", event.event_id)
        return
    if event.event_type == "seat.reserved":
        booking.status = "CONFIRMED"
        booking.reason = None
        emit(session, booking, "booking.confirmed", event.event_id)
    else:
        if not event.data.reason:
            raise PermanentEventError("Rifiuto privo di motivazione")
        booking.reason = event.data.reason
        booking.status = "WAITLISTED" if event.data.reason in {"FULL", "QUEUED"} else "REJECTED"
        emit(session, booking, "booking.waitlisted" if booking.status == "WAITLISTED" else "booking.rejected", event.event_id)


def handle_waiting_command(session, event: Event) -> None:
    booking = session.get(BookingRecord, event.data.booking_id, with_for_update=True)
    if booking is None or booking.user_id != event.data.user_id or booking.slot_id != event.data.slot_id:
        raise PermanentEventError("Comando della lista non coerente con la prenotazione")
    if event.event_type == "waiting.withdraw_requested":
        request_cancellation(session, booking, "USER_CANCELLED", event.event_id)
        return
    data = event.data
    if data.promotion_id is None or data.queue_ticket is None or data.attempt <= 1:
        raise PermanentEventError("Promozione priva di token, ticket o tentativo valido")
    if booking.status in {"CANCELLING", "CANCELLED", "REJECTED", "CONFIRMED"}:
        skipped = data.model_copy(update={"reason": booking.status})
        enqueue(session, Outbox, make_event("booking.promotion_skipped", "booking", skipped, event.event_id))
        return
    if booking.status == "PENDING" and booking.deadline_at <= datetime.now(UTC):
        request_cancellation(session, booking, "TIMEOUT", event.event_id)
        skipped = data.model_copy(update={"reason": "CANCELLING"})
        enqueue(session, Outbox, make_event("booking.promotion_skipped", "booking", skipped, event.event_id))
        return
    if data.attempt <= booking.attempt:
        return
    if booking.queue_ticket is not None and booking.queue_ticket != data.queue_ticket:
        raise PermanentEventError("Ticket della promozione non coerente")
    booking.queue_ticket = data.queue_ticket
    booking.promotion_id = data.promotion_id
    booking.attempt = data.attempt
    booking.status = "PENDING"
    booking.reason = None
    booking.deadline_at = datetime.now(UTC) + timedelta(seconds=int(os.environ.get("BOOKING_TIMEOUT_SECONDS", "60")))
    emit(session, booking, "seat.reserve", event.event_id)


def expire_pending() -> None:
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        bookings = session.scalars(select(BookingRecord)
            .where(BookingRecord.status == "PENDING", BookingRecord.deadline_at <= now)
            .order_by(BookingRecord.deadline_at).limit(20).with_for_update(skip_locked=True)).all()
        for booking in bookings:
            request_cancellation(session, booking, "TIMEOUT")
