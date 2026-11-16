from labreserve_messaging.events import AVAILABILITY_EVENTS, BOOKING_COMMANDS
from labreserve_messaging.runtime import run_worker

from .database import SessionLocal, engine
from .models import messaging_tables
from .saga import expire_pending, handle_event


if __name__ == "__main__":
    try:
        run_worker("booking", SessionLocal, messaging_tables, [AVAILABILITY_EVENTS, BOOKING_COMMANDS], handle_event, expire_pending)
    finally:
        engine.dispose()
