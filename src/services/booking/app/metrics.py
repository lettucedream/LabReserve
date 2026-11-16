from sqlalchemy import func, select

from labreserve_observability.database import age_seconds, gauge, scalar_gauge
from .models import BookingRecord


def business_metrics(session, now):
    counts = dict(session.execute(select(BookingRecord.status, func.count()).group_by(BookingRecord.status)).all())
    yield gauge("labreserve_bookings", "Prenotazioni persistite per stato corrente", "booking",
        [((status,), counts.get(status, 0)) for status in ["PENDING", "CONFIRMED", "WAITLISTED", "CANCELLING", "CANCELLED", "REJECTED"]], ["status"])
    oldest = session.scalar(select(func.min(BookingRecord.created_at)).where(BookingRecord.status.in_(["PENDING", "CANCELLING"])))
    yield scalar_gauge("labreserve_booking_oldest_processing_age_seconds", "Eta della richiesta in elaborazione piu vecchia", "booking", age_seconds(oldest, now))
