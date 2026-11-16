from sqlalchemy import case, func, select

from labreserve_observability.database import gauge
from .models import NotificationRecord


def business_metrics(session, now):
    status = case((NotificationRecord.read_at.is_(None), "unread"), else_="read")
    counts = dict(session.execute(select(status, func.count()).where(NotificationRecord.deleted_at.is_(None)).group_by(status)).all())
    yield gauge("labreserve_notifications", "Notifiche persistite per stato di lettura", "notification",
        [((value,), counts.get(value, 0)) for value in ["unread", "read"]], ["read_status"])
