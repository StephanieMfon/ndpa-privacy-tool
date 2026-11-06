import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ndpa.evaluation import corpus
from ndpa.models import ScanStatus

SITES = ["https://a.ng", "https://b.ng", "https://c.ng", "https://d.ng"]


class FakeScanner:
    """Stands in for run_scan. results maps a site to a status (or an exception to raise)."""

    def __init__(self, results=None):
        self.results, self.calls = results or {}, []

    def __call__(self, url):
        self.calls.append(url)
        outcome = self.results.get(url, ScanStatus.DONE)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(scan_id=len(self.calls), status=outcome, error=None)


def run(tmp_path, scanner, **kw):
    kw.setdefault("allow_unfrozen", True)
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("say", lambda *a: None)
    return corpus.run_corpus(SITES, "t", scanner, "test lab", manifest_dir=tmp_path / "runs", freeze_file=tmp_path / "FREEZE.json", root=tmp_path, **kw)


def test_sites_are_read_without_blanks_comments_or_duplicates(tmp_path):
    path = tmp_path / "sites.txt"
    path.write_text("# my corpus\nhttps://a.ng\n\n  https://b.ng  \nhttps://a.ng\n")
    assert corpus.read_sites(path) == ["https://a.ng", "https://b.ng"]


def test_the_same_seed_always_gives_the_same_order():
    assert corpus.order_sites(SITES, 7) == corpus.order_sites(SITES, 7) and sorted(corpus.order_sites(SITES, 7)) == sorted(SITES)
    assert any(corpus.order_sites(SITES, s) != corpus.order_sites(SITES, 7) for s in range(8, 20))


def test_every_site_is_scanned_once_and_the_manifest_is_saved(tmp_path):
    scanner = FakeScanner({"https://b.ng": ScanStatus.BLOCKED})
    manifest = run(tmp_path, scanner)
    assert sorted(scanner.calls) == sorted(SITES)
    assert {u: e["status"] for u, e in manifest.entries.items()} == {"https://a.ng": "done", "https://b.ng": "blocked", "https://c.ng": "done", "https://d.ng": "done"}
    saved = json.loads((tmp_path / "runs" / "t.json").read_text())
    assert saved["vantage"] == "test lab" and saved["planned"] == SITES and len(saved["entries"]) == 4


def test_a_site_that_crashes_is_recorded_and_the_others_still_run(tmp_path):
    scanner = FakeScanner({"https://b.ng": RuntimeError("chrome exploded")})
    manifest = run(tmp_path, scanner)
    assert len(scanner.calls) == 4 and manifest.entries["https://b.ng"]["status"] == "failed"
    assert "chrome exploded" in manifest.entries["https://b.ng"]["error"] and manifest.entries["https://a.ng"]["status"] == "done"


def test_a_run_can_be_resumed_and_only_unsettled_sites_are_scanned(tmp_path):
    order = corpus.order_sites(SITES, 20261106)  # the order every run with the default seed uses
    first = FakeScanner({order[0]: ScanStatus.BLOCKED, order[1]: RuntimeError("network"), order[2]: ScanStatus.DONE})
    run(tmp_path, first, limit=3)  # stop early, as pressing Ctrl+C would
    assert first.calls == order[:3]
    second = FakeScanner()
    manifest = run(tmp_path, second)
    assert second.calls == [order[3]]  # blocked and done are settled; the failed site waits for --retry-failed
    assert {u: e["status"] for u, e in manifest.entries.items()} == {order[0]: "blocked", order[1]: "failed", order[2]: "done", order[3]: "done"}


def test_failed_sites_are_only_retried_when_asked(tmp_path):
    run(tmp_path, FakeScanner({u: RuntimeError("x") for u in SITES}))
    nothing = FakeScanner()
    run(tmp_path, nothing)
    assert nothing.calls == []
    again = FakeScanner()
    manifest = run(tmp_path, again, retry_failed=True)
    assert sorted(again.calls) == sorted(SITES) and all(e["attempts"] == 2 and e["status"] == "done" for e in manifest.entries.values())


def test_there_is_a_pause_between_sites_but_not_before_the_first(tmp_path):
    pauses = []
    run(tmp_path, FakeScanner(), pause_s=17, sleep=pauses.append)
    assert pauses == [17, 17, 17]


def test_the_time_window_is_watched(tmp_path):
    clock = {"t": datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)}

    def now():
        clock["t"] += timedelta(hours=30)  # each look at the clock is 30 hours later
        return clock["t"]
    manifest = run(tmp_path, FakeScanner(), now=now, window_hours=72)
    assert manifest.window_exceeded is True
    assert any(e["outside_window"] for e in manifest.entries.values()) and not manifest.entries[corpus.order_sites(SITES, manifest.seed)[0]]["outside_window"]


def freeze(tmp_path, content="rules: 1\n"):
    (tmp_path / "rules.yaml").write_text(content)
    record = {"rulebook_version": "2.0.0", "files": {"rules.yaml": {"sha256": corpus._sha256(tmp_path / "rules.yaml"), "bytes": 9}}}
    (tmp_path / "FREEZE.json").write_text(json.dumps(record))


def test_the_real_run_refuses_an_unfrozen_rulebook_but_a_trial_may_continue(tmp_path):
    scanner = FakeScanner()
    with pytest.raises(SystemExit, match="has not been frozen"):
        run(tmp_path, scanner, allow_unfrozen=False)
    assert scanner.calls == []
    said = []
    run(tmp_path, scanner, allow_unfrozen=True, say=said.append)
    assert any("TRIAL" in m or "trial" in m for m in said) and len(scanner.calls) == 4


def test_a_frozen_rulebook_is_accepted_and_a_changed_one_is_refused(tmp_path):
    freeze(tmp_path)
    manifest = run(tmp_path, FakeScanner(), allow_unfrozen=False)
    assert manifest.freeze["rulebook_version"] == "2.0.0" and len(manifest.entries) == 4  # the hashes are kept with the run
    (tmp_path / "rules.yaml").write_text("rules: 2\n")  # someone edits a frozen file
    with pytest.raises(SystemExit, match="has changed since the freeze"):
        run(tmp_path, FakeScanner(), allow_unfrozen=False)
    (tmp_path / "rules.yaml").unlink()
    with pytest.raises(SystemExit, match="is missing"):
        run(tmp_path, FakeScanner(), allow_unfrozen=False)
