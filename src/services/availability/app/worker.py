from labreserve_messaging.events import COMMANDS
from labreserve_messaging.runtime import run_worker

from .database import SessionLocal, engine
from .models import messaging_tables
from .saga import handle_event


if __name__ == "__main__":
    try:
        run_worker("availability", SessionLocal, messaging_tables, [COMMANDS], handle_event)
    finally:
        engine.dispose()
