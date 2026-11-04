import pytest

from ndpa.models import Condition, ConsentObservation, Event, RunResult, RunStatus, ScoreCard, ScanStatus
from ndpa.storage import db


def rows(rule_id="CN-01", outcome="non_compliant"):
    return [{"rule_id": rule_id, "tier": "major", "category": "consent", "outcome": outcome, "instances_failed": 1,
             "instances_total": 1, "root_cause": None, "note": "n", "evidence": [{"k": "v"}]}]


def test_schema_is_created_once_and_can_be_reopened(tmp_path):
    path = tmp_path / "x.db"
    db.connect(path).close()
    conn = db.connect(path)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"scan", "run", "event", "finding", "score", "artifact", "progress"} <= names


def test_a_scan_with_runs_events_findings_score_and_artifacts(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    scan_id = db.insert_scan(conn, "https://shop.ng/", "shop.ng", "/tmp/f", "Port Harcourt, NG", tool_version="abc123")
    run = RunResult(url="https://shop.ng/", condition=Condition.NO_ACTION, status=RunStatus.OK, observe_s=1, load_ms=900,
                    events=[Event(t_ms=10, kind="request", domain="a.example", third_party=True, vendor="A", detail={"x": 1}),
                            Event(t_ms=5, kind="response", detail={})],
                    consent=ConsentObservation(click_ms=None))
    run_id = db.insert_run(conn, scan_id, run, attempts=2)
    db.insert_findings(conn, scan_id, rows())
    db.insert_score(conn, scan_id, ScoreCard(status=ScanStatus.DONE, score_weighted=80.0, band="moderate", coverage=1.0,
                                             category_scores={"consent": 50.0}, scored_weight=28, total_weight=28))
    db.insert_artifacts(conn, scan_id, [{"path": "a.txt", "sha256": "1" * 64, "bytes": 3, "chain": "2" * 64}])
    db.update_scan(conn, scan_id, status="done", manifest_hash="f" * 64)
    scan = db.get_scan(conn, scan_id)
    assert scan["status"] == "done" and scan["tool_version"] == "abc123" and scan["vantage"] == "Port Harcourt, NG"
    ordered = [r["t_ms"] for r in conn.execute("SELECT t_ms FROM event WHERE run_id = ? ORDER BY t_ms", (run_id,))]
    assert ordered == [5, 10]
    assert db.get_findings(conn, scan_id)[0]["rule_id"] == "CN-01"
    assert conn.execute("SELECT attempts FROM run").fetchone()[0] == 2


def test_history_for_a_host_is_newest_first_with_the_headline_score(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    ids = [db.insert_scan(conn, "https://shop.ng/", "shop.ng", "/tmp/f", "NG") for _ in range(2)]
    db.insert_scan(conn, "https://other.ng/", "other.ng", "/tmp/g", "NG")
    db.insert_score(conn, ids[1], ScoreCard(status=ScanStatus.DONE, score_weighted=61.5, band="high", coverage=1.0))
    history = db.list_scans(conn, "shop.ng")
    assert [h["id"] for h in history] == [ids[1], ids[0]] and history[0]["score_weighted"] == 61.5
    assert len(db.list_scans(conn)) == 3


def test_only_known_scan_columns_can_be_updated(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    scan_id = db.insert_scan(conn, "https://shop.ng/", "shop.ng", "/tmp/f", "NG")
    with pytest.raises(ValueError):
        db.update_scan(conn, scan_id, url="https://evil.example/")


def test_progress_rows_are_kept_in_order(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    scan_id = db.insert_scan(conn, "https://shop.ng/", "shop.ng", "/tmp/f", "NG")
    db.log_progress(conn, scan_id, "no_action", "capturing")
    db.log_progress(conn, scan_id, "no_action", "ok")
    assert [r["message"] for r in conn.execute("SELECT message FROM progress ORDER BY id")] == ["capturing", "ok"]
