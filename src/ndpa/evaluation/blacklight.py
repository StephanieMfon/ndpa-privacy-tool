"""Runs Blacklight's open-source collector (The Markup) on a list of sites, as the comparison point for the evaluation.

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
