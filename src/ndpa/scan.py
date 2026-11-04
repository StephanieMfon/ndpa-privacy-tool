"""One scan, start to finish (decision D-32: one scan is one process).

Three capture runs, privacy policy discovery, the 17 rules, the score, SQLite storage and the sealed evidence folder.

Usage:
    python -m ndpa.scan https://example.com.ng [--observe 10] [--headless] [--bundled-chromium] [--vantage "Port Harcourt, NG"]
"""
import argparse
import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ndpa.analyse.trackers import SNAPSHOT, TrackerList
from ndpa.capture.policy import capture_policy
from ndpa.capture.run import BrowserConfig, capture_run
from ndpa.evidence import chain
from ndpa.models import Condition, RunResult, RunStatus, ScanStatus, ScoreCard
from ndpa.remediation.fixes import fix_first
from ndpa.rules.context import NecessaryCookies
from ndpa.rules.engine import evaluate, load_scan
from ndpa.scoring.score import RULEBOOK_PATH, load_rulebook, scan_status, score
from ndpa.storage import db
from ndpa.urls import host_of

CONDITIONS = (Condition.NO_ACTION, Condition.ACCEPT, Condition.REJECT)


@dataclass
class ScanOptions:
    observe_s: float = 10.0
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    vantage: str = "unspecified"
    attempts: int = 2          # a network failure gets one retry; a blocked scan is never retried
    retry_pause_s: float = 20.0


@dataclass
class ScanSummary:
    scan_id: int
    status: ScanStatus
    folder: Path
    card: ScoreCard
    manifest_hash: str | None
    error: str | None = None


def _sha256_file(path: Path) -> str | None:
    return chain.sha256_file(path) if path.exists() else None


def _tool_version() -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, timeout=10)
        if commit.returncode != 0:
            return "unknown"
        return commit.stdout.strip() + ("+uncommitted changes" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _capture(url, folder, condition, opts, trackers, say) -> tuple[RunResult, int]:
    out_dir, attempts = folder / condition.value, 0
    while True:
        attempts += 1
        shutil.rmtree(out_dir, ignore_errors=True)  # a retry replaces the failed attempt
        result = capture_run(url, out_dir, condition, opts.observe_s, opts.browser, trackers)
        if result.status != RunStatus.FAILED or attempts >= opts.attempts:
            return result, attempts
        say(condition.value, f"failed ({result.error}); trying again in {opts.retry_pause_s:g} s")
        time.sleep(opts.retry_pause_s)


def run_scan(url: str, db_path: Path = db.DEFAULT_DB, out_root: Path = Path("data/evidence"),
             opts: ScanOptions | None = None, trackers: TrackerList | None = None, say_out=print,
             scan_id: int | None = None) -> ScanSummary:
    """Scan one site. Pass scan_id when the dashboard has already created the (queued) scan row."""
    opts = opts or ScanOptions()
    if trackers is None and SNAPSHOT.exists():
        trackers = TrackerList()
    host = host_of(url)
    folder = out_root / host / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    folder.mkdir(parents=True, exist_ok=True)

    conn = db.connect(db_path)
    rulebook = load_rulebook()
    env = dict(tool_version=_tool_version(), rulebook_version=str(rulebook.get("meta", {}).get("version", "unknown")),
               rulebook_sha256=_sha256_file(RULEBOOK_PATH), tracker_list_sha256=_sha256_file(SNAPSHOT))
    if scan_id is None:
        scan_id = db.insert_scan(conn, url, host, str(folder), opts.vantage, **env)
    else:
        db.update_scan(conn, scan_id, status="running", started_at=db.now(), folder=str(folder), **env)

    def say(stage: str, message: str = "") -> None:
        db.log_progress(conn, scan_id, stage, message)
        say_out(f"[{stage}] {message}".rstrip())

    runs: dict[Condition, RunResult] = {}
    attempts: dict[Condition, int] = {}
    error: str | None = None
    try:
        for condition in CONDITIONS:
            if condition != Condition.NO_ACTION and runs[Condition.NO_ACTION].status != RunStatus.OK:
                break
            say(condition.value, "capturing")
            runs[condition], attempts[condition] = _capture(url, folder, condition, opts, trackers, say)
            say(condition.value, runs[condition].status.value)
        if runs[Condition.NO_ACTION].status == RunStatus.OK:
            say("policy", "looking for the privacy and cookie policies")
            found = capture_policy(url, folder / "policy", opts.browser)
            say("policy", found.discovery_status)
        status = scan_status(runs[Condition.NO_ACTION].status)
        say("rules", "evaluating")
        ev = load_scan(folder)
        results = evaluate(ev, NecessaryCookies.load(), trackers)
        card = score(results, rulebook, status)
        fixes = fix_first(results, rulebook)
    except Exception as exc:  # noqa: BLE001  (for example Chrome is not installed)
        error, status = f"{type(exc).__name__}: {exc}", ScanStatus.FAILED
        results, fixes = [], []
        card = score([], rulebook, status)
        say("error", error)

    rules = {r["id"]: r for r in rulebook["rules"]}
    rows = [{"rule_id": r.rule_id, "tier": rules[r.rule_id]["tier"], "category": rules[r.rule_id]["category"],
             "outcome": r.outcome.value, "instances_failed": r.instances_failed, "instances_total": r.instances_total,
             "root_cause": r.root_cause, "note": r.note, "evidence": r.evidence} for r in results]
    browser_version = next((r.browser_version for r in runs.values() if r.browser_version), None)
    (folder / "results.json").write_text(json.dumps(
        {"status": status.value, "rules": rows, "score": card.model_dump(mode="json"), "fix_first": fixes}, indent=2),
        encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps(
        {"url": url, "host": host, "status": status.value, "vantage": opts.vantage, "browser_version": browser_version,
         "attempts": {c.value: n for c, n in attempts.items()}, "observe_s": opts.observe_s,
         "evidence_written_at": db.now(), "error": error}, indent=2), encoding="utf-8")

    say("saving", "storing results and sealing the evidence")
    for condition, run in runs.items():
        db.insert_run(conn, scan_id, run, attempts[condition])
    db.insert_findings(conn, scan_id, rows)
    db.insert_score(conn, scan_id, card)
    shutil.copy(Path(chain.__file__), folder / chain.VERIFIER)
    manifest = chain.build_manifest(folder)
    db.insert_artifacts(conn, scan_id, manifest["entries"])
    db.update_scan(conn, scan_id, status=status.value, finished_at=db.now(), manifest_hash=manifest["final"],
                   browser_version=browser_version, error=error)
    say("done", status.value)
    conn.close()
    return ScanSummary(scan_id, status, folder, card, manifest["final"], error)


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan one site: three runs, policy, rules, score, SQLite, sealed evidence.")
    ap.add_argument("url")
    ap.add_argument("--observe", type=float, default=10.0)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--bundled-chromium", action="store_true")
    ap.add_argument("--vantage", default="unspecified", help='where the scan runs from, e.g. "Port Harcourt, NG"')
    ap.add_argument("--db", default=str(db.DEFAULT_DB))
    ap.add_argument("--out-root", default="data/evidence", help="where evidence folders are written")
    ap.add_argument("--scan-id", type=int, default=None, help="use a scan row the dashboard already created")
    args = ap.parse_args()
    cfg = BrowserConfig(channel=None if args.bundled_chromium else "chrome", headless=args.headless)
    summary = run_scan(args.url, Path(args.db), Path(args.out_root),
                       opts=ScanOptions(observe_s=args.observe, browser=cfg, vantage=args.vantage), scan_id=args.scan_id)
    card = summary.card
    print()
    print(f"scan #{summary.scan_id}: {summary.status.value}" + (f" ({summary.error})" if summary.error else ""))
    if card.score_weighted is not None:
        print(f"score {card.score_weighted}, risk band {card.band}, coverage {card.coverage:.0%}, "
              f"based on {card.scored_weight:g} of {card.total_weight:g} points")
    elif card.note:
        print(card.note)
    print(f"evidence: {summary.folder}")
    print(f"details:  python -m ndpa.rules.engine {summary.folder}")
    print(f"verify:   python {summary.folder / chain.VERIFIER} --expect {summary.manifest_hash}")


if __name__ == "__main__":
    main()
