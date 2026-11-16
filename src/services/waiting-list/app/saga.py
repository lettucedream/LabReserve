from uuid import uuid4

from sqlalchemy import select, text

from labreserve_messaging.events import Event, EventData, make_event
from labreserve_messaging.runtime import PermanentEventError
from labreserve_messaging.storage import enqueue

from .models import ACTIVE, Outbox, SlotQueue, WaitingEntry


def lock_slot(session, slot_id: int) -> SlotQueue:
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "waiting:" + str(slot_id)})
    state = session.get(SlotQueue, slot_id)
    if state is None:
        state = SlotQueue(slot_id=slot_id)
        session.add(state)
        session.flush()
    return state


def entry_data(entry: WaitingEntry, state: SlotQueue, reason=None) -> dict:
    return {"booking_id": entry.booking_id, "user_id": entry.user_id, "slot_id": entry.slot_id,
        "attempt": entry.attempt, "queue_ticket": entry.queue_ticket, "promotion_id": entry.promotion_id,
        "queue_generation": state.generation, "capacity_version": state.capacity_version, "reason": reason}


def dispatch(session, state: SlotQueue, reference: EventData, cause=None) -> None:
    session.flush()
    if state.inflight_booking_id is not None:
        return
    head = session.scalar(select(WaitingEntry).where(WaitingEntry.slot_id == state.slot_id,
        WaitingEntry.status == "WAITING").order_by(WaitingEntry.queue_ticket).limit(1))
    if head is None:
        if state.generation > state.last_drain_generation:
            payload = reference.model_copy(update={"queue_generation": state.generation, "capacity_version": state.capacity_version})
            enqueue(session, Outbox, make_event("queue.drain", "waiting-list", payload, cause))
            state.last_drain_generation = state.generation
        return
    if head.last_failed_capacity_version is not None and state.capacity_version <= head.last_failed_capacity_version:
        return
    head.status = "OFFERING"
    head.attempt += 1
    head.promotion_id = uuid4()
    state.inflight_booking_id = head.booking_id
    enqueue(session, Outbox, make_event("waiting.promote", "waiting-list", entry_data(head, state), cause))


def get_entry(session, data: EventData) -> WaitingEntry | None:
    entry = session.get(WaitingEntry, data.booking_id)
    if entry is not None and (entry.slot_id != data.slot_id or entry.user_id != data.user_id):
        raise PermanentEventError("Identita della voce in lista non coerente")
    return entry


def withdraw(session, state, data, cause=None, final=False) -> WaitingEntry:
    entry = get_entry(session, data)
    if entry is None:
        entry = WaitingEntry(booking_id=data.booking_id, slot_id=data.slot_id, user_id=data.user_id,
            queue_ticket=data.queue_ticket, attempt=data.attempt, status="WITHDRAWN" if final else "WITHDRAWING")
        session.add(entry)
    elif entry.status != "WITHDRAWN":
        entry.status = "WITHDRAWN" if final else "WITHDRAWING"
    if state.inflight_booking_id == entry.booking_id:
        state.inflight_booking_id = None
    dispatch(session, state, data, cause)
    return entry


def handle_event(session, event: Event) -> None:
    data = event.data
    if event.producer == "availability" and event.event_type == "seat.revoked":
        
        return
    if event.producer == "availability" and event.event_type in {"seat.reserved", "seat.rejected", "seat.released"}:
        state = lock_slot(session, data.slot_id)
        
        state.generation = max(state.generation, data.queue_generation)
        state.capacity_version = max(state.capacity_version, data.capacity_version)
        if event.event_type == "seat.rejected" and data.reason in {"FULL", "QUEUED"} and data.queue_ticket is not None:
            entry = get_entry(session, data)
            if entry is None:
                entry = WaitingEntry(booking_id=data.booking_id, slot_id=data.slot_id, user_id=data.user_id,
                    queue_ticket=data.queue_ticket, attempt=data.attempt, status="WAITING",
                    last_failed_capacity_version=data.capacity_version if data.reason == "FULL" else None)
                session.add(entry)
            else:
                if entry.queue_ticket is None:
                    entry.queue_ticket = data.queue_ticket
                elif entry.queue_ticket != data.queue_ticket:
                    raise PermanentEventError("Ticket non coerente con la voce in lista")
                if entry.status in ACTIVE and data.attempt >= entry.attempt:
                    entry.status = "WAITING"
                    entry.attempt = data.attempt
                    entry.last_failed_capacity_version = data.capacity_version if data.reason == "FULL" else None
                    if state.inflight_booking_id == entry.booking_id:
                        state.inflight_booking_id = None
        dispatch(session, state, data, event.event_id)
        return

    if event.producer == "booking" and event.event_type == "waiting.withdraw":
        state = lock_slot(session, data.slot_id)
        withdraw(session, state, data, event.event_id)
        return

    if event.producer == "booking" and event.event_type in {"booking.confirmed", "booking.cancelled", "booking.rejected", "booking.promotion_skipped"}:
        state = lock_slot(session, data.slot_id)
        entry = get_entry(session, data)
        if event.event_type == "booking.cancelled":
            withdraw(session, state, data, event.event_id, final=True)
            return
        if entry is None:
            return
        if event.event_type == "booking.promotion_skipped":
            if data.attempt != entry.attempt or data.promotion_id != entry.promotion_id:
                return
            if data.reason == "CONFIRMED" and entry.status in ACTIVE:
                entry.status = "CONFIRMED"
            elif data.reason == "REJECTED" and entry.status in ACTIVE:
                entry.status = "REJECTED"
            elif entry.status != "WITHDRAWN":
                entry.status = "WITHDRAWN" if data.reason == "CANCELLED" else "WITHDRAWING"
        elif event.event_type == "booking.confirmed":
            if entry.status in ACTIVE and data.attempt >= entry.attempt:
                entry.status = "CONFIRMED"
        elif entry.status in ACTIVE:
            entry.status = "REJECTED"
        if state.inflight_booking_id == entry.booking_id and entry.status != "OFFERING":
            state.inflight_booking_id = None
        dispatch(session, state, data, event.event_id)
        return
    
    if event.producer == "booking" and event.event_type == "booking.waitlisted":
        return
    raise PermanentEventError("Evento non previsto per Waiting List")
