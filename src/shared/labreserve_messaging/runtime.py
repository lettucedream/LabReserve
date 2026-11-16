import logging
import os
import signal
import threading
from datetime import UTC, datetime

from confluent_kafka import Consumer, KafkaException, Producer
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from .events import Event

logger = logging.getLogger(__name__)


class PermanentEventError(ValueError):
    pass


def assignment_lost(consumer, partitions) -> None:
    raise RuntimeError("Assegnazione Kafka persa; riavvio del worker")


def process_event(session_factory, tables, handler, event: Event) -> bool:
    with session_factory.begin() as session:
        inserted = session.scalar(insert(tables.inbox).values(event_id=event.event_id)
            .on_conflict_do_nothing().returning(tables.inbox.event_id))
        if inserted is None:
            return False
        handler(session, event)
    return True


def producer_config() -> dict:
    return {
        "bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
        "enable.idempotence": True, "acks": "all", "message.timeout.ms": 5000,
    }


def send_event(producer: Producer, topic: str, key: str, payload: dict) -> None:
    import json
    outcome = []
    producer.produce(topic, key=key.encode(), value=json.dumps(payload).encode(),
        on_delivery=lambda error, message: outcome.append(error))
    remaining = producer.flush(6)
    if remaining or not outcome or outcome[0] is not None:
        raise RuntimeError("Kafka non ha confermato la pubblicazione")


def publish_one(session_factory, tables, producer: Producer) -> bool:
    with session_factory.begin() as session:
        
        if not session.scalar(text("SELECT pg_try_advisory_xact_lock(28110601)")):
            return False
        row = session.scalar(select(tables.outbox).where(tables.outbox.published_at.is_(None))
            .order_by(tables.outbox.id).limit(1).with_for_update(skip_locked=True))
        if row is None:
            return False
        send_event(producer, row.topic, row.message_key, row.payload)
        row.published_at = datetime.now(UTC)
    return True


def heartbeat(session_factory, tables) -> None:
    now = datetime.now(UTC)
    with session_factory.begin() as session:
        session.execute(insert(tables.heartbeat).values(name="worker", last_seen=now)
            .on_conflict_do_update(index_elements=[tables.heartbeat.name], set_={"last_seen": now}))


def quarantine(session_factory, tables, message, reason: str) -> None:
    with session_factory.begin() as session:
        session.execute(insert(tables.dead_letter).values(
            topic=message.topic(), partition=message.partition(), offset=message.offset(),
            payload=(message.value() or b"").decode("utf-8", errors="replace")[:65536], reason=reason[:1000],
        ).on_conflict_do_nothing(constraint="uq_dead_letter_position"))


def run_worker(service: str, session_factory, tables, topics: list[str], handler, on_tick=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, frame: stop.set())
    producer = Producer(producer_config())
    consumer = Consumer({
        "bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"], "group.id": service + "-v1",
        "auto.offset.reset": "earliest", "enable.auto.commit": False,
        "enable.auto.offset.store": False, "max.poll.interval.ms": 120000,
    })
    try:
        consumer.list_topics(timeout=15)
        consumer.subscribe(topics, on_lost=assignment_lost)
        while not stop.is_set():
            if on_tick is not None:
                on_tick()
            try:
                publish_one(session_factory, tables, producer)
            except Exception as exc:
                
                logger.warning("Pubblicazione rinviata: %s", type(exc).__name__)
                stop.wait(0.5)
            message = consumer.poll(0.2)
            if message is not None:
                if message.error():
                    logger.warning("Kafka: %s", message.error().name())
                    stop.wait(0.5)
                else:
                    try:
                        event = Event.model_validate_json(message.value() or b"")
                        if message.key() != str(event.data.slot_id).encode():
                            raise PermanentEventError("Chiave Kafka diversa dallo slot")
                        process_event(session_factory, tables, handler, event)
                    except (ValidationError, PermanentEventError) as exc:
                        
                        quarantine(session_factory, tables, message, str(exc))
                        logger.warning("Evento salvato in dead_letters")
                    
                    result = consumer.commit(message=message, asynchronous=False)
                    for partition in result or []:
                        if partition.error:
                            raise KafkaException(partition.error)
            heartbeat(session_factory, tables)
    finally:
        consumer.close()
        producer.flush(6)
