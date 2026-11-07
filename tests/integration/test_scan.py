"""Whole scans against the fixture site. Needs a real browser."""
import json
import sqlite3

import pytest

from ndpa.capture.run import BrowserConfig
from ndpa.evidence import chain
from ndpa.models import ScanStatus
from ndpa.scan import ScanOptions, run_scan

pytestmark = pytest.mark.browser
OPTS = ScanOptions(observe_s=1, browser=BrowserConfig(channel=None, headless=True), vantage="test", retry_pause_s=0)


def scan(url, tmp_path):
    return run_scan(url, tmp_path / "t.db", tmp_path / "evidence", OPTS, say_out=lambda *_: None)


def rows(tmp_path, sql, *args):
    conn = sqlite3.connect(tmp_path / "t.db")
    return conn.execute(sql, args).fetchall()


def test_a_full_scan_is_stored_scored_and_sealed(site, tmp_path):
    s = scan(f"{site}/banner_simple.html", tmp_path)
    assert s.status == ScanStatus.DONE and s.card.score_weighted is not None
    assert {p.name for p in s.folder.iterdir()} >= {"no_action", "accept", "reject", "policy", "results.json",
                                                    "meta.json", "manifest.json", "verify.py"}
    assert [r[0] for r in rows(tmp_path, "SELECT condition FROM run ORDER BY id")] == ["no_action", "accept", "reject"]
    assert rows(tmp_path, "SELECT COUNT(*) FROM finding")[0][0] == 17
    assert rows(tmp_path, "SELECT COUNT(*) FROM event")[0][0] > 10
    assert rows(tmp_path, "SELECT COUNT(*) FROM score")[0][0] == 1
    scan_row = rows(tmp_path, "SELECT status, manifest_hash, vantage, browser_version, tool_version FROM scan")[0]
    assert scan_row[0] == "done" and scan_row[1] == s.manifest_hash and scan_row[2] == "test" and scan_row[3]
    assert chain.verify(s.folder, expect=s.manifest_hash)[0] == []


def test_the_sealed_evidence_detects_tampering(site, tmp_path):
    s = scan(f"{site}/banner_simple.html", tmp_path)
    (s.folder / "results.json").write_text("{}")
    assert any("results.json" in p for p in chain.verify(s.folder)[0])


def test_a_blocked_site_stops_after_the_first_run_and_gets_no_score(site, tmp_path):
    s = scan(f"{site}/blocked.html", tmp_path)
    assert s.status == ScanStatus.BLOCKED and s.card.score_weighted is None
    assert [r[0] for r in rows(tmp_path, "SELECT condition FROM run")] == ["no_action"]
    assert rows(tmp_path, "SELECT COUNT(*) FROM finding")[0][0] == 0
    assert not (s.folder / "policy").exists()
    assert chain.verify(s.folder)[0] == []


def test_an_unreachable_site_is_tried_twice_then_fails(tmp_path):
    s = scan("http://127.0.0.1:9/", tmp_path)
    assert s.status == ScanStatus.FAILED
    assert rows(tmp_path, "SELECT attempts, status FROM run") == [(2, "failed")]
    assert chain.verify(s.folder)[0] == []


def test_a_close_only_banner_is_judged_strictly_and_the_implied_reading_is_reported(site, tmp_path):
    scan(f"{site}/banner_close_only.html", tmp_path)
    outcome, evidence = rows(tmp_path, "SELECT outcome, evidence_json FROM finding WHERE rule_id = 'CN-02'")[0]
    after_close = [e for e in json.loads(evidence) if e["run"] == "close"]
    assert outcome == "non_compliant" and after_close and {"excused_if_implied", "implied_outcome"} <= set(after_close[0])
    other = tmp_path / "other"
    other.mkdir()
    scan(f"{site}/banner_simple.html", other)  # an Accept button: Close is not involved
    evidence = rows(other, "SELECT evidence_json FROM finding WHERE rule_id = 'CN-02'")[0][0]
    assert not any(e["run"] == "close" for e in json.loads(evidence))
