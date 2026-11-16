from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert

from labreserve_messaging.events import Event
from labreserve_messaging.runtime import PermanentEventError
from .models import NotificationRecord

MESSAGES = {
    "booking.confirmed": "Prenotazione confermata",
    "booking.waitlisted": "Sei in lista d'attesa",
    "booking.cancelled": "Prenotazione annullata",
    "booking.rejected": "Prenotazione non accettata",
}
REASONS = {
    "TIMEOUT": "tempo di elaborazione scaduto", "SLOT_STARTED": "fascia gia iniziata",
    "SLOT_NOT_FOUND": "fascia inesistente",
    "LAB_REMOVED": "laboratorio rimosso dall'amministratore",
}


def handle_event(session, event: Event) -> None:
    if event.producer != "booking":
        raise PermanentEventError("Notification accetta solo eventi Booking")
    if event.event_type not in MESSAGES:
        return
    message = MESSAGES[event.event_type] + f" per la fascia {event.data.slot_id}."
    if event.data.reason in REASONS:
        message += " Motivo: " + REASONS[event.data.reason] + "."
    session.execute(insert(NotificationRecord).values(
        id=uuid4(), booking_id=event.data.booking_id, user_id=event.data.user_id, slot_id=event.data.slot_id,
        event_type=event.event_type, message=message, source_event_id=event.event_id, occurred_at=event.occurred_at,
    ).on_conflict_do_nothing(constraint="uq_notification_booking_type"))
