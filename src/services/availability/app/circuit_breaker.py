from enum import Enum
from threading import Lock
from time import monotonic


class CircuitBreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerRejected(RuntimeError):
    """Chiamata sospesa dal circuito o da un tentativo già in corso."""


class CircuitBreaker:
    """Circuito per processo: apre al primo errore e ammette una chiamata alla volta."""

    def __init__(self, recovery_timeout, *, clock=monotonic):
        self.recovery_timeout, self.clock = recovery_timeout, clock
        self._state = CircuitBreakerState.CLOSED
        self._retry_at = 0
        self._lock = Lock()

    @property
    def state(self):
        return self._state

    @property
    def retry_at(self):
        return self._retry_at

    def call(self, operation):
        if not self._lock.acquire(blocking=False):
            raise CircuitBreakerRejected("Chiamata al provider già in corso")
        try:
            if self._state is CircuitBreakerState.OPEN:
                if self.clock() < self._retry_at:
                    raise CircuitBreakerRejected("Circuit breaker aperto")
                self._state = CircuitBreakerState.HALF_OPEN

            try:
                result = operation()
            except BaseException:
                self._retry_at = self.clock() + self.recovery_timeout
                self._state = CircuitBreakerState.OPEN
                raise
            else:
                self._retry_at = 0
                self._state = CircuitBreakerState.CLOSED
                return result
        finally:
            self._lock.release()
