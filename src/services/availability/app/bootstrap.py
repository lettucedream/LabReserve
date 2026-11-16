from datetime import UTC, datetime, time, timedelta

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from .database import SessionLocal, engine
from .models import LabRecord, TimeSlotRecord
from .accounts import seed_accounts


def seed_demo_data() -> bool:
    with SessionLocal.begin() as session:
        
        session.execute(text("SELECT pg_advisory_xact_lock(28110401)"))
        if session.scalar(select(LabRecord.id).limit(1)) is not None:
            return False

        tomorrow = datetime.now(UTC).date() + timedelta(days=1)
        first_start = datetime.combine(tomorrow, time(hour=9), tzinfo=UTC)
        for name, capacity in [("Laboratorio Informatica", 2), ("Laboratorio Reti", 4)]:
            lab = LabRecord(name=name, capacity=capacity)
            session.add(lab)
            session.flush()
            for index in range(2):
                starts_at = first_start + timedelta(hours=index * 2)
                session.add(
                    TimeSlotRecord(
                        lab_id=lab.id,
                        starts_at=starts_at,
                        ends_at=starts_at + timedelta(hours=2),
                        capacity=lab.capacity,
                    )
                )
    return True


def main() -> None:
    try:
        command.upgrade(Config("alembic.ini"), "head")
        seed_accounts()
        inserted = seed_demo_data()
        print("Migrazioni completate. " + ("Dati iniziali inseriti." if inserted else "Dati esistenti conservati."))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
