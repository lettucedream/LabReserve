from sqlalchemy import func, select

from labreserve_observability.database import gauge
from .models import WaitingEntry


def business_metrics(session, now):
    counts = dict(session.execute(select(WaitingEntry.status, func.count()).group_by(WaitingEntry.status)).all())
    yield gauge("labreserve_waiting_entries", "Voci persistite della lista per stato corrente", "waiting-list",
        [((status,), counts.get(status, 0)) for status in ["WAITING", "OFFERING", "WITHDRAWING", "WITHDRAWN", "CONFIRMED", "REJECTED"]], ["status"])
