"""Fix for the two failures: paste this whole file into script.py and run:  python script.py"""
import pathlib


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def write(path, text):
    pathlib.Path(path).write_text(text, encoding="utf-8")


def patch(path, old, new):
    s = read(path)
    if new in s and old not in s:
        print("  already applied:", path)
        return
    assert s.count(old) == 1, f"{path}: the expected text was not found exactly once. Paste me the lines around '{old[:40]}'."
    write(path, s.replace(old, new))
    print("  patched:", path)


def replace_between(path, start, end, new):
    """Replace everything from `start` up to (not including) `end`."""
    s = read(path)
    if new in s:
        print("  already applied:", path)
        return
    assert s.count(start) == 1 and s.count(end) == 1, f"{path}: could not find the place to change ('{start[:40]}'). Paste me that part of the file."
    a, b = s.index(start), s.index(end)
    assert a < b, f"{path}: the markers are in an unexpected order."
    write(path, s[:a] + new + s[b:])
    print("  patched:", path)


def append_once(path, marker, text):
    if marker in read(path):
        print("  already there:", path, marker)
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
    print("  added to:", path, marker)


# 1. The live-progress stream: one update per step, so a step that ends between two looks is never lost.
replace_between("src/ndpa/web/app.py", "        def stream() -> Iterator[str]:", "        return StreamingResponse(stream(),", '''        def stream() -> Iterator[str]:
            conn = db.connect(settings.db_path, share_across_threads=True)  # it may be closed from another thread when the visitor leaves

            def state(rows: list[dict], status: str) -> str:
                payload = json.dumps({"status": status, "stages": views.stage_states(rows, status),
                                      "position": app.state.manager.queue_position(scan_id)})
                return f"id: {rows[-1]['id'] if rows else 0}\\nevent: state\\ndata: {payload}\\n\\n"

            try:
                yield "retry: 2000\\n\\n"
                started, idle, cursor, sent = time.monotonic(), 0.0, last, None
                while time.monotonic() - started < 1800:
                    scan = db.get_scan(conn, scan_id)
                    if scan is None:
                        return
                    rows = db.progress_rows(conn, scan_id)
                    new = [r for r in rows if r["id"] > cursor]
                    for r in new:  # one update per step, in order, however quickly the steps happened
                        status = scan["status"] if r is new[-1] else "running"
                        yield state([x for x in rows if x["id"] <= r["id"]], status)
                        sent, cursor = status, r["id"]
                    if sent is None or (scan["status"] in db.FINAL_STATUSES and sent != scan["status"]):
                        yield state(rows, scan["status"])  # nothing new to say, but bring the page up to date
                        sent = scan["status"]
                    if scan["status"] in db.FINAL_STATUSES:
                        yield f"event: finished\\ndata: {json.dumps({'status': scan['status']})}\\n\\n"
                        return
                    idle += 0.5
                    if idle >= 15:
                        idle = 0
                        yield ": keep-alive\\n\\n"
                    time.sleep(0.5)
            finally:
                conn.close()

''')

# 2. The two stream tests no longer depend on how fast the fake scan runs.
replace_between("tests/unit/test_web_app.py", "def test_the_stream_for_a_finished_scan_sends_the_state_then_finishes(make):",
                "def test_the_stream_for_an_unknown_scan_ends_quietly(make):", '''def test_the_stream_replays_a_finished_scan_step_by_step_and_then_finishes(make):
    client, settings = make()
    sid = seeded(settings)
    got = events(stream(client, f"/scans/{sid}/events"))
    names = [n for n, _ in got]
    assert names[-1] == "finished" and got[-1][1]["status"] == "done" and names[:-1] == ["state"] * (len(names) - 1) and len(names) >= 3
    assert all(s["state"] == "done" for s in got[-2][1]["stages"])  # the last update shows everything done


def test_the_stream_reports_every_step_even_when_the_scan_is_over_before_anyone_looks(make):
    """The fake scan does not pause at all, which is the hardest case for a stream that only looks now and then."""
    settings_holder = {}

    def runner(scan_id, url):
        conn = db.connect(settings_holder["db"])
        db.update_scan(conn, scan_id, status="running")
        for stage, msg in (("no_action", "capturing"), ("no_action", "ok"), ("accept", "capturing"), ("accept", "ok"),
                           ("reject", "capturing"), ("reject", "ok"), ("policy", "found_linked"), ("rules", "evaluating"), ("saving", "x")):
            db.log_progress(conn, scan_id, stage, msg)
        db.update_scan(conn, scan_id, status="done", finished_at=db.now())
        conn.close()

    client, settings = make(runner=runner)
    settings_holder["db"] = settings.db_path
    client.post("/scans", data={"url": PUBLIC}, headers=SAME, follow_redirects=False)
    got = events(stream(client, "/scans/1/events"))
    states = [d for n, d in got if n == "state"]
    assert got[-1][0] == "finished" and got[-1][1]["status"] == "done"
    seen = [{s["key"]: s["state"] for s in d["stages"]} for d in states]
    assert any(x["no_action"] == "running" for x in seen)  # the first step was reported while it was running
    assert any(x["accept"] == "done" and x["reject"] != "done" for x in seen)  # and the order of the steps is kept
    assert seen[-1]["saving"] == "done" and all(v == "done" for v in seen[-1].values())
    done_once = dict.fromkeys(seen[0], False)
    for x in seen:  # a finished step never goes back
        for key, value in x.items():
            assert not (done_once[key] and value != "done"), key
            done_once[key] = done_once[key] or value == "done"


''')

patch("tests/unit/test_web_app.py", "import threading\nimport time\nfrom pathlib import Path\n", "import threading\nfrom pathlib import Path\n")  # the tests no longer sleep

# 3. The real-browser test no longer asks the page to evaluate a string as code (our security policy forbids that, correctly).
patch("tests/integration/test_dashboard_browser.py", '''    page.wait_for_function("document.getElementById('sb-03').open === true")''',
      '''    page.wait_for_selector("details#sb-03[open]")''')

# 4. Record it.
append_once("docs/decisions.md", "D-44", """
- D-44 (6 Nov 2026) The live-progress stream sends one update per step instead of only the latest picture, so a quick step is never skipped; tests must never depend on timing. Browser tests must not evaluate strings as JavaScript (the Content-Security-Policy forbids it); they use selector waits.
""")
append_once("docs/backlog.md", "B-39", """- B-39 My test sandbox runs older browsers (Playwright 1.56, Chromium 141) than the project's own machine (Chrome 156). Rule: before delivering, state the versions I tested with. A CI job that tests against the newest Playwright would catch these differences earlier.
""")
print("\nDone. Now run:  python -m ruff check src tests eval   and   python -m pytest -q")