"""Turns browser events into Event rows. No browser needed, so it is unit-testable."""
import functools
import json
from urllib.parse import urlparse

from ndpa.analyse.trackers import TrackerList, is_third_party
from ndpa.capture.events import (
    EventLog,
    clean_url,
    parse_cookie_assignment,
    set_cookie_names,
    value_hash,
)


def _guarded(method):
    """A bug in one handler must not stop the capture; it is recorded as a capture_error event."""
    @functools.wraps(method)
    def wrapper(self, *args):
        try:
            return method(self, *args)
        except Exception as exc:  # noqa: BLE001
            self.log.add("capture_error", handler=method.__name__,
                         error=f"{type(exc).__name__}: {exc}"[:200])
    return wrapper


class Recorder:
    def __init__(self, site_url: str, log: EventLog, trackers: TrackerList | None = None):
        self.site_url = site_url
        self.log = log
        self.trackers = trackers
        self.main_frame = None          # set by the caller once the page exists
        self.main_status: int | None = None
        self.main_headers: dict = {}
        self._responses: list = []      # (event, response); Set-Cookie is read later, not in the handler

    @_guarded
    def on_request(self, request) -> None:
        url = request.url
        if not url.startswith(("http://", "https://")):
            return
        shown, keys = clean_url(url)
        third = is_third_party(url, self.site_url)
        match = self.trackers.match(url) if (self.trackers and third) else None
        try:
            frame_url = clean_url(request.frame.url)[0]
        except Exception:  # noqa: BLE001  (service-worker requests have no frame)
            frame_url = None
        self.log.add(
            "request", domain=urlparse(url).hostname, third_party=third,
            vendor=match.owner if match else None,
            method=request.method, resource_type=request.resource_type, url=shown,
            query_keys=keys, frame_url=frame_url, tracker=match is not None,
            tracker_categories=list(match.categories) if match else [],
            tracker_reason=match.reason if match else None,
        )

    @_guarded
    def on_response(self, response) -> None:
        url = response.url
        if not url.startswith(("http://", "https://")):
            return
        request = response.request
        event = self.log.add(
            "response", domain=urlparse(url).hostname,
            third_party=is_third_party(url, self.site_url),
            status=response.status, resource_type=request.resource_type, url=clean_url(url)[0],
        )
        self._responses.append((event, response))
        if (self.main_status is None and request.resource_type == "document"
                and not 300 <= response.status < 400 and response.frame == self.main_frame):
            self.main_status = response.status
            self.main_headers = dict(response.headers)

    @_guarded
    def on_js(self, payload: str) -> None:
        data = json.loads(payload)
        script = data.get("script")
        third = is_third_party(script, self.site_url) if script else None
        match = self.trackers.match(script) if (self.trackers and script and third) else None
        if data["kind"] == "cookie_set_js":
            name, value = parse_cookie_assignment(data.get("raw", ""))
            detail = {"name": name, "value_hash": value_hash(value)}
        elif data["kind"] == "storage_set":
            detail = {"area": data.get("area"), "key": data.get("key"),
                      "value_hash": value_hash(data.get("value", ""))}
        else:
            return
        self.log.add(
            data["kind"], domain=urlparse(script).hostname if script else None,
            third_party=third, vendor=match.owner if match else None,
            script=clean_url(script)[0] if script else None, attributed=script is not None,
            **detail,
        )

    def resolve_set_cookies(self) -> None:
        """Add the cookie names from each response's Set-Cookie header. Call before closing the browser."""
        for event, response in self._responses:
            try:
                names = set_cookie_names(response.all_headers().get("set-cookie"))
            except Exception:  # noqa: BLE001
                continue
            if names:
                event.detail["set_cookie_names"] = names
        self._responses.clear()
