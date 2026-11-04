"""Run clock and event log (D-30, D-31), plus privacy helpers (D-22)."""
import hashlib
import time
from collections.abc import Callable
from urllib.parse import parse_qsl, urlsplit

from ndpa.models import Event


class EventLog:
    """Collects events. t_ms = milliseconds since start(), on one monotonic clock."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._t0: float | None = None
        self.events: list[Event] = []

    def start(self) -> None:
        self._t0 = self._clock()

    def now_ms(self) -> int:
        if self._t0 is None:
            raise RuntimeError("clock not started")
        return int((self._clock() - self._t0) * 1000)

    def add(self, kind: str, domain: str | None = None, third_party: bool | None = None,
            vendor: str | None = None, **detail) -> Event:
        event = Event(t_ms=self.now_ms(), kind=kind, domain=domain,
                      third_party=third_party, vendor=vendor, detail=detail)
        self.events.append(event)
        return event


def value_hash(value: str) -> str:
    """Short hash of a value, so changes can be seen without storing the value."""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]


def clean_url(url: str) -> tuple[str, list[str]]:
    """URL without query values or fragment, plus the query key names."""
    parts = urlsplit(url)
    if parts.scheme in ("data", "blob", "about", "javascript"):
        return f"{parts.scheme}:", []
    keys = sorted({k for k, _ in parse_qsl(parts.query, keep_blank_values=True)})
    return f"{parts.scheme}://{parts.netloc}{parts.path}", keys


def set_cookie_names(raw_header: str | None) -> list[str]:
    """Cookie names from a raw set-cookie header value (several cookies are joined by newlines)."""
    names = []
    for line in (raw_header or "").splitlines():
        name = line.split("=", 1)[0].strip()
        if name:
            names.append(name)
    return names


def parse_cookie_assignment(raw: str) -> tuple[str, str]:
    """Split what a script assigned to document.cookie into (name, value)."""
    pair = raw.split(";", 1)[0]
    name, _, value = pair.partition("=")
    return name.strip(), value.strip()
