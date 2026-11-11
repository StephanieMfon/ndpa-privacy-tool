"""Installs Blacklight and scans your pilot sites (second version: fixes the Node 26 failure). Paste this whole file into script.py and run:  python script.py
(running it again is harmless: finished sites are kept, failed ones are tried again)

It writes the runner and its tests, adds slot.ng to your pilot list, records the decision, then downloads Blacklight (pinned to the
version I tested), installs it, and scans the pilot sites in your real Chrome. A Chrome window opens for each scan: leave it alone.
Add --no-run to only write the files.
"""
import pathlib
import py_compile
import subprocess
import sys

FILES = {
    "src/ndpa/evaluation/blacklight.py": r'''"""Runs Blacklight's open-source collector (The Markup) on a list of sites, as the comparison point for the evaluation.

    python -m ndpa.evaluation.blacklight pilot      the pilot sites (eval/pilot_sites.txt) into eval/blacklight/pilot
    python -m ndpa.evaluation.blacklight corpus     the 30-site corpus (my_site_list.txt) into eval/blacklight/corpus

The first run installs the collector (a pinned version) next to the results. A site that already has a result is skipped, so a
run can be repeated safely. Settings are fixed in advance so the comparison is fair: homepage only, a 1366 x 768 desktop window,
the real Chrome, run from this machine (see ndpa.capture for the same conditions in the main tool).
"""
import csv
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ndpa.analyse.trackers import registrable_domain
from ndpa.evaluation.corpus import read_sites
from ndpa.urls import host_of

COLLECTOR_REPO = "https://github.com/the-markup/blacklight-collector.git"
PINNED_COMMIT = "fe046f914ba87b131b86dc1f8029fffa0b70de44"  # version 3.11.0, the one this was tested with
BASE = Path("eval/blacklight")
MODES = {"pilot": (Path("eval/pilot_sites.txt"), BASE / "pilot"), "corpus": (Path("my_site_list.txt"), BASE / "corpus")}
VANTAGE = "Port Harcourt, NG (home network)"
PAUSE_S = float(os.environ.get("BLACKLIGHT_PAUSE", "10"))
SITE_TIMEOUT_S = 240
MIN_NODE = 20

# The scan settings, fixed in advance. numPages is the number of EXTRA pages after the homepage, so 0 means homepage only.
RUNNER_JS = """// Scans one site with Blacklight. usage: node run_scan.js <url> <outDir> <chromePath> <chromeMajor> <vantage>
// The collector empties outDir first, so every site gets its own folder.
(async () => {
  let collect;
  try {
    ({ collect } = require('./blacklight-collector/build'));
  } catch (e) {
    console.log('RESULT ' + JSON.stringify({ status: 'failed', page_response: 'Could not load Blacklight: ' + String((e && e.message) || e).split('\\n')[0] }));
    process.exit(0);
  }
  const [url, outDir, chromePath, major, vantage] = process.argv.slice(2);
  const result = await collect(url, {
    numPages: 0,
    headless: false,
    outDir,
    puppeteerExecutablePath: chromePath,
    emulateDevice: {
      viewport: { width: 1366, height: 768 },
      userAgent: `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${major}.0.0.0 Safari/537.36`,
    },
    captureHar: true,
    saveScreenshots: true,
    clearCache: true,
    defaultTimeout: 30000,
    quiet: true,
    location: vantage,
  });
  console.log('RESULT ' + JSON.stringify({ status: result.status, page_response: result.page_response ? String(result.page_response) : '' }));
  process.exit(0);
})().catch((e) => {
  console.log('RESULT ' + JSON.stringify({ status: 'failed', page_response: String(e.message || e) }));
  process.exit(0);
});
"""

COLUMNS = ["site", "status", "note", "final_url", "tracker_requests", "tracker_domains", "tracker_domain_list", "cookies", "third_party_cookies",
           "key_logging", "session_recorders", "canvas_fingerprinting", "facebook_pixel_events", "google_analytics_events", "browser", "scanned_at"]


def node_major(version_text: str) -> int | None:
    m = re.match(r"v?(\d+)\.", version_text.strip())
    return int(m.group(1)) if m else None


def find_chrome() -> Path | None:
    """The real Chrome: BLACKLIGHT_CHROME if set, else the usual places."""
    candidates = [os.environ.get("BLACKLIGHT_CHROME", ""), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    candidates += [shutil.which(n) or "" for n in ("google-chrome", "google-chrome-stable", "chromium")]
    return next((Path(c) for c in candidates if c and Path(c).exists()), None)


def chrome_major(chrome: Path) -> tuple[int, str]:
    """The Chrome version, read from the app's own metadata on a Mac (instant), otherwise by asking Chrome."""
    text = ""
    plist = next((p / "Contents" / "Info.plist" for p in chrome.parents if p.suffix == ".app"), None)
    if plist and plist.exists():
        with open(plist, "rb") as f:
            text = f"Google Chrome {plistlib.load(f).get('CFBundleShortVersionString', '')}"
    else:
        try:
            text = subprocess.run([str(chrome), "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass
    m = re.search(r"(\d+)\.\d+\.\d+\.\d+", text)
    if not m:
        raise RuntimeError(f"Could not read the version of {chrome}. Is it a working Chrome?")
    return int(m.group(1)), text


NODE_PRIVATE = ["npx", "--yes", "node@22"]  # a private Node 22, fetched on demand; your own Node is not changed
LOAD_CHECK = "require('./blacklight-collector/build'); console.log('loads')"


def first_line(text: str) -> str:
    """The start of an error message (the useful part), not the tail of a stack trace."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    named = next((ln for ln in lines if re.match(r"[A-Za-z]*Error\b", ln)), None)  # a line that STARTS with 'Error:' or 'TypeError:'
    return (named or (lines[0] if lines else "no message"))[:300]


def node_command(base: Path) -> tuple[list[str] | None, str]:
    """A way to start Node that can really load Blacklight. Blacklight is built for Node 22; some newer Node versions cannot load its
    libraries (Node 26 fails inside yargs), so if yours cannot, a private Node 22 is used. Returns (command, what to tell the user)."""
    candidates = ([[os.environ["BLACKLIGHT_NODE"]]] if os.environ.get("BLACKLIGHT_NODE") else []) + [["node"], NODE_PRIVATE]
    last = "nothing worked"
    for cmd in candidates:
        try:
            result = subprocess.run(cmd + ["-e", LOAD_CHECK], cwd=base, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as error:
            last = f"{cmd[0]}: {error}"
            continue
        if result.returncode == 0 and "loads" in result.stdout:
            return cmd, ("using your Node" if cmd == ["node"] else "using a private Node 22 (your Node cannot load Blacklight's libraries)" if cmd == NODE_PRIVATE else f"using {cmd[0]}")
        last = f"{' '.join(cmd)}: {first_line(result.stderr or result.stdout)}"
    return None, last


def problems_with_tools() -> list[str]:
    out = []
    for tool in ("git", "node", "npm"):
        if not shutil.which(tool):
            out.append(f"'{tool}' is not installed." + (" Install Node 22 from https://nodejs.org (the LTS installer is fine), then open a new terminal." if tool != "git" else ""))
    if shutil.which("node"):
        major = node_major(subprocess.run(["node", "-v"], capture_output=True, text=True).stdout)
        if major is None or major < MIN_NODE:
            out.append(f"Node {MIN_NODE} or newer is needed (found {major}). Install Node 22 from https://nodejs.org.")
    if not find_chrome():
        out.append("Google Chrome was not found. Install it, or set BLACKLIGHT_CHROME to its full path.")
    return out


def run(cmd: list[str], cwd: Path, env: dict | None = None, timeout: int = 900) -> None:
    result = subprocess.run(cmd, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"'{' '.join(cmd)}' failed:\n{(result.stderr or result.stdout)[-1500:]}")


def setup(base: Path = BASE) -> Path:
    """Installs the pinned collector next to the results. Safe to repeat."""
    base.mkdir(parents=True, exist_ok=True)
    collector = base / "blacklight-collector"
    if not collector.exists():
        print("  downloading the Blacklight collector ...")
        run(["git", "clone", "--quiet", COLLECTOR_REPO, collector.name], base)
        run(["git", "checkout", "--quiet", PINNED_COMMIT], collector)
    if not (collector / "node_modules").exists():
        print("  installing its libraries (a few minutes the first time) ...")
        run(["npm", "install", "--no-audit", "--no-fund"], collector, env={"PUPPETEER_SKIP_DOWNLOAD": "1"})  # it uses your Chrome, not its own
    if not (collector / "build" / "index.js").exists():
        print("  building it ...")
        run(["npm", "run", "build"], collector)
    (base / "run_scan.js").write_text(RUNNER_JS, encoding="utf-8")
    return collector


def count(value) -> int:
    return len(value) if hasattr(value, "__len__") else 0


def summarise(site_dir: Path) -> dict:
    """One row of numbers from a site's inspection.json. A missing or unreadable file is a failed scan."""
    path = site_dir / "inspection.json"
    if not path.exists():
        reason = site_dir / "error.txt"  # written when a scan fails, so the summary can say why
        return {"status": "failed", "note": reason.read_text(encoding="utf-8").splitlines()[0] if reason.exists() and reason.read_text(encoding="utf-8").strip() else "no result file"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"status": "failed", "note": "unreadable result file"}
    reports = data.get("reports") or {}
    trackers = reports.get("third_party_trackers") or []
    domains = sorted({registrable_domain(e["url"]) for e in trackers if isinstance(e, dict) and e.get("url")} - {""})
    cookies = reports.get("cookies") or []
    browser = data.get("browser") or {}
    return {
        "status": "done", "note": "", "final_url": data.get("uri_dest", ""),
        "tracker_requests": count(trackers), "tracker_domains": len(domains), "tracker_domain_list": " ".join(domains),
        "cookies": count(cookies), "third_party_cookies": sum(1 for c in cookies if isinstance(c, dict) and c.get("third_party")),
        "key_logging": "yes" if count(reports.get("key_logging")) else "no", "session_recorders": "yes" if count(reports.get("session_recorders")) else "no",
        "canvas_fingerprinting": "yes" if count(reports.get("canvas_fingerprinters")) else "no",
        "facebook_pixel_events": count(reports.get("fb_pixel_events")), "google_analytics_events": count(reports.get("google_analytics_events")),
        "browser": browser.get("version", ""), "scanned_at": data.get("end_time", ""),
    }


def failed(site_dir: Path, note: str, full: str = "") -> dict:
    (site_dir / "error.txt").write_text(note + "\n" + (full[-3000:] if full else ""), encoding="utf-8")
    return {"status": "failed", "note": note}


def scan_site(url: str, site_dir: Path, base: Path, chrome: Path, major: int, node: list[str] | None = None) -> dict:
    site_dir.mkdir(parents=True, exist_ok=True)
    cmd = [*(node or ["node"]), str((base / "run_scan.js").resolve()), url, str(site_dir.resolve()), str(chrome), str(major), VANTAGE]
    try:
        result = subprocess.run(cmd, cwd=base, capture_output=True, text=True, timeout=SITE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return failed(site_dir, f"no answer after {SITE_TIMEOUT_S} s")
    line = next((ln for ln in result.stdout.splitlines() if ln.startswith("RESULT ")), "")
    outcome = json.loads(line[7:]) if line else {"status": "failed", "page_response": first_line(result.stderr or "no answer")}
    if outcome.get("status") != "success":
        return failed(site_dir, (outcome.get("page_response") or "the scan failed").replace("\n", " ")[:300], result.stderr)
    (site_dir / "error.txt").unlink(missing_ok=True)
    return summarise(site_dir)


def write_summary(out_dir: Path, sites: list[str]) -> list[dict]:
    rows = []
    for url in sites:
        row = {"site": url, **summarise(out_dir / host_of(url))}
        rows.append(row)
    with open(out_dir / "summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def write_version_record(out_dir: Path, chrome: Path, chrome_text: str, node: list[str] | None = None) -> None:
    node = subprocess.run([*(node or ["node"]), "-v"], capture_output=True, text=True).stdout.strip()
    (out_dir / "VERSION.txt").write_text(
        f"Blacklight collector {PINNED_COMMIT} (version 3.11.0)\nNode {node}\n{chrome_text}\n{platform.platform()}\nvantage: {VANTAGE}\n"
        f"settings: homepage only (numPages 0), desktop window 1366 x 768, real Chrome with a window, defaults for everything else\n"
        f"written: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    mode = args[0] if args else "pilot"
    if mode not in MODES:
        print(f"Say which sites: {' or '.join(MODES)}.  Example: python -m ndpa.evaluation.blacklight pilot")
        return 2
    sites_file, out_dir = MODES[mode]
    problems = problems_with_tools()
    if problems:
        print("Not ready yet:\n  - " + "\n  - ".join(problems))
        return 1
    sites = read_sites(sites_file)
    if not sites:
        print(f"No sites in {sites_file}.")
        return 1
    setup()
    chrome = find_chrome()
    try:
        major, chrome_text = chrome_major(chrome)
    except RuntimeError as error:
        print(error)
        return 1
    node, how = node_command(BASE)
    if node is None:
        print(f"Blacklight could not be started with any Node: {how}\n"
              "Install Node 22 (for example 'brew install node@22'), then run again with its path, e.g.\n"
              "  BLACKLIGHT_NODE=/opt/homebrew/opt/node@22/bin/node python script.py")
        return 1
    print(f"  {how}")
    out_dir.mkdir(parents=True, exist_ok=True)
    write_version_record(out_dir, chrome, chrome_text, node)
    print(f"\n{len(sites)} site(s) from {sites_file}, with {chrome_text}. A Chrome window opens for each scan; leave it alone.")
    scanned = 0
    for i, url in enumerate(sites, start=1):
        site_dir = out_dir / host_of(url)
        if (site_dir / "inspection.json").exists():
            print(f"[{i}/{len(sites)}] {url}\n    -> already scanned (kept)")
            continue
        if scanned:
            time.sleep(PAUSE_S)  # polite pause between sites
        print(f"[{i}/{len(sites)}] {url}")
        row = scan_site(url, site_dir, BASE, chrome, major, node)
        scanned += 1
        print("    -> " + (f"done ({row['tracker_requests']} tracker requests, {row['third_party_cookies']} third-party cookies)" if row["status"] == "done" else f"FAILED: {row['note']}"))
    rows = write_summary(out_dir, sites)
    done = sum(r["status"] == "done" for r in rows)
    print(f"\nfinished: {done} done, {len(rows) - done} failed or missing. Summary: {out_dir / 'summary.csv'}")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
''',
    "tests/unit/test_blacklight.py": r'''import csv
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
''',
}

EXPECTED_LINES = {
    "src/ndpa/evaluation/blacklight.py": 293,
    "tests/unit/test_blacklight.py": 177,
}


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def append_once(path, marker, text):
    if marker in read(path):
        print("  already there:", path, "|", marker)
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
    print("  added to:", path, "|", marker)


# 1. The runner and its tests
problems = []
for name, text in FILES.items():
    target = pathlib.Path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    if len(read(name).splitlines()) != EXPECTED_LINES[name]:
        problems.append(f"{name}: {len(read(name).splitlines())} lines, expected {EXPECTED_LINES[name]}")
    try:
        py_compile.compile(name, doraise=True)
    except py_compile.PyCompileError as error:
        problems.append(f"{name}: does not compile ({error.msg.splitlines()[-1]})")
assert not problems, "The paste was not complete:\n  " + "\n  ".join(problems) + "\nPaste the whole script again."
print(f"wrote {len(FILES)} files, all complete and compiling")

# 2. slot.ng is the third pilot site (it is not in the evaluation corpus)
pilot = pathlib.Path("eval/pilot_sites.txt")
text = read(pilot)
if "slot.ng" in text:
    print("  already there: slot.ng in", pilot)
else:
    old = "# Add a third site that is not in my_site_list.txt, for example another online shop or a news site.\n"
    text = text.replace(old, "") if old in text else text
    pilot.write_text(text.rstrip("\n") + "\nhttps://slot.ng\n", encoding="utf-8")
    print("  added: https://slot.ng to", pilot)

# 3. Keep the downloaded collector and the bulky files out of git (the result JSON and the summary stay)
append_once(".gitignore", "eval/blacklight/blacklight-collector/", """
# Blacklight comparison: the downloaded collector and the bulky files. The result JSON and summary.csv are kept.
eval/blacklight/blacklight-collector/
eval/blacklight/**/requests.har
eval/blacklight/**/*.html
eval/blacklight/**/*.jpeg
eval/blacklight/**/inspection-log.ndjson
""")

# 4. Decisions and backlog
append_once("docs/decisions.md", "D-62", """
## Update 9 Nov 2026 (comparison point)

- D-62 The comparison point is Blacklight's open-source collector (The Markup, version 3.11.0, commit fe046f9), which replaces Cookiescanner (B-41 is closed). Cookiescanner needs Debian, PostgreSQL and Docker, needed a code change to run (NumPy 2 removed numpy.Infinity), and its authors say it may no longer work. Blacklight installs and builds unchanged, is maintained (last release June 2026), and covers the pre-consent tracker and cookie rules (TR-01, SB-03, parts of CN-02 and SB-02) instead of only two banner rules. The collector decides what a tracker is with EasyList and EasyPrivacy, so its tracker definition is independent of ours (the DuckDuckGo list). Limits to state: it never clicks a banner, so it is compared with the no-interaction run only; it types test text into form fields but never submits; it has no peer-reviewed paper of its own (a published methodology, built on OpenWPM).
- D-63 Blacklight scan settings, fixed in advance: homepage only (numPages 0), a 1366 x 768 desktop window, the real Chrome with a window, run from the home network, collector defaults for everything else, one site at a time with a 10 second pause. The corpus run happens inside the same 72-hour window as the tool's scans.
""")
append_once("docs/decisions.md", "D-64", """
- D-64 Blacklight is started with a private Node 22 (fetched with npx, nothing installed on the system) when the installed Node cannot load it. Found on 9 Nov 2026: with Node 26.6.0, a library inside Blacklight (Puppeteer's yargs) fails to load, while Node 22, the version Blacklight targets, works. The Node version used is recorded in eval/blacklight/pilot/VERSION.txt.
""")
append_once("docs/backlog.md", "B-56", """
## Added 9 Nov 2026 (comparison point)
- B-56 Chapter wording: Objective D (Chapter 1) and step D3 (Chapter 3) name Cookiescanner. Change them to Blacklight after telling the supervisor, and cite The Markup's methodology page and OpenWPM (Englehardt & Narayanan, 2016). One sentence may say Cookiescanner was tried and could not be run without changes.
- B-57 Comparison design: for each site, 'a tracker was contacted before consent' from the tool (SB-03), from Blacklight (at least one tracker request) and from the annotators (SB-03 label, the reference). Report precision and recall for both tools, and how many tracker domains each found.
- B-58 After the freeze, run python -m ndpa.evaluation.blacklight corpus inside the same 72-hour window as the tool's corpus scan.
""")

# 5. Install Blacklight and scan the pilot sites
if "--no-run" in sys.argv:
    print("\nDone (files only). To install and scan:  python -m ndpa.evaluation.blacklight pilot")
    sys.exit(0)
print("\nNow installing Blacklight and scanning the pilot sites. Chrome windows will open: leave them alone.\n")
code = subprocess.run([sys.executable, "-m", "ndpa.evaluation.blacklight", "pilot"]).returncode
print("\nResults: eval/blacklight/pilot/summary.csv" if code == 0 else "\nSomething needs attention, see above. Fix it and run  python script.py  again.")
sys.exit(code)