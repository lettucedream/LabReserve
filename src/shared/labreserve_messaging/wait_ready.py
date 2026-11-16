import argparse
import os
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("resource", choices=["connection", "database", "broker", "topics"])
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    deadline, reason = time.monotonic() + args.timeout, "not ready"
    engine = None
    if args.resource in {"connection", "database"}:
        from app.database import engine
        from sqlalchemy import text
        if args.resource == "database":
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            expected = set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())
    else:
        from confluent_kafka.admin import AdminClient
        from .events import COMMANDS, AVAILABILITY_EVENTS, BOOKING_EVENTS, BOOKING_COMMANDS, WAITING_COMMANDS
        admin = AdminClient({"bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"], "log_level": 0})
        expected = {COMMANDS, AVAILABILITY_EVENTS, BOOKING_EVENTS, BOOKING_COMMANDS, WAITING_COMMANDS}
    print("Attendo:", args.resource, flush=True)
    try:
        while time.monotonic() < deadline:
            try:
                if engine is not None:
                    with engine.connect() as connection:
                        connection.execute(text("SELECT 1"))
                        ready = args.resource == "connection" or set(connection.scalars(text("SELECT version_num FROM alembic_version"))) == expected
                else:
                    metadata = admin.list_topics(timeout=4)
                    ready = bool(metadata.brokers) and (args.resource == "broker" or all(
                        name in metadata.topics and metadata.topics[name].error is None
                        and len(metadata.topics[name].partitions) == 3 for name in expected))
                if ready:
                    print("Risorsa pronta:", args.resource, flush=True)
                    return
                reason = "schema o topic non ancora pronti"
            except Exception as error:
                reason = type(error).__name__
            time.sleep(1)
        raise SystemExit(f"Timeout {args.resource}: {reason}")
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__": main()
