import json
import os
import re
import threading
import time
from pathlib import Path

import pytest
import web_seed as ws
from fastapi.testclient import TestClient

from ndpa.storage import db
from ndpa.web.app import create_app
from ndpa.web.jobs import ScanManager, Settings

PUBLIC = "http://93.184.216.34/"  # a public address, so the address check needs no DNS
SAME = {"origin": "http://testserver"}


@pytest.fixture
def make(tmp_path):
    clients = []

    def build(runner=None, **overrides):
        settings = Settings(db_path=tmp_path / "t.db", evidence_root=tmp_path / "ev", log_dir=tmp_path / "logs", **overrides)
        manager = ScanManager(settings, runner=runner or (lambda *a: None))
        client = TestClient(create_app(settings, manager))
        client.__enter__()
        clients.append(client)
        return client, settings

    yield build
    for c in clients:
        c.__exit__(None, None, None)


def seeded(settings, **kw):
    conn = db.connect(settings.db_path)
    try:
        return ws.seed_scan(conn, settings.evidence_root, **kw)
    finally:
        conn.close()


# ---------- starting scans ----------
def test_home_has_the_scan_form(make):
    client, _ = make()
    r = client.get("/")
    assert r.status_code == 200 and 'name="url"' in r.text and 'action="/scans"' in r.text and "No scans yet" in r.text


def test_a_valid_address_starts_a_scan_and_redirects_to_its_page(make):
    client, settings = make()
    r = client.post("/scans", data={"url": "93.184.216.34"}, headers=SAME, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/scans/1"
    conn = db.connect(settings.db_path)
    scan = db.get_scan(conn, 1)
    assert scan["url"] == "https://93.184.216.34" and scan["status"] in ("queued", "failed")  # the do-nothing runner fails it at once


def test_an_address_on_a_private_network_is_refused_and_nothing_is_stored(make):
    client, settings = make()
    r = client.post("/scans", data={"url": "http://127.0.0.1:8000/"}, headers=SAME)
    assert r.status_code == 400 and "private or local" in r.text and "127.0.0.1:8000" in r.text  # the typed address is kept
    assert db.list_scans(db.connect(settings.db_path)) == []


def test_junk_input_gets_a_friendly_message(make):
    client, _ = make()
    for junk in ("", "ftp://x.ng", "not a url at all"):
        r = client.post("/scans", data={"url": junk}, headers=SAME)
        assert r.status_code == 400 and 'role="alert"' in r.text


def test_a_post_from_another_website_is_refused(make):
    client, settings = make()
    r = client.post("/scans", data={"url": PUBLIC}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and db.list_scans(db.connect(settings.db_path)) == []


def test_a_full_queue_says_so(make):
    gate = threading.Event()
    client, _ = make(runner=lambda *a: gate.wait(10), max_queue=1)
    assert client.post("/scans", data={"url": PUBLIC}, headers=SAME, follow_redirects=False).status_code == 303
    r = client.post("/scans", data={"url": "http://93.184.216.35/"}, headers=SAME)
    assert r.status_code == 400 and "Too many scans" in r.text
    gate.set()


# ---------- pages ----------
def test_every_page_renders_for_every_kind_of_scan(make):
    client, settings = make()
    done = seeded(settings, host="shop.ng", started="2026-10-28T09:12:44+00:00", results=ws.problem_site())
    later = seeded(settings, host="shop.ng", started="2026-11-04T22:06:59+00:00", results=ws.better_site())
    blocked = seeded(settings, host="gt.com", results=None, status="blocked", started="2026-11-03T08:45:25+00:00")
    failed = seeded(settings, host="old.ng", results=None, status="failed", error="DNS", started="2026-11-01T10:00:00+00:00")
    urls = ["/", "/history", "/history/shop.ng", f"/compare?a={done}&b={later}", f"/compare?pick={done}&pick={later}",
            f"/scans/{done}", f"/scans/{done}/timeline", f"/scans/{done}/evidence", f"/scans/{later}",
            f"/scans/{blocked}", f"/scans/{blocked}/evidence", f"/scans/{failed}", f"/scans/{failed}/evidence", f"/api/scans/{later}"]
    for url in urls:
        assert client.get(url).status_code == 200, url
    page = client.get(f"/scans/{later}").text
    assert "High risk" in page and "In plain words" in page and "Fix first" in page and "All 17 checks" in page and 'id="sb-03"' in page
    assert "refused an automated visit" in client.get(f"/scans/{blocked}").text and "No score is given" in client.get(f"/scans/{blocked}").text
    assert "could not be completed" in client.get(f"/scans/{failed}").text
    assert "Timeline" not in client.get(f"/scans/{blocked}").text.split("<main")[1].split("</nav>")[1][:400]  # no timeline tab for a blocked scan


def test_a_running_scan_shows_live_progress_and_timeline_redirects_to_it(make):
    gate = threading.Event()
    client, settings = make(runner=lambda *a: gate.wait(10))
    r = client.post("/scans", data={"url": PUBLIC}, headers=SAME, follow_redirects=True)
    assert 'data-progress' in r.text and "First visit, no clicks" in r.text and 'data-stage="reject"' in r.text
    follow = client.get("/scans/1/timeline", follow_redirects=False)
    assert follow.status_code == 303 and follow.headers["location"] == "/scans/1"
    gate.set()


def test_unknown_things_get_the_friendly_not_found_page(make):
    client, _ = make()
    for url in ("/scans/99", "/scans/abc", "/history/nobody.ng", "/compare?a=1&b=2", "/compare?a=1&b=1", "/nope", "/scans/99/timeline"):
        r = client.get(url)
        assert r.status_code == 404 and "Go to the start" in r.text, url
    assert client.get("/api/scans/99").status_code == 404 and client.get("/api/scans/99").json() == {"error": "scan not found"}


def test_json_api_has_the_score_and_the_findings(make):
    client, settings = make()
    sid = seeded(settings, results=ws.better_site())
    data = client.get(f"/api/scans/{sid}").json()
    assert data["scan"]["host"] == "shop.ng" and data["score"]["band"] == "high" and len(data["findings"]) == 17
    assert data["fix_first"][0] in ("SB-01", "SB-03") and {"rule_id", "outcome", "evidence"} <= set(data["findings"][0])


# ---------- security ----------
def test_pages_have_no_inline_scripts_or_styles_so_the_strict_policy_holds(make):
    client, settings = make()
    a = seeded(settings, started="2026-10-28T09:12:44+00:00", results=ws.problem_site())
    b = seeded(settings, started="2026-11-04T22:06:59+00:00", results=ws.better_site())
    for url in ("/", "/history", "/history/shop.ng", f"/compare?a={a}&b={b}", f"/scans/{b}", f"/scans/{b}/timeline", f"/scans/{b}/evidence"):
        html = client.get(url).text
        assert " style=" not in html, url
        assert not re.search(r"<script(?![^>]*\bsrc=)", html), url
        assert not re.search(r"\son[a-z]+=", html), url


def test_every_response_carries_the_security_headers(make):
    client, _ = make()
    for url in ("/", "/static/app.css", "/nope"):
        h = client.get(url).headers
        assert "default-src 'none'" in h["content-security-policy"] and "script-src 'self'" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer"
    assert "immutable" in client.get("/static/app.js").headers["cache-control"]


def test_text_from_a_scanned_site_is_escaped(make):
    client, settings = make()
    hostile = ws.better_site()
    hostile["CN-01"] = ws.finding("CN-01", ws.N, "<img src=x onerror=alert(1)>", [{"banner": "<script>alert(2)</script>"}], 1, 1)
    sid = seeded(settings, results=hostile)
    page = client.get(f"/scans/{sid}").text
    assert "<img src=x" not in page and "<script>alert" not in page and "&lt;img src=x" in page
    api = client.get(f"/api/scans/{sid}")  # JSON is data, not a page: the browser must not treat it as HTML
    assert api.headers["content-type"].startswith("application/json") and api.headers["x-content-type-options"] == "nosniff"


def test_only_the_listed_evidence_files_are_served_and_never_outside_the_scan_folder(make):
    client, settings = make()
    sid = seeded(settings)
    folder = Path(db.get_scan(db.connect(settings.db_path), sid)["folder"])
    (folder / "network.har").write_text("{}")
    (folder.parent / "secret.txt").write_text("secret")
    ok = client.get(f"/scans/{sid}/file/no_action/screenshot.png")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png" and ok.content[:4] == b"\x89PNG"
    assert client.get(f"/scans/{sid}/file/manifest.json").status_code == 200
    assert client.get(f"/scans/{sid}/file/verify.py").headers["content-type"].startswith("text/plain")
    for bad in ("network.har", "../secret.txt", "..%2fsecret.txt", "no_action/../../secret.txt", "no_action/dom_snapshot.html", "results.json/../x"):
        assert client.get(f"/scans/{sid}/file/{bad}").status_code == 404, bad
    if os.name == "posix":  # a listed name that is really a link to somewhere else
        (folder / "meta.json").unlink()
        (folder / "meta.json").symlink_to(folder.parent / "secret.txt")
        assert client.get(f"/scans/{sid}/file/meta.json").status_code == 404


# ---------- live progress ----------
def stream(client, url):
    with client.stream("GET", url) as r:
        assert r.headers["content-type"].startswith("text/event-stream") and r.headers["x-accel-buffering"] == "no"
        return "".join(r.iter_text())


def events(text):
    out = []
    for block in text.split("\n\n"):
        name = re.search(r"^event: (\w+)", block, re.M)
        data = re.search(r"^data: (.*)$", block, re.M)
        if name and data:
            out.append((name.group(1), json.loads(data.group(1))))
    return out


def test_the_stream_for_a_finished_scan_sends_the_state_then_finishes(make):
    client, settings = make()
    sid = seeded(settings)
    got = events(stream(client, f"/scans/{sid}/events"))
    assert [n for n, _ in got] == ["state", "finished"] and got[1][1]["status"] == "done"
    assert all(s["state"] == "done" for s in got[0][1]["stages"])


def test_the_stream_follows_a_scan_from_waiting_to_finished(make):
    settings_holder = {}

    def runner(scan_id, url):
        conn = db.connect(settings_holder["db"])
        db.update_scan(conn, scan_id, status="running")
        for stage, msg in (("no_action", "capturing"), ("no_action", "ok"), ("accept", "capturing"), ("accept", "ok"),
                           ("reject", "capturing"), ("reject", "ok"), ("policy", "found_linked"), ("rules", "evaluating"), ("saving", "x")):
            db.log_progress(conn, scan_id, stage, msg)
            time.sleep(0.15)
        db.update_scan(conn, scan_id, status="done", finished_at=db.now())
        conn.close()

    client, settings = make(runner=runner)
    settings_holder["db"] = settings.db_path
    client.post("/scans", data={"url": PUBLIC}, headers=SAME, follow_redirects=False)
    got = events(stream(client, "/scans/1/events"))
    states = [d for n, d in got if n == "state"]
    assert len(states) >= 3 and got[-1][0] == "finished" and got[-1][1]["status"] == "done"
    seen = [{s["key"]: s["state"] for s in d["stages"]} for d in states]
    assert any(x["no_action"] == "running" for x in seen) and any(x["accept"] == "done" and x["reject"] != "done" for x in seen)
    assert seen[-1]["saving"] == "done"


def test_the_stream_for_an_unknown_scan_ends_quietly(make):
    client, _ = make()
    assert "event: finished" not in stream(client, "/scans/99/events")
