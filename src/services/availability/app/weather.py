import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from http.client import HTTPException as HTTPClientError
from time import monotonic
from typing import Literal
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from prometheus_client import Counter, Histogram
from pydantic import BaseModel, Field

from .circuit_breaker import CircuitBreaker, CircuitBreakerRejected


ROME = ZoneInfo("Europe/Rome")
FORECAST_DAYS = 7
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WeatherSettings:
    
    latitude: float = 37.5253
    longitude: float = 15.0722
    timeout_seconds: float = 4
    cache_seconds: int = 600
    max_age_seconds: int = 3600
    retry_seconds: int = 60

    def __post_init__(self):
        values = (self.latitude, self.longitude, self.timeout_seconds,
                  self.cache_seconds, self.max_age_seconds, self.retry_seconds)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Configurazione meteo non finita")
        if not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180:
            raise ValueError("Coordinate meteo non valide")
        if not 0 < self.timeout_seconds <= 10 or not 0 < self.cache_seconds <= self.max_age_seconds:
            raise ValueError("Timeout o durata della cache meteo non validi")
        if self.retry_seconds <= 0:
            raise ValueError("Intervallo di recupero meteo non valido")

    @classmethod
    def from_env(cls):
        return cls(
            latitude=float(os.getenv("WEATHER_LATITUDE", "37.5253")),
            longitude=float(os.getenv("WEATHER_LONGITUDE", "15.0722")),
            timeout_seconds=float(os.getenv("WEATHER_TIMEOUT_SECONDS", "4")),
            cache_seconds=int(os.getenv("WEATHER_CACHE_SECONDS", "600")),
            max_age_seconds=int(os.getenv("WEATHER_MAX_AGE_SECONDS", "3600")),
            retry_seconds=int(os.getenv("WEATHER_RETRY_SECONDS", "60")),
        )


class CurrentWeather(BaseModel):
    valid_at: datetime
    temperature_c: float
    apparent_temperature_c: float | None
    humidity_percent: float | None
    wind_kmh: float | None
    weather_code: int
    is_day: bool


class DailyWeather(BaseModel):
    date: date
    temperature_min_c: float
    temperature_max_c: float
    weather_code: int
    precipitation_probability_percent: float | None
    precipitation_mm: float | None
    wind_max_kmh: float | None


class WeatherResponse(BaseModel):
    status: Literal["fresh", "stale", "unavailable", "out_of_range"]
    location: str = "Cittadella Universitaria"
    city: str = "Catania"
    latitude: float
    longitude: float
    timezone: str = "Europe/Rome"
    provider: str = "Open-Meteo"
    selected_date: date
    available_from: date
    available_to: date
    fetched_at: datetime | None = None
    data_age_seconds: int | None = None
    max_age_seconds: int
    cache_seconds: int
    retry_after_seconds: int = Field(ge=1)
    current: CurrentWeather | None = None
    forecast: DailyWeather | None = None
    message: str | None = None


@dataclass(frozen=True)
class WeatherSnapshot:
    current: CurrentWeather
    daily: tuple[DailyWeather, ...]
    fetched_at: datetime
    cached_at: float


def fetch_open_meteo(settings):
    params = urlencode({
        "latitude": settings.latitude, "longitude": settings.longitude,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max",
        "forecast_days": FORECAST_DAYS, "timezone": "Europe/Rome", "timeformat": "unixtime",
        "temperature_unit": "celsius", "wind_speed_unit": "kmh", "precipitation_unit": "mm",
    })
    request = Request("https://api.open-meteo.com/v1/forecast?" + params,
                      headers={"Accept": "application/json", "User-Agent": "LabReserve/0.8 (educational project)"})
    with urlopen(request, timeout=settings.timeout_seconds) as response:
        raw = response.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise ValueError("Risposta meteo troppo grande")
    return json.loads(raw)


def number(value, minimum=None, maximum=None, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Valore meteo non numerico o non finito")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError("Valore meteo fuori intervallo")
    return value


def weather_code(value):
    code = number(value, 0, 99)
    if int(code) != code:
        raise ValueError("Codice meteo non intero")
    return int(code)


def normalize(payload, fetched_at, cached_at):
    
    if payload["current_units"]["temperature_2m"] != "°C" or payload["current_units"]["wind_speed_10m"] != "km/h":
        raise ValueError("Unita meteo inattese")
    daily_units = payload["daily_units"]
    if any(daily_units[key] != unit for key, unit in (
        ("temperature_2m_max", "°C"), ("temperature_2m_min", "°C"),
        ("precipitation_probability_max", "%"), ("precipitation_sum", "mm"), ("wind_speed_10m_max", "km/h"),
    )):
        raise ValueError("Unita delle previsioni inattese")
    raw = payload["current"]
    valid_at = datetime.fromtimestamp(number(raw["time"]), UTC)
    if not -600 <= (fetched_at - valid_at).total_seconds() <= 3600:
        raise ValueError("Condizioni meteo troppo vecchie o nel futuro")
    day_flag = number(raw["is_day"], 0, 1)
    if day_flag not in (0, 1):
        raise ValueError("Indicatore giorno/notte non valido")
    current = CurrentWeather(
        valid_at=valid_at, temperature_c=number(raw["temperature_2m"], -100, 70),
        apparent_temperature_c=number(raw.get("apparent_temperature"), -120, 100, optional=True),
        humidity_percent=number(raw.get("relative_humidity_2m"), 0, 100, optional=True),
        wind_kmh=number(raw.get("wind_speed_10m"), 0, 500, optional=True),
        weather_code=weather_code(raw["weather_code"]), is_day=bool(day_flag),
    )
    raw_daily = payload["daily"]
    timestamps = raw_daily["time"]
    required = ("temperature_2m_min", "temperature_2m_max", "weather_code",
                "precipitation_probability_max", "precipitation_sum", "wind_speed_10m_max")
    if not isinstance(timestamps, list) or len(timestamps) != FORECAST_DAYS:
        raise ValueError("Numero di giornate inatteso")
    if any(not isinstance(raw_daily[key], list) or len(raw_daily[key]) != len(timestamps) for key in required):
        raise ValueError("Previsioni giornaliere incomplete")
    daily = []
    for index, timestamp in enumerate(timestamps):
        day = datetime.fromtimestamp(number(timestamp), UTC).astimezone(ROME).date()
        if day != fetched_at.astimezone(ROME).date() + timedelta(days=index):
            raise ValueError("Giornate delle previsioni non consecutive o non aggiornate")
        row = DailyWeather(
            date=day,
            temperature_min_c=number(raw_daily["temperature_2m_min"][index], -100, 70),
            temperature_max_c=number(raw_daily["temperature_2m_max"][index], -100, 70),
            weather_code=weather_code(raw_daily["weather_code"][index]),
            precipitation_probability_percent=number(raw_daily["precipitation_probability_max"][index], 0, 100, optional=True),
            precipitation_mm=number(raw_daily["precipitation_sum"][index], 0, 5000, optional=True),
            wind_max_kmh=number(raw_daily["wind_speed_10m_max"][index], 0, 500, optional=True),
        )
        if row.temperature_min_c > row.temperature_max_c:
            raise ValueError("Temperature giornaliere incoerenti")
        daily.append(row)
    return WeatherSnapshot(current, tuple(daily), fetched_at, cached_at)


class WeatherService:
    def __init__(self, settings=None, *, fetch=None, clock=monotonic, now=None, registry=None):
        self.settings = settings or WeatherSettings.from_env()
        self.fetch = fetch or (lambda: fetch_open_meteo(self.settings))
        self.clock, self.now = clock, now or (lambda: datetime.now(UTC))
        self.snapshot = None
        self.circuit_breaker = CircuitBreaker(self.settings.retry_seconds, clock=self.clock)
        self.requests = Counter("labreserve_weather_provider_requests_total", "Chiamate al provider meteo", ["outcome"], registry=registry)
        self.duration = Histogram("labreserve_weather_provider_duration_seconds", "Durata chiamate al provider meteo", registry=registry,
                                  buckets=(.1, .25, .5, 1, 2, 4, 8, 15))
        self.responses = Counter("labreserve_weather_responses_total", "Esiti del meteo, inclusa la cache", ["status"], registry=registry)

    def get(self, selected_date=None):
        today = self.now().astimezone(ROME).date()
        day = selected_date or today
        if not today <= day < today + timedelta(days=FORECAST_DAYS):
            return self._response(day, today, out_of_range=True)
        tick = self.clock()
        if self._fresh(tick, today):
            return self._response(day, today)
        try:
            self.circuit_breaker.call(lambda: self._refresh(today))
        except CircuitBreakerRejected:
            return self._response(day, today, retrying=True)
        except (OSError, HTTPClientError, ValueError, TypeError, KeyError, OverflowError) as exc:
            self.requests.labels("error").inc()
            logger.warning("Meteo esterno non disponibile: %s", type(exc).__name__)
        return self._response(day, today)

    def _refresh(self, today):
        started = self.clock()
        if self._fresh(started, today):
            return
        try:
            payload = self.fetch()
            self.snapshot = normalize(payload, self.now(), self.clock())
            self.requests.labels("success").inc()
        finally:
            self.duration.observe(max(0, self.clock() - started))

    def _fresh(self, tick, today):
        
        return (self.snapshot is not None
                and tick - self.snapshot.cached_at < self.settings.cache_seconds
                and self.snapshot.fetched_at.astimezone(ROME).date() == today)

    def _response(self, day, today, *, out_of_range=False, retrying=False):
        settings, snapshot, tick = self.settings, self.snapshot, self.clock()
        result = WeatherResponse(
            status="unavailable", latitude=settings.latitude, longitude=settings.longitude,
            selected_date=day, available_from=today, available_to=today + timedelta(days=FORECAST_DAYS - 1),
            max_age_seconds=settings.max_age_seconds, cache_seconds=settings.cache_seconds,
            retry_after_seconds=settings.retry_seconds,
        )
        if out_of_range:
            result.status = "out_of_range"
            result.retry_after_seconds = settings.cache_seconds
            result.message = "Previsioni disponibili per oggi e i prossimi sei giorni."
        elif snapshot and 0 <= tick - snapshot.cached_at < settings.max_age_seconds:
            forecast = next((row for row in snapshot.daily if row.date == day), None)
            if forecast:
                age = int(tick - snapshot.cached_at)
                result.status = "fresh" if self._fresh(tick, today) else "stale"
                result.forecast, result.fetched_at, result.data_age_seconds = forecast, snapshot.fetched_at, age
                if day == today and snapshot.current.valid_at.astimezone(ROME).date() == today:
                    result.current = snapshot.current
                result.retry_after_seconds = max(1, settings.cache_seconds - age) if result.status == "fresh" else settings.retry_seconds
                if result.status == "stale":
                    result.message = "Aggiornamento meteo temporaneamente non disponibile. Ultimi dati ricevuti."
        if result.status == "unavailable":
            result.message = "Meteo temporaneamente non disponibile. Le prenotazioni restano disponibili."
            if retrying and tick >= self.circuit_breaker.retry_at:
                result.retry_after_seconds = 2
        self.responses.labels(result.status).inc()
        return result
