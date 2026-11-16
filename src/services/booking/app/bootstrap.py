from alembic import command
from alembic.config import Config

from .database import engine


if __name__ == "__main__":
    try:
        command.upgrade(Config("alembic.ini"), "head")
        print("Migrazioni Booking completate.")
    finally:
        engine.dispose()
