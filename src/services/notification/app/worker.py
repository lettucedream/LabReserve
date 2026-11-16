from labreserve_messaging.events import BOOKING_EVENTS
from labreserve_messaging.runtime import run_worker
from .database import SessionLocal, engine
from .handler import handle_event
from .models import messaging_tables

if __name__ == "__main__":
    try:
        run_worker("notification", SessionLocal, messaging_tables, [BOOKING_EVENTS], handle_event)
    finally:
        engine.dispose()
