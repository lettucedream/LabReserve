import os

from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

from .events import AVAILABILITY_EVENTS, BOOKING_COMMANDS, BOOKING_EVENTS, COMMANDS, WAITING_COMMANDS


def main() -> None:
    admin = AdminClient({"bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"]})
    futures = admin.create_topics([NewTopic(name, num_partitions=3, replication_factor=1)
        for name in [COMMANDS, AVAILABILITY_EVENTS, BOOKING_EVENTS, BOOKING_COMMANDS, WAITING_COMMANDS]])
    for name, future in futures.items():
        try:
            future.result(timeout=30)
        except KafkaException as exc:
            if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                raise
        print("Topic pronto:", name)


if __name__ == "__main__":
    main()
