from datetime import UTC, datetime

from sqlalchemy import text

from labreserve_messaging.events import Event, make_event
from labreserve_messaging.runtime import PermanentEventError
from labreserve_messaging.storage import enqueue

from .models import AllocationRecord, LabRecord, Outbox, TimeSlotRecord


def reply(session, event: Event, event_type: str, reason: str | None = None, allocation=None) -> None:
    slot = session.get(TimeSlotRecord, event.data.slot_id)
    data = event.data.model_copy(update={
        "reason": reason, "queue_ticket": allocation.queue_ticket if allocation else None,
        "queue_generation": slot.queue_generation if slot else 0,
        "capacity_version": slot.capacity_version if slot else 0,
    })
    enqueue(session, Outbox, make_event(event_type, "availability", data, event.event_id))


def handle_event(session, event: Event) -> None:
    if event.producer == "waiting-list" and event.event_type == "queue.drain":
        slot = session.get(TimeSlotRecord, event.data.slot_id, with_for_update=True)
        if slot is not None and event.data.queue_generation == slot.queue_generation:
            slot.drained_generation = event.data.queue_generation
        return
    if event.producer != "booking" or event.event_type not in {"seat.reserve", "seat.release"}:
        raise PermanentEventError("Availability accetta solo comandi Booking")
    data = event.data
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": str(data.booking_id)})
    allocation = session.get(AllocationRecord, data.booking_id)
    if allocation is not None and (allocation.slot_id != data.slot_id or allocation.user_id != data.user_id):
        raise PermanentEventError("Dati diversi per la stessa prenotazione")

    if event.event_type == "seat.release":
        if allocation is None:
            allocation = AllocationRecord(booking_id=data.booking_id, slot_id=data.slot_id,
                user_id=data.user_id, attempt=data.attempt, status="RELEASED", reason=data.reason)
            session.add(allocation)
        else:
            if allocation.status == "ALLOCATED":
                slot = session.get(TimeSlotRecord, data.slot_id, with_for_update=True)
                if slot is None or slot.allocated_seats <= 0:
                    raise RuntimeError("Allocazione senza contatore coerente")
                slot.allocated_seats -= 1
                slot.capacity_version += 1
            allocation.status = "RELEASED"
            allocation.attempt = max(allocation.attempt, data.attempt)
            allocation.reason = data.reason
        reply(session, event, "seat.released", data.reason, allocation)
        return

    if allocation is not None and allocation.status == "RELEASED":
        reply(session, event, "seat.rejected", "CANCELLED", allocation)
        return

    slot = session.get(TimeSlotRecord, data.slot_id, with_for_update=True)
    if slot is not None and session.get(LabRecord, slot.lab_id).deleted_at is not None:
        if allocation is None:
            allocation = AllocationRecord(booking_id=data.booking_id, slot_id=data.slot_id,
                user_id=data.user_id, attempt=data.attempt, status="REJECTED", reason="LAB_REMOVED")
            session.add(allocation)
        
        
        reply(session, event, "seat.revoked", "LAB_REMOVED", allocation)
        return

    if allocation is not None:
        if allocation.status == "ALLOCATED":
            allocation.attempt = max(allocation.attempt, data.attempt)
            reply(session, event, "seat.reserved", allocation=allocation)
            return
        if data.attempt <= allocation.attempt:
            reply(session, event, "seat.rejected", allocation.reason, allocation)
            return

    is_promotion = data.promotion_id is not None and data.queue_ticket is not None and data.attempt > 1
    if data.attempt > 1 and not is_promotion:
        raise PermanentEventError("Un nuovo tentativo richiede una promozione della lista")
    if is_promotion and allocation is not None and allocation.queue_ticket != data.queue_ticket:
        raise PermanentEventError("Ticket diverso dall'assegnazione originaria")

    reason = None
    if slot is None:
        reason = "SLOT_NOT_FOUND"
    elif slot.starts_at <= datetime.now(UTC):
        reason = "SLOT_STARTED"
    elif slot.waiting_list_active and not is_promotion:
        reason = "QUEUED"
    elif slot.allocated_seats >= slot.capacity:
        reason = "FULL"
    else:
        slot.allocated_seats += 1

    if allocation is None:
        allocation = AllocationRecord(booking_id=data.booking_id, slot_id=data.slot_id, user_id=data.user_id)
        session.add(allocation)
        allocation.queue_ticket = data.queue_ticket if is_promotion else None
    if reason in {"FULL", "QUEUED"} and allocation.queue_ticket is None:
        slot.queue_generation += 1
        allocation.queue_ticket = slot.queue_generation
    allocation.attempt = data.attempt
    allocation.status = "REJECTED" if reason else "ALLOCATED"
    allocation.reason = reason
    reply(session, event, "seat.rejected" if reason else "seat.reserved", reason, allocation)
