import json
from types import SimpleNamespace as NS

import pytest

from ndpa.analyse.trackers import TrackerList
from ndpa.capture.events import EventLog
from ndpa.capture.recorder import Recorder

SITE = "https://www.shop.com.ng/"
SNAPSHOT = {"trackers": {
    "tracker.example": {"owner": {"displayName": "Tracker Inc"}, "default": "block",
                        "categories": ["Analytics"], "rules": []},
}}


@pytest.fixture
def trackers(tmp_path):
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(SNAPSHOT))
    return TrackerList(p)


@pytest.fixture
def rec(trackers):
    log = EventLog()
    log.start()
    r = Recorder(SITE, log, trackers)
    r.main_frame = "MAIN"
    return r


def request(url, rtype="script", frame_url=SITE):
    return NS(url=url, method="GET", resource_type=rtype, frame=NS(url=frame_url))


def response(url, status=200, rtype="document", frame="MAIN", headers=None, raw=None):
    def all_headers():
        if raw is None:
            raise RuntimeError("response gone")
        return raw
    return NS(url=url, status=status, request=NS(resource_type=rtype), frame=frame,
              headers=headers or {}, all_headers=all_headers)


def events(rec, kind):
    return [e for e in rec.log.events if e.kind == kind]


def test_tracker_request_is_flagged_with_vendor(rec):
    rec.on_request(request("https://cdn.tracker.example/t.js?uid=secret123"))
    e = events(rec, "request")[0]
    assert e.third_party and e.vendor == "Tracker Inc" and e.detail["tracker"]
    assert e.detail["url"] == "https://cdn.tracker.example/t.js"
    assert e.detail["query_keys"] == ["uid"]
    assert "secret123" not in e.model_dump_json()


def test_first_party_request_is_not_a_tracker(rec):
    rec.on_request(request("https://static.shop.com.ng/app.js"))
    e = events(rec, "request")[0]
    assert e.third_party is False and e.vendor is None and not e.detail["tracker"]


def test_non_http_requests_are_skipped(rec):
    rec.on_request(request("data:image/png;base64,AAAA"))
    assert rec.log.events == []


def test_request_without_frame_still_recorded(rec):
    req = NS(url="https://x.example/a.js", method="GET", resource_type="script")  # no .frame
    rec.on_request(req)
    assert events(rec, "request")[0].detail["frame_url"] is None


def test_main_document_skips_redirect_and_other_frames(rec):
    rec.on_response(response("https://shop.com.ng/", status=301))
    rec.on_response(response("https://ads.example/frame", status=403, frame="OTHER"))
    assert rec.main_status is None
    rec.on_response(response("https://www.shop.com.ng/", status=200, headers={"server": "nginx"}))
    assert rec.main_status == 200 and rec.main_headers == {"server": "nginx"}


def test_script_cookie_is_attributed_and_value_is_hashed(rec):
    payload = {"kind": "cookie_set_js", "raw": "_id=abc123; path=/",
               "script": "https://cdn.tracker.example/t.js?v=2"}
    rec.on_js(json.dumps(payload))
    e = events(rec, "cookie_set_js")[0]
    assert e.detail["name"] == "_id" and e.detail["attributed"] is True
    assert e.detail["script"] == "https://cdn.tracker.example/t.js"
    assert e.third_party and e.vendor == "Tracker Inc"
    assert "abc123" not in e.model_dump_json() and len(e.detail["value_hash"]) == 12


def test_unattributed_storage_set(rec):
    rec.on_js(json.dumps({"kind": "storage_set", "area": "localStorage", "key": "k",
                          "value": "v", "script": None}))
    e = events(rec, "storage_set")[0]
    assert e.detail["attributed"] is False and e.domain is None and e.detail["key"] == "k"


def test_bad_payload_becomes_capture_error_not_a_crash(rec):
    rec.on_js("not json")
    assert len(events(rec, "capture_error")) == 1


def test_set_cookie_names_are_added_after_the_fact(rec):
    rec.on_response(response("https://www.shop.com.ng/", raw={"set-cookie": "sid=1; Path=/\nlang=en"}))
    rec.on_response(response("https://www.shop.com.ng/a.css", rtype="stylesheet", raw=None))  # gone
    rec.resolve_set_cookies()
    first, second = events(rec, "response")
    assert first.detail["set_cookie_names"] == ["sid", "lang"]
    assert "set_cookie_names" not in second.detail
