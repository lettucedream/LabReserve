from sqlalchemy import and_, func, select

from labreserve_observability.database import gauge
from .models import LabRecord, TimeSlotRecord


def business_metrics(session, now):
    
    
    rows = session.execute(select(LabRecord.id,
        func.coalesce(func.sum(TimeSlotRecord.capacity), 0),
        func.coalesce(func.sum(TimeSlotRecord.allocated_seats), 0),
        func.count(TimeSlotRecord.id))
        .outerjoin(TimeSlotRecord, and_(TimeSlotRecord.lab_id == LabRecord.id, TimeSlotRecord.ends_at > now))
        .where(LabRecord.deleted_at.is_(None))
        .group_by(LabRecord.id)).all()
    for name, help_text, index in [
        ("labreserve_seats_capacity", "Capienza complessiva delle fasce non terminate per laboratorio", 1),
        ("labreserve_seats_allocated", "Posti assegnati sulle fasce non terminate per laboratorio", 2),
        ("labreserve_slots", "Numero di fasce non terminate per laboratorio", 3),
    ]:
        yield gauge(name, help_text, "availability", [((row[0],), row[index]) for row in rows], ["lab_id"])
