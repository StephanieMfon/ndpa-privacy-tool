"""Scan the whole corpus under controlled conditions and keep a record of how it went.

    python -m ndpa.evaluation.corpus --name eval-1 --vantage "Port Harcourt, NG (home network)"

The run is resumable (a site that is already done or blocked is not scanned again), polite (a pause between sites, because
repeated visits make blocks more likely), randomised (a fixed seed shuffles the order, so time of day does not line up
with site type), and time-boxed (the plan is to capture everything inside a 72-hour window so sites do not change under
us). A manifest is saved after every site, so a crash or Ctrl+C loses nothing.
"""
import argparse
import hashlib
import json
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path("data/eval.db")
DEFAULT_EVIDENCE = Path("data/eval_evidence")
MANIFEST_DIR = Path("data/eval_runs")
FREEZE_FILE = Path("rulebook/FREEZE.json")
SETTLED = ("done", "blocked")  # a result that does not need repeating


@dataclass
class Manifest:
    name: str
    started_at: str
    seed: int
    vantage: str
    window_hours: float = 72.0
    window_exceeded: bool = False
    freeze: dict = field(default_factory=dict)  # the frozen-file hashes this run was made under
    planned: list[str] = field(default_factory=list)  # every site the run is meant to cover
    entries: dict[str, dict] = field(default_factory=dict)  # site url -> {scan_id, status, started_at, attempts, error}

    def path(self, directory: Path = MANIFEST_DIR) -> Path:
        return directory / f"{self.name}.json"

    def save(self, directory: Path = MANIFEST_DIR) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path(directory).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, name: str, directory: Path = MANIFEST_DIR) -> "Manifest":
        data = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        return cls(**data)


def read_sites(path: Path) -> list[str]:
    """One address per line. Empty lines and lines starting with # are ignored. Duplicates are dropped."""
    seen, sites = set(), []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in seen:
            seen.add(line)
            sites.append(line)
    return sites


def order_sites(sites: list[str], seed: int) -> list[str]:
    """The same seed always gives the same order, so a run can be repeated and explained."""
    shuffled = list(sites)
    random.Random(seed).shuffle(shuffled)
    return shuffled


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def freeze_status(freeze_file: Path = FREEZE_FILE, root: Path = Path(".")) -> tuple[dict, list[str]]:
    """(the freeze record, problems). No problems means every frozen file is exactly as it was frozen."""
    if not freeze_file.exists():
        return {}, [f"{freeze_file} does not exist: the rulebook has not been frozen yet (run eval/freeze_rulebook.py after the pilot)"]
    record = json.loads(freeze_file.read_text(encoding="utf-8"))
    problems = []
    for name, info in record.get("files", {}).items():
        path = root / name
        if not path.exists():
            problems.append(f"{name} is missing")
        elif _sha256(path) != info["sha256"]:
            problems.append(f"{name} has changed since the freeze")
    return record, problems


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_corpus(sites: list[str], name: str, scanner, vantage: str, *, seed: int = 20261106, pause_s: float = 20.0,
               window_hours: float = 72.0, limit: int | None = None, retry_failed: bool = False, allow_unfrozen: bool = False,
               manifest_dir: Path = MANIFEST_DIR, freeze_file: Path = FREEZE_FILE, root: Path = Path("."),
               sleep=time.sleep, now=_now, say=print) -> Manifest:
    """Scan every site not yet settled. scanner(url) must return an object with .scan_id and .status (a ScanStatus)."""
    record, problems = freeze_status(freeze_file, root)
    if problems and not allow_unfrozen:
        raise SystemExit("Refusing to run the evaluation on an unfrozen rulebook:\n  - " + "\n  - ".join(problems) +
                         "\nFor a trial run only, add --allow-unfrozen. Results from a trial run must not be reported.")
    if problems:
        say("WARNING: trial run on an unfrozen rulebook. Do not report these results.")
    manifest_file = manifest_dir / f"{name}.json"
    if manifest_file.exists():
        manifest = Manifest.load(name, manifest_dir)
        if manifest.freeze.get("files") != record.get("files"):
            say("WARNING: the frozen files differ from when this run started. Start a new run name, or restore the files.")
    else:
        manifest = Manifest(name=name, started_at=now().isoformat(timespec="seconds"), seed=seed, vantage=vantage,
                            window_hours=window_hours, freeze=record)
    manifest.planned = list(sites)
    todo = []
    for url in order_sites(sites, manifest.seed):
        status = manifest.entries.get(url, {}).get("status")
        if status in SETTLED or (status == "failed" and not retry_failed):
            continue
        todo.append(url)
    if limit is not None:
        todo = todo[:limit]
    say(f"{len(sites)} sites in the corpus, {len(sites) - len(todo)} settled or skipped, {len(todo)} to scan now")
    for i, url in enumerate(todo):
        if i:
            sleep(pause_s)
        elapsed_h = (now() - datetime.fromisoformat(manifest.started_at)).total_seconds() / 3600
        if elapsed_h > manifest.window_hours and not manifest.window_exceeded:
            manifest.window_exceeded = True
            say(f"WARNING: {elapsed_h:.1f} h since this run started. The {manifest.window_hours:g}-hour window is over: sites scanned "
                "from now on must be reported as outside the window.")
        say(f"[{i + 1}/{len(todo)}] {url}")
        started = now().isoformat(timespec="seconds")
        previous = manifest.entries.get(url, {})
        try:
            summary = scanner(url)
            entry = {"scan_id": summary.scan_id, "status": summary.status.value, "started_at": started, "error": summary.error,
                     "attempts": previous.get("attempts", 0) + 1, "outside_window": manifest.window_exceeded}
        except Exception as exc:  # noqa: BLE001  (one bad site must not stop the other 29)
            entry = {"scan_id": None, "status": "failed", "started_at": started, "error": f"{type(exc).__name__}: {exc}",
                     "attempts": previous.get("attempts", 0) + 1, "outside_window": manifest.window_exceeded}
        manifest.entries[url] = entry
        manifest.save(manifest_dir)  # after every site, so nothing is lost if the run stops
        say(f"    -> {entry['status']}" + (f" ({entry['error']})" if entry["error"] else ""))
    counts = {s: sum(1 for e in manifest.entries.values() if e["status"] == s) for s in ("done", "blocked", "failed")}
    say(f"finished: {counts['done']} done, {counts['blocked']} blocked, {counts['failed']} failed, "
        f"{len(sites) - len(manifest.entries)} not attempted. Manifest: {manifest.path(manifest_dir)}")
    return manifest


def main(argv: list[str] | None = None) -> None:
    from ndpa.capture.run import BrowserConfig
    from ndpa.scan import ScanOptions, run_scan

    ap = argparse.ArgumentParser(description="Scan the evaluation corpus: resumable, polite, randomised, time-boxed.")
    ap.add_argument("--name", required=True, help="a name for this run, e.g. eval-1. Re-run with the same name to resume.")
    ap.add_argument("--vantage", required=True, help='where you are scanning from, e.g. "Port Harcourt, NG (home network)"')
    ap.add_argument("--sites", default="my_site_list.txt")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out-root", default=str(DEFAULT_EVIDENCE))
    ap.add_argument("--pause", type=float, default=20.0, help="seconds between sites (repeated visits make blocks more likely)")
    ap.add_argument("--seed", type=int, default=20261106)
    ap.add_argument("--window-hours", type=float, default=72.0)
    ap.add_argument("--limit", type=int, default=None, help="scan at most this many sites now (for a trial)")
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--allow-unfrozen", action="store_true", help="TRIAL RUNS ONLY: results must not be reported")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--bundled-chromium", action="store_true")
    ap.add_argument("--observe", type=float, default=10.0)
    args = ap.parse_args(argv)
    browser = BrowserConfig(channel=None if args.bundled_chromium else "chrome", headless=args.headless)
    options = ScanOptions(observe_s=args.observe, browser=browser, vantage=args.vantage)

    def scanner(url: str):
        return run_scan(url, Path(args.db), Path(args.out_root), options, say_out=lambda *_: None)

    run_corpus(read_sites(Path(args.sites)), args.name, scanner, args.vantage, seed=args.seed, pause_s=args.pause,
               window_hours=args.window_hours, limit=args.limit, retry_failed=args.retry_failed, allow_unfrozen=args.allow_unfrozen)


if __name__ == "__main__":
    main()
