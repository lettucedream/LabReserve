from time import perf_counter

from fastapi import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST, CollectorRegistry, Counter, GCCollector, Gauge, Histogram,
    PlatformCollector, ProcessCollector, generate_latest,
)


class RequestMetrics:
    def __init__(self, service, registry):
        self.service = service
        labels = ["service", "method", "route", "status"]
        self.requests = Counter("labreserve_http_requests_total", "Richieste HTTP terminate", labels, registry=registry)
        self.duration = Histogram("labreserve_http_request_duration_seconds", "Durata HTTP fino al completamento della risposta", labels,
            buckets=(.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, 30), registry=registry)
        self.in_progress = Gauge("labreserve_http_requests_in_progress", "Richieste HTTP in elaborazione", ["service"], registry=registry)


class MetricsMiddleware:
    def __init__(self, app, metrics):
        self.app, self.metrics = app, metrics

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "").removeprefix(scope.get("root_path", "")).rstrip("/")
        if scope["type"] != "http" or path == "/metrics":
            return await self.app(scope, receive, send)
        started, status = perf_counter(), 500
        self.metrics.in_progress.labels(self.metrics.service).inc()

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            
            route = getattr(scope.get("route"), "path", "__unmatched__")
            method = scope.get("method", "OTHER")
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"}:
                method = "OTHER"
            labels = (self.metrics.service, method, route, str(status))
            self.metrics.requests.labels(*labels).inc()
            self.metrics.duration.labels(*labels).observe(perf_counter() - started)
            self.metrics.in_progress.labels(self.metrics.service).dec()


def install_metrics(app, service, collector=None):
    registry = CollectorRegistry(auto_describe=True)
    GCCollector(registry=registry)
    ProcessCollector(registry=registry)
    PlatformCollector(registry=registry)
    metrics = RequestMetrics(service, registry)
    if collector is not None:
        registry.register(collector)
    app.state.metrics_registry = registry
    app.add_middleware(MetricsMiddleware, metrics=metrics)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        
        return Response(content=generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    return registry
