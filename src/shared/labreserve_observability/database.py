import logging
from time import perf_counter

from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select, text

logger = logging.getLogger(__name__)


def gauge(name, help_text, service, rows, labels=()):
    metric = GaugeMetricFamily(name, help_text, labels=["service", *labels])
    for values, value in rows:
        metric.add_metric([service, *map(str, values)], float(value))
    return metric


def scalar_gauge(name, help_text, service, value):
    return gauge(name, help_text, service, [((), value)])


def age_seconds(value, now):
    return 0 if value is None else max(0, (now - value).total_seconds())


class DatabaseCollector:
    def __init__(self, service, session_factory, tables, business_metrics):
        self.service, self.session_factory = service, session_factory
        self.tables, self.business_metrics = tables, business_metrics

    def describe(self):
        
        return []

    def collect(self):
        started, metrics, success = perf_counter(), [], 0
        try:
            with self.session_factory.begin() as session:
                session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                session.execute(text("SET LOCAL statement_timeout = '3000ms'"))
                now = session.scalar(select(func.now()))
                pending, oldest = session.execute(select(func.count(), func.min(self.tables.outbox.created_at))
                    .where(self.tables.outbox.published_at.is_(None))).one()
                last_seen = session.scalar(select(func.max(self.tables.heartbeat.last_seen)))
                for name, help_text, value in [
                    ("labreserve_outbox_pending", "Eventi locali ancora da pubblicare", pending),
                    ("labreserve_outbox_oldest_age_seconds", "Eta del piu vecchio evento non pubblicato, zero se assente", age_seconds(oldest, now)),
                    ("labreserve_worker_last_seen_timestamp_seconds", "Ultimo heartbeat worker persistito, zero se assente", 0 if last_seen is None else last_seen.timestamp()),
                    ("labreserve_dead_letters", "Eventi conservati in quarantena", session.scalar(select(func.count()).select_from(self.tables.dead_letter))),
                    ("labreserve_inbox_events", "Eventi distinti persistiti nell'inbox locale", session.scalar(select(func.count()).select_from(self.tables.inbox))),
                ]:
                    metrics.append(scalar_gauge(name, help_text, self.service, value))
                metrics.extend(self.business_metrics(session, now))
            success = 1
        except Exception as error:
            
            
            logger.warning("Raccolta metriche SQL fallita (%s): %s", self.service, type(error).__name__)
        if success:
            yield from metrics
        yield scalar_gauge("labreserve_metrics_database_up", "Lettura SQL delle metriche riuscita", self.service, success)
        yield scalar_gauge("labreserve_metrics_database_collection_duration_seconds", "Durata della raccolta SQL", self.service, perf_counter() - started)
