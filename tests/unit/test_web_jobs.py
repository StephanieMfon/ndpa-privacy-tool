import os
import stat
import sys
import threading
import time

import pytest

from ndpa.storage import db
from ndpa.web.jobs import QueueFull, ScanManager, Settings


def wait_for(condition, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


def status_of(settings, scan_id):
    conn = db.connect(settings.db_path)
    try:
        return db.get_scan(conn, scan_id)
    finally:
        conn.close()


def finishing_runner(settings, order=None, gate=None):
    def run(scan_id, url):
        if order is not None:
            order.append(scan_id)
        if gate is not None:
            gate.wait(10)
        conn = db.connect(settings.db_path)
        db.update_scan(conn, scan_id, status="done", finished_at=db.now())
        conn.close()
    return run


def test_submit_creates_a_queued_scan_with_a_progress_row(tmp_path):
    s = Settings(db_path=tmp_path / "t.db", vantage="Port Harcourt, NG")
    m = ScanManager(s, runner=lambda *a: None)
    scan_id = m.submit("https://www.shop.ng/")
    conn = db.connect(s.db_path)
    scan = db.get_scan(conn, scan_id)
    assert scan["status"] == "queued" and scan["host"] == "www.shop.ng" and scan["vantage"] == "Port Harcourt, NG"
    assert db.progress_rows(conn, scan_id)[0]["stage"] == "queued" and m.queue_position(scan_id) == 1


def test_scans_run_one_at_a_time_in_order(tmp_path):
    s = Settings(db_path=tmp_path / "t.db")
    order, gate = [], threading.Event()
    m = ScanManager(s, runner=finishing_runner(s, order, gate))
    m.start()
    ids = [m.submit(f"https://s{i}.ng/") for i in range(3)]
    assert wait_for(lambda: order == [ids[0]])
    assert m.queue_position(ids[0]) == 0 and m.queue_position(ids[1]) == 1 and m.queue_position(ids[2]) == 2
    time.sleep(0.2)
    assert order == [ids[0]]  # the others wait while the first is running
    gate.set()
    assert wait_for(lambda: all(status_of(s, i)["status"] == "done" for i in ids))
    assert order == ids and m.queue_position(ids[2]) is None


def test_a_full_queue_refuses_more_scans(tmp_path):
    s = Settings(db_path=tmp_path / "t.db", max_queue=2)
    m = ScanManager(s, runner=lambda *a: None)  # worker not started: nothing leaves the queue
    m.submit("https://a.ng/")
    m.submit("https://b.ng/")
    with pytest.raises(QueueFull):
        m.submit("https://c.ng/")


def test_a_runner_that_crashes_marks_the_scan_failed_and_the_worker_carries_on(tmp_path):
    s = Settings(db_path=tmp_path / "t.db")
    calls = []

    def run(scan_id, url):
        calls.append(scan_id)
        if len(calls) == 1:
            raise RuntimeError("chrome exploded")
        finishing_runner(s)(scan_id, url)

    m = ScanManager(s, runner=run)
    m.start()
    first, second = m.submit("https://a.ng/"), m.submit("https://b.ng/")
    assert wait_for(lambda: status_of(s, second)["status"] == "done")
    broken = status_of(s, first)
    assert broken["status"] == "failed" and "chrome exploded" in broken["error"]


def test_a_runner_that_ends_without_a_result_is_marked_failed(tmp_path):
    s = Settings(db_path=tmp_path / "t.db")
    m = ScanManager(s, runner=lambda *a: None)
    m.start()
    scan_id = m.submit("https://a.ng/")
    assert wait_for(lambda: status_of(s, scan_id)["status"] == "failed")
    assert "stopped unexpectedly" in status_of(s, scan_id)["error"]


def test_starting_the_manager_fails_scans_left_over_from_a_previous_run(tmp_path):
    s = Settings(db_path=tmp_path / "t.db")
    conn = db.connect(s.db_path)
    stale = [db.create_scan(conn, "https://a.ng/", "a.ng", "NG", status=st) for st in ("queued", "running")]
    done = db.create_scan(conn, "https://b.ng/", "b.ng", "NG", status="done")
    ScanManager(s, runner=lambda *a: None).start()
    assert [status_of(s, i)["status"] for i in stale] == ["failed", "failed"] and status_of(s, done)["status"] == "done"
    assert "restarted" in status_of(s, stale[0])["error"]


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX only")
def test_a_scan_that_takes_too_long_is_killed_with_everything_it_started(tmp_path, monkeypatch):
    marker = tmp_path / "child-pid"
    script = tmp_path / "slow.sh"  # stands in for Python; starts a grandchild like Chrome would
    script.write_text(f"#!/bin/sh\nsleep 60 &\necho $! > {marker}\nwait\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(sys, "executable", str(script))
    s = Settings(db_path=tmp_path / "t.db", log_dir=tmp_path / "logs", scan_timeout_s=1.5)
    m = ScanManager(s)
    m.start()
    scan_id = m.submit("https://a.ng/")
    assert wait_for(lambda: status_of(s, scan_id)["status"] == "failed", timeout=15)
    assert "longer than" in status_of(s, scan_id)["error"]
    pid = int(marker.read_text())
    assert wait_for(lambda: not _alive(pid), timeout=5)  # the grandchild is gone too


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
