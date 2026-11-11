import csv
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ndpa.evaluation import blacklight as bl


def write_result(site_dir: Path, reports: dict, **extra) -> None:
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "inspection.json").write_text(json.dumps({"uri_dest": "https://shop.example/", "browser": {"version": "Chrome/156"}, "end_time": "2026-11-09T10:00:00Z", "reports": reports, **extra}))


REPORTS = {
    "third_party_trackers": [{"url": "https://www.google-analytics.com/collect?x=1"}, {"url": "https://stats.g.doubleclick.net/j/collect"}, {"url": "https://connect.facebook.net/en_US/fbevents.js"},
                             {"url": "https://www.google-analytics.com/g/collect"}],
    "cookies": [{"name": "_ga", "domain": ".shop.example", "third_party": False}, {"name": "IDE", "domain": ".doubleclick.net", "third_party": True}, {"name": "fr", "domain": ".facebook.com", "third_party": True}],
    "key_logging": {}, "session_recorders": [], "canvas_fingerprinters": [{"script": "x"}], "fb_pixel_events": [{}], "google_analytics_events": [],
}


def test_a_result_is_summarised_into_counts_and_domains(tmp_path):
    write_result(tmp_path / "shop.example", REPORTS)
    row = bl.summarise(tmp_path / "shop.example")
    assert row["status"] == "done" and row["final_url"] == "https://shop.example/" and row["browser"] == "Chrome/156"
    assert row["tracker_requests"] == 4 and row["tracker_domains"] == 3 and row["tracker_domain_list"] == "doubleclick.net facebook.net google-analytics.com"
    assert row["cookies"] == 3 and row["third_party_cookies"] == 2
    assert (row["key_logging"], row["session_recorders"], row["canvas_fingerprinting"]) == ("no", "no", "yes")
    assert row["facebook_pixel_events"] == 1 and row["google_analytics_events"] == 0


def test_a_missing_or_broken_result_counts_as_failed(tmp_path):
    assert bl.summarise(tmp_path / "nothing")["status"] == "failed"
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "inspection.json").write_text("{not json")
    assert bl.summarise(tmp_path / "broken") == {"status": "failed", "note": "unreadable result file"}
    write_result(tmp_path / "empty", {})
    assert bl.summarise(tmp_path / "empty")["tracker_requests"] == 0  # a clean site is a real result, not a failure


def test_the_scan_settings_are_the_ones_fixed_in_advance():
    js = bl.RUNNER_JS
    for fixed in ("numPages: 0", "headless: false", "width: 1366", "height: 768", "captureHar: true", "clearCache: true", "puppeteerExecutablePath: chromePath"):
        assert fixed in js, fixed  # changing any of these changes what the comparison means
    assert "iPhone" not in js


@pytest.mark.skipif(not shutil.which("node"), reason="Node is not installed here")
def test_the_runner_is_valid_javascript(tmp_path):
    (tmp_path / "run_scan.js").write_text(bl.RUNNER_JS)
    assert subprocess.run(["node", "--check", str(tmp_path / "run_scan.js")], capture_output=True).returncode == 0


def test_node_versions_are_read_and_chrome_can_be_named(tmp_path, monkeypatch):
    assert bl.node_major("v22.22.2\n") == 22 and bl.node_major("v18.0.0") == 18 and bl.node_major("nonsense") is None
    fake = tmp_path / "my-chrome"
    fake.write_text("x")
    monkeypatch.setenv("BLACKLIGHT_CHROME", str(fake))
    assert bl.find_chrome() == fake


def test_scan_site_records_each_kind_of_failure_and_a_success(tmp_path, monkeypatch):
    def fake_run(stdout="", stderr="", raises=None):
        def run(*a, **k):
            if raises:
                raise raises
            return subprocess.CompletedProcess(a, 0, stdout, stderr)
        return run

    base, chrome = tmp_path, tmp_path / "chrome"
    monkeypatch.setattr(bl.subprocess, "run", fake_run('RESULT {"status": "failed", "page_response": "Timed out while waiting"}\n'))
    assert bl.scan_site("https://a.example", tmp_path / "a", base, chrome, 156) == {"status": "failed", "note": "Timed out while waiting"}
    assert bl.summarise(tmp_path / "a") == {"status": "failed", "note": "Timed out while waiting"}  # the reason is kept for the summary file
    monkeypatch.setattr(bl.subprocess, "run", fake_run("", "boom"))
    assert "boom" in bl.scan_site("https://a.example", tmp_path / "a", base, chrome, 156)["note"]
    monkeypatch.setattr(bl.subprocess, "run", fake_run(raises=subprocess.TimeoutExpired("node", 1)))
    assert "no answer" in bl.scan_site("https://a.example", tmp_path / "a", base, chrome, 156)["note"]
    write_result(tmp_path / "ok", REPORTS)
    monkeypatch.setattr(bl.subprocess, "run", fake_run('noise\nRESULT {"status": "success"}\n'))
    assert bl.scan_site("https://ok.example", tmp_path / "ok", base, chrome, 156)["status"] == "done"


def test_a_run_skips_finished_sites_records_failures_and_writes_the_summary(tmp_path, monkeypatch, capsys):
    sites = tmp_path / "sites.txt"
    sites.write_text("# comment\nhttps://done.example\nhttps://bad.example\nhttps://good.example\n")
    out = tmp_path / "out"
    write_result(out / "done.example", REPORTS)  # scanned on an earlier run
    called = []

    def fake_scan(url, site_dir, base, chrome, major, node):
        called.append(url)
        if "bad" in url:
            return {"status": "failed", "note": "Chrome crashed"}
        write_result(site_dir, {"third_party_trackers": [], "cookies": []})
        return bl.summarise(site_dir)

    monkeypatch.setitem(bl.MODES, "pilot", (sites, out))
    monkeypatch.setattr(bl, "problems_with_tools", lambda: [])
    monkeypatch.setattr(bl, "node_command", lambda base: (["node"], "using your Node"))
    monkeypatch.setattr(bl, "setup", lambda *a: tmp_path)
    monkeypatch.setattr(bl, "find_chrome", lambda: tmp_path / "chrome")
    monkeypatch.setattr(bl, "chrome_major", lambda c: (156, "Google Chrome 156.0.8078.80"))
    monkeypatch.setattr(bl, "write_version_record", lambda *a: None)
    monkeypatch.setattr(bl, "scan_site", fake_scan)
    monkeypatch.setattr(bl, "PAUSE_S", 0)
    assert bl.main(["pilot"]) == 0
    said = capsys.readouterr().out
    assert called == ["https://bad.example", "https://good.example"] and "already scanned (kept)" in said and "FAILED: Chrome crashed" in said
    rows = list(csv.DictReader(open(out / "summary.csv")))
    assert [(r["site"], r["status"]) for r in rows] == [("https://done.example", "done"), ("https://bad.example", "failed"), ("https://good.example", "done")]
    assert bl.main(["pilot"]) == 0 and called == ["https://bad.example", "https://good.example", "https://bad.example"]  # only the failed one is tried again


def test_a_run_explains_what_is_missing_and_rejects_an_unknown_mode(monkeypatch, capsys):
    monkeypatch.setattr(bl, "problems_with_tools", lambda: ["'node' is not installed."])
    assert bl.main(["pilot"]) == 1 and "'node' is not installed." in capsys.readouterr().out
    assert bl.main(["nonsense"]) == 2


def test_pilot_and_corpus_results_go_to_separate_folders():
    assert bl.MODES["pilot"][1] != bl.MODES["corpus"][1] and str(bl.MODES["corpus"][0]) == "my_site_list.txt"


def test_the_chrome_version_comes_from_the_app_file_on_a_mac_and_a_bad_chrome_is_explained(tmp_path):
    import plistlib

    app = tmp_path / "Google Chrome.app" / "Contents"
    (app / "MacOS").mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "156.0.8078.80"}))
    binary = app / "MacOS" / "Google Chrome"
    binary.write_text("not run")
    assert bl.chrome_major(binary) == (156, "Google Chrome 156.0.8078.80")  # no process is started
    broken = tmp_path / "broken-chrome"
    broken.write_text("#!/bin/sh\necho nonsense\n")
    broken.chmod(0o755)
    with pytest.raises(RuntimeError, match="Could not read the version"):
        bl.chrome_major(broken)


def test_a_node_that_cannot_load_blacklight_is_replaced_by_a_private_node_22(monkeypatch, tmp_path):
    calls = []
    node26 = "node:internal/modules/cjs/loader:1569\n  const err = new Error(message);\nError: Cannot find module './build/index.cjs'\n    at Module._resolveFilename\n"

    def fake_run(cmd, **kw):
        calls.append(list(cmd[:3]))
        if cmd[0] == "node":  # the situation on a Mac with Node 26: a library inside Blacklight cannot be loaded
            return subprocess.CompletedProcess(cmd, 1, "", node26)
        return subprocess.CompletedProcess(cmd, 0, "loads\n", "")

    monkeypatch.delenv("BLACKLIGHT_NODE", raising=False)
    monkeypatch.setattr(bl.subprocess, "run", fake_run)
    command, how = bl.node_command(tmp_path)
    assert command == bl.NODE_PRIVATE and "private Node 22" in how and calls[0][0] == "node" and calls[1] == ["npx", "--yes", "node@22"]
    monkeypatch.setattr(bl.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Error: boom\n    at x"))
    command, why = bl.node_command(tmp_path)
    assert command is None and "Error: boom" in why  # nothing works: the reason is explained
    monkeypatch.setattr(bl.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "loads\n", ""))
    assert bl.node_command(tmp_path)[0] == ["node"]  # your own Node is used when it works
    monkeypatch.setenv("BLACKLIGHT_NODE", "/x/node22")
    assert bl.node_command(tmp_path)[0] == ["/x/node22"]  # and one you name wins


def test_an_error_is_reported_by_its_first_line_and_kept_in_full(tmp_path):
    trace = "node:internal/modules/cjs/loader:1569\n  const err = new Error(message);\n  ^\n\nError: Cannot find module './build/index.cjs'\n    at Module._resolveFilename\n" + "    at x\n" * 50
    assert bl.first_line(trace) == "Error: Cannot find module './build/index.cjs'" and bl.first_line("") == "no message"
    row = bl.failed(tmp_path, "short note", trace)
    assert row["note"] == "short note" and "Module._resolveFilename" in (tmp_path / "error.txt").read_text()
    assert bl.summarise(tmp_path) == {"status": "failed", "note": "short note"}  # the summary shows only the first line


def test_the_runner_reports_a_loading_failure_instead_of_crashing():
    js = bl.RUNNER_JS
    assert "const { collect } = require" not in js and "Could not load Blacklight" in js
    assert js.index("require('./blacklight-collector/build')") < js.index("RESULT")
