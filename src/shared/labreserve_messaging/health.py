from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.database import engine


def main() -> None:
    try:
        with engine.connect() as connection:
            last_seen = connection.scalar(text("SELECT last_seen FROM worker_heartbeats WHERE name = 'worker'"))
        if last_seen is None or datetime.now(UTC) - last_seen > timedelta(seconds=45):
            raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
