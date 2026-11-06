"""The evaluation harness. Paste this whole file into script.py and run:  python script.py

It writes ten new files (the harness and its tests), then checks that every file arrived complete and compiles.
Nothing existing is overwritten except small additions to README.md, docs/ and .gitignore.
"""
import pathlib
import py_compile

FILES = {
    "src/ndpa/evaluation/__init__.py": r'''"""Evaluation harness: scan the corpus under frozen conditions, compare with the annotators, report the numbers."""
''',
    "src/ndpa/evaluation/metrics.py": r'''"""Plain-Python statistics for the evaluation. No third-party packages, so every number can be checked by hand.

Every function returns None when the number is not defined (for example precision when nothing was predicted),
never 0 or NaN: an undefined number must not look like a result.
"""
import math
from collections import Counter


def safe_div(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def prf(tp: int, fp: int, fn: int) -> tuple[float | None, float | None, float | None]:
    """Precision, recall and F1 from counts. F1 = 2TP / (2TP + FP + FN), the same as 2PR / (P + R)."""
    return safe_div(tp, tp + fp), safe_div(tp, tp + fn), safe_div(2 * tp, 2 * tp + fp + fn)


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion. With 30 sites per rule these intervals are wide, and should be shown."""
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def cohen_kappa(a: list, b: list) -> float | None:
    """Agreement between two raters beyond chance. None when it is undefined (no items, or chance agreement is 100%)."""
    if len(a) != len(b):
        raise ValueError("both raters must label the same items")
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[label] * cb[label] for label in set(ca) | set(cb)) / (n * n)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def kappa_band(kappa: float | None) -> str:
    """The Landis and Koch (1977) wording for a kappa value."""
    if kappa is None:
        return "not defined"
    if kappa < 0:
        return "poor"
    for upper, word in ((0.20, "slight"), (0.40, "fair"), (0.60, "moderate"), (0.80, "substantial")):
        if kappa <= upper:
            return word
    return "almost perfect"


def _ranks(values: list[float]) -> list[float]:
    """Ranks starting at 1, tied values share the average of their positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3 or len(y) != n:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / math.sqrt(sxx * syy)


def spearman(x: list[float], y: list[float]) -> float | None:
    """Rank correlation: do the two scores put the sites in the same order? Needs at least 3 sites."""
    if len(x) != len(y):
        raise ValueError("both lists must have the same length")
    return pearson(_ranks(x), _ranks(y))


def mean_abs_error(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y):
        raise ValueError("both lists must have the same length")
    return sum(abs(a - b) for a, b in zip(x, y, strict=True)) / len(x) if x else None
''',
    "src/ndpa/evaluation/labels.py": r'''"""Reads an annotator's label sheet (the CSV made by eval/prepare_annotation.py) and checks it carefully.

A mistake in a label sheet must never silently change a result, so every problem is collected and reported together.
"""
import argparse
import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from ndpa.models import Outcome

# What annotators may write. Case, spaces, hyphens and underscores are ignored: "Non-Compliant" = "non_compliant" = "nc".
LABELS = {"compliant": Outcome.COMPLIANT, "c": Outcome.COMPLIANT,
          "noncompliant": Outcome.NON_COMPLIANT, "nc": Outcome.NON_COMPLIANT,
          "notapplicable": Outcome.NOT_APPLICABLE, "na": Outcome.NOT_APPLICABLE, "n/a": Outcome.NOT_APPLICABLE}
REQUIRED_COLUMNS = ("site", "rule_id", "label")


class AnnotationError(ValueError):
    """The sheet has problems. .problems lists every one of them."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        shown = "\n  - ".join(problems[:25])
        more = f"\n  ... and {len(problems) - 25} more" if len(problems) > 25 else ""
        super().__init__(f"{len(problems)} problem(s) in the label sheet:\n  - {shown}{more}")


@dataclass
class Label:
    outcome: Outcome
    na_reason: str = ""
    evidence_ref: str = ""
    notes: str = ""


@dataclass
class Annotations:
    path: str
    labels: dict[tuple[str, str], Label] = field(default_factory=dict)  # (site key, rule id) -> label
    blank_rows: int = 0  # rows the annotator has not labelled yet

    def sites(self) -> set[str]:
        return {site for site, _ in self.labels}


def normalise_site(raw: str) -> str:
    """'https://www.Example.com.ng/path' and 'example.com.ng' are the same site: example.com.ng.
    A port is kept unless it is the usual one for the scheme, so two services on one machine stay apart."""
    raw = (raw or "").strip()
    parts = urlsplit(raw if "://" in raw else "//" + raw)
    host = (parts.hostname or raw).lower().rstrip(".")
    host = host[4:] if host.startswith("www.") else host
    try:
        port = parts.port
    except ValueError:
        port = None
    return f"{host}:{port}" if port not in (None, 80, 443) else host


def parse_label(raw: str) -> Outcome | None:
    """None for an empty cell (not labelled yet). KeyError for something that is not a label."""
    cleaned = (raw or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    if not cleaned:
        return None
    return LABELS[cleaned]


def _read_rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")  # spreadsheets often save a byte-order mark
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # some locales save with semicolons, which the sniffer handles; otherwise assume commas
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)
    reader.fieldnames = [(name or "").strip().lower() for name in (reader.fieldnames or [])]
    return list(reader)


def load_annotations(path: str | Path, rule_ids: list[str], site_keys: set[str] | None = None) -> Annotations:
    """Load one label sheet. Raises AnnotationError listing every problem found."""
    path = Path(path)
    rows = _read_rows(path)
    if not rows:
        raise AnnotationError([f"{path.name} has no rows"])
    missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
    if missing:
        raise AnnotationError([f"{path.name} is missing the column(s): {', '.join(missing)}"])
    problems: list[str] = []
    result = Annotations(path=str(path))
    known_rules = set(rule_ids)
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        site, rule = normalise_site(row.get("site", "")), (row.get("rule_id") or "").strip().upper()
        where = f"row {number} ({row.get('site', '').strip()} {rule})"
        if not site:
            problems.append(f"row {number}: the site is empty")
            continue
        if rule not in known_rules:
            problems.append(f"{where}: '{rule}' is not a scored rule")
            continue
        if site_keys is not None and site not in site_keys:
            problems.append(f"{where}: this site is not in the corpus")
            continue
        try:
            outcome = parse_label(row.get("label", ""))
        except KeyError:
            problems.append(f"{where}: '{row.get('label', '').strip()}' is not a label (use Compliant, Non-Compliant or Not Applicable)")
            continue
        if outcome is None:
            result.blank_rows += 1
            continue
        label = Label(outcome, (row.get("na_reason") or "").strip(), (row.get("evidence_ref") or "").strip(), (row.get("notes") or "").strip())
        if outcome == Outcome.NOT_APPLICABLE and not label.na_reason:
            problems.append(f"{where}: Not Applicable needs a reason in the na_reason column")
        earlier = result.labels.get((site, rule))
        if earlier is not None and earlier.outcome != outcome:
            problems.append(f"{where}: this site and rule appear twice with different labels")
        result.labels[(site, rule)] = label
    if problems:
        raise AnnotationError(problems)
    return result


def complete_sites(annotations: Annotations, rule_ids: list[str]) -> set[str]:
    """Sites where every scored rule has a label."""
    return {site for site in annotations.sites() if all((site, rule) in annotations.labels for rule in rule_ids)}


def main(argv: list[str] | None = None) -> None:
    """python -m ndpa.evaluation.labels eval/annotations/annotator1.csv --sites my_site_list.txt   (annotators: run this before handing in)"""
    from ndpa.evaluation.corpus import read_sites
    from ndpa.scoring.score import load_rulebook

    ap = argparse.ArgumentParser(description="Check a label sheet and say what is still missing.")
    ap.add_argument("sheet")
    ap.add_argument("--sites", help="the site list, so a site that is not in the corpus is caught")
    args = ap.parse_args(argv)
    ids = [r["id"] for r in load_rulebook()["rules"] if r.get("tier") != "unscored"]
    site_keys = {normalise_site(u) for u in read_sites(Path(args.sites))} if args.sites else None
    try:
        annotations = load_annotations(args.sheet, ids, site_keys)
    except AnnotationError as problem:
        raise SystemExit(f"{problem}\n\nFix these and run the check again.") from None
    finished = complete_sites(annotations, ids)
    print(f"OK: {len(annotations.labels)} rows labelled, {annotations.blank_rows} still blank. "
          f"{len(annotations.sites())} site(s) started, {len(finished)} complete.")
    for site in sorted(annotations.sites() - finished):
        print(f"  {site}: {sum(1 for rule in ids if (site, rule) not in annotations.labels)} rule(s) still to label")


if __name__ == "__main__":
    main()
''',
    "src/ndpa/evaluation/corpus.py": r'''"""Scan the whole corpus under controlled conditions and keep a record of how it went.

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
''',
    "src/ndpa/evaluation/report.py": r'''"""Compare the tool with the annotators and produce the numbers for Chapter 4.

    python -m ndpa.evaluation.report --run eval-1 --annotator1 eval/annotations/annotator1.csv \
        [--annotator2 eval/annotations/annotator2.csv] [--adjudicated eval/annotations/adjudicated.csv]

Definitions (also printed in summary.md, so the report explains itself):
  - The positive class is NON-COMPLIANT: "the tool finds a violation".
  - TP: tool and gold both say non-compliant.  FP: the tool says non-compliant, gold says compliant or not applicable.
    FN: gold says non-compliant, the tool says compliant or not applicable.  TN: neither says non-compliant.
  - "Unable to determine" exists only in the tool. Those cases are reported as abstentions. Recall is shown without them
    (lenient) and with each abstention on a gold non-compliant case counted as a miss (strict).
  - Gold is annotator 1, overridden by the adjudicated sheet where one is given.
  - Blocked and failed scans have no outcomes, so they are left out of the comparison and counted in the block rate.
"""
import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ndpa.evaluation import metrics
from ndpa.evaluation.corpus import DEFAULT_DB, MANIFEST_DIR, Manifest, freeze_status
from ndpa.evaluation.labels import AnnotationError, Annotations, complete_sites, load_annotations, normalise_site
from ndpa.models import Outcome, RuleResult, ScanStatus
from ndpa.scoring.score import load_rulebook, score
from ndpa.storage import db

NC, C, NA, UTD = Outcome.NON_COMPLIANT, Outcome.COMPLIANT, Outcome.NOT_APPLICABLE, Outcome.UNABLE_TO_DETERMINE
ERROR_CATEGORIES = [
    "tool defect (the code is wrong)", "word-list gap (the policy wording was not recognised)", "capture gap (the browser missed something)",
    "annotator error", "rulebook ambiguity (the rule can be read two ways)", "site changed between the two looks", "other (explain in notes)"]


@dataclass
class ToolSite:
    url: str
    status: str  # done, blocked, failed, or not_scanned
    scan_id: int | None = None
    folder: str = ""
    outcomes: dict[str, tuple[Outcome, str]] = field(default_factory=dict)  # rule id -> (outcome, the tool's note)
    score_weighted: float | None = None
    score_equal: float | None = None
    band: str | None = None
    outside_window: bool = False


def scored_rules(rulebook: dict) -> list[dict]:
    return [{"id": r["id"], "name": r["name"], "category": r["category"], "tier": r["tier"], "weight": r["weight"]}
            for r in rulebook["rules"] if r.get("tier") != "unscored"]


def load_tool(conn, manifest: Manifest) -> dict[str, ToolSite]:
    """One ToolSite per planned site, read from the database the corpus run wrote to."""
    sites: dict[str, ToolSite] = {}
    for url in dict.fromkeys([*manifest.planned, *manifest.entries]):
        entry = manifest.entries.get(url)
        site = ToolSite(url=url, status="not_scanned")
        if entry:
            site.status, site.scan_id, site.outside_window = entry["status"], entry.get("scan_id"), bool(entry.get("outside_window"))
            scan = db.get_scan(conn, entry["scan_id"]) if entry.get("scan_id") else None
            if scan:
                site.status, site.folder = scan["status"], scan.get("folder") or ""
                if scan["status"] == "done":
                    for f in db.get_findings(conn, scan["id"]):
                        site.outcomes[f["rule_id"]] = (Outcome(f["outcome"]), f["note"] or "")
                    row = conn.execute("SELECT score_weighted, score_equal, band FROM score WHERE scan_id = ?", (scan["id"],)).fetchone()
                    if row:
                        site.score_weighted, site.score_equal, site.band = row["score_weighted"], row["score_equal"], row["band"]
        sites[normalise_site(url)] = site
    return sites


def merge_gold(first: Annotations, adjudicated: Annotations | None) -> dict[tuple[str, str], Outcome]:
    gold = {key: label.outcome for key, label in first.labels.items()}
    if adjudicated:
        gold.update({key: label.outcome for key, label in adjudicated.labels.items()})
    return gold


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def _interval(ci: tuple[float, float] | None, sign: bool = False) -> str:
    if ci is None:
        return ""
    return f"{100 * ci[0]:.0f}% to {100 * ci[1]:.0f}%" if sign else f"{100 * ci[0]:.0f} to {100 * ci[1]:.0f}"


CATEGORY_NAMES = {"cookies": "Cookies", "consent": "Consent banner", "trackers": "Trackers", "script_behaviour": "Scripts", "privacy_policy": "Privacy policy"}


def _counts(pairs: list[tuple[Outcome, Outcome]]) -> dict:
    """pairs are (gold, tool). Lenient: abstentions are left out of tp/fp/fn/tn and counted on their own."""
    c = {"n": len(pairs), "tp": 0, "fp": 0, "fn": 0, "tn": 0, "abstained": 0, "abstained_gold_nc": 0, "gold_nc": 0, "tool_nc": 0, "agree": 0, "determined": 0}
    for gold, tool in pairs:
        c["gold_nc"] += gold == NC
        if tool == UTD:
            c["abstained"] += 1
            c["abstained_gold_nc"] += gold == NC
            continue
        c["determined"] += 1
        c["tool_nc"] += tool == NC
        c["agree"] += gold == tool
        if tool == NC and gold == NC:
            c["tp"] += 1
        elif tool == NC:
            c["fp"] += 1
        elif gold == NC:
            c["fn"] += 1
        else:
            c["tn"] += 1
    return c


def _metrics(c: dict) -> dict:
    p, r, f1 = metrics.prf(c["tp"], c["fp"], c["fn"])
    return {**c, "precision": p, "p_ci": metrics.wilson(c["tp"], c["tp"] + c["fp"]), "recall": r, "r_ci": metrics.wilson(c["tp"], c["tp"] + c["fn"]),
            "f1": f1, "recall_strict": metrics.safe_div(c["tp"], c["tp"] + c["fn"] + c["abstained_gold_nc"]),
            "agreement": metrics.safe_div(c["agree"], c["determined"])}


def _sum(rows: list[dict]) -> dict:
    keys = ("n", "tp", "fp", "fn", "tn", "abstained", "abstained_gold_nc", "gold_nc", "tool_nc", "agree", "determined")
    return {k: sum(r[k] for r in rows) for k in keys}


def detection(tool: dict[str, ToolSite], gold: dict[tuple[str, str], Outcome], rules: list[dict]) -> dict:
    """Per rule, per category and overall precision, recall and F1 for 'the tool finds a violation'."""
    by_rule: dict[str, list[tuple[Outcome, Outcome]]] = defaultdict(list)
    sites_compared = set()
    for (site, rule), g in gold.items():
        t = tool.get(site)
        if t is None or t.status != "done" or rule not in t.outcomes:
            continue
        by_rule[rule].append((g, t.outcomes[rule][0]))
        sites_compared.add(site)
    rule_rows = []
    for r in rules:
        m = _metrics(_counts(by_rule.get(r["id"], [])))
        rule_rows.append({"rule_id": r["id"], "name": r["name"], "category": r["category"], "tier": r["tier"], **m})
    category_rows = []
    for category in dict.fromkeys(r["category"] for r in rules):
        members = [r for r in rule_rows if r["category"] == category]
        m = _metrics(_sum(members))
        f1s = [r["f1"] for r in members if r["f1"] is not None]
        category_rows.append({"category": category, "rules": len(members), "macro_f1": sum(f1s) / len(f1s) if f1s else None,
                              "macro_f1_rules": len(f1s), **m})
    overall = _metrics(_sum(rule_rows))
    f1s = [r["f1"] for r in rule_rows if r["f1"] is not None]
    overall["macro_f1"], overall["macro_f1_rules"] = (sum(f1s) / len(f1s) if f1s else None), len(f1s)
    determined = [(g, t) for pairs in by_rule.values() for g, t in pairs if t != UTD]
    overall["kappa_tool_vs_gold"] = metrics.cohen_kappa([g.value for g, _ in determined], [t.value for _, t in determined])
    overall["kappa_band"] = metrics.kappa_band(overall["kappa_tool_vs_gold"])
    return {"rules": rule_rows, "categories": category_rows, "overall": overall, "sites_compared": len(sites_compared)}


def inter_annotator(first: Annotations, second: Annotations | None, rules: list[dict]) -> dict | None:
    if second is None:
        return None
    shared = sorted(k for k in first.labels if k in second.labels)
    per_rule = []
    for r in rules:
        keys = [k for k in shared if k[1] == r["id"]]
        a = [first.labels[k].outcome.value for k in keys]
        b = [second.labels[k].outcome.value for k in keys]
        per_rule.append({"rule_id": r["id"], "n": len(keys), "agreement": metrics.safe_div(sum(x == y for x, y in zip(a, b, strict=True)), len(keys)),
                         "kappa": metrics.cohen_kappa(a, b)})
    a = [first.labels[k].outcome.value for k in shared]
    b = [second.labels[k].outcome.value for k in shared]
    kappa = metrics.cohen_kappa(a, b)
    disagreements = [{"site": s, "rule_id": r, "annotator1": first.labels[(s, r)].outcome.value, "annotator2": second.labels[(s, r)].outcome.value,
                      "annotator1_notes": first.labels[(s, r)].notes, "annotator2_notes": second.labels[(s, r)].notes,
                      "adjudicated_label": "", "adjudication_notes": ""} for s, r in shared if first.labels[(s, r)].outcome != second.labels[(s, r)].outcome]
    return {"sites": len({s for s, _ in shared}), "items": len(shared), "agreement": metrics.safe_div(sum(x == y for x, y in zip(a, b, strict=True)), len(shared)),
            "kappa": kappa, "kappa_band": metrics.kappa_band(kappa), "per_rule": per_rule, "disagreements": disagreements}


def score_comparison(tool: dict[str, ToolSite], gold: dict[tuple[str, str], Outcome], rulebook: dict, rules: list[dict]) -> dict:
    """Score every fully annotated site from the annotator's labels, with the same formula as the tool, and compare."""
    ids = [r["id"] for r in rules]
    rows = []
    for site, t in sorted(tool.items()):
        if t.status != "done" or not all((site, i) in gold for i in ids):
            continue
        card = score([RuleResult(rule_id=i, outcome=gold[(site, i)]) for i in ids], rulebook, ScanStatus.DONE)
        rows.append({"site": site, "gold_weighted": card.score_weighted, "gold_equal": card.score_equal, "gold_band": card.band,
                     "tool_weighted": t.score_weighted, "tool_equal": t.score_equal, "tool_band": t.band})
    both = [r for r in rows if r["gold_weighted"] is not None and r["tool_weighted"] is not None]
    both_equal = [r for r in rows if r["gold_equal"] is not None and r["tool_equal"] is not None]
    tool_both = [r for r in rows if r["tool_weighted"] is not None and r["tool_equal"] is not None]
    gw, tw = [r["gold_weighted"] for r in both], [r["tool_weighted"] for r in both]
    return {"rows": rows, "n": len(both),
            "spearman_weighted": metrics.spearman(gw, tw), "mean_abs_error": metrics.mean_abs_error(gw, tw),
            "band_agreement": metrics.safe_div(sum(r["gold_band"] == r["tool_band"] for r in both), len(both)),
            "spearman_equal": metrics.spearman([r["gold_equal"] for r in both_equal], [r["tool_equal"] for r in both_equal]),
            "sensitivity_spearman": metrics.spearman([r["tool_weighted"] for r in tool_both], [r["tool_equal"] for r in tool_both]),
            "sensitivity_n": len(tool_both)}


def block_rate(tool: dict[str, ToolSite]) -> dict:
    count = lambda s: sum(1 for t in tool.values() if t.status == s)  # noqa: E731
    done, blocked, failed, unscanned = count("done"), count("blocked"), count("failed"), count("not_scanned")
    reached = done + blocked
    return {"planned": len(tool), "done": done, "blocked": blocked, "failed": failed, "not_scanned": unscanned,
            "block_rate": metrics.safe_div(blocked, reached), "block_rate_ci": metrics.wilson(blocked, reached),
            "blocked_sites": sorted(t.url for t in tool.values() if t.status == "blocked"),
            "failed_sites": sorted(t.url for t in tool.values() if t.status == "failed")}


def error_rows(tool: dict[str, ToolSite], gold: dict[tuple[str, str], Outcome], rules: list[dict]) -> list[dict]:
    names = {r["id"]: r["name"] for r in rules}
    out = []
    for (site, rule), g in sorted(gold.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        t = tool.get(site)
        if t is None or t.status != "done" or rule not in t.outcomes or t.outcomes[rule][0] == g:
            continue
        out.append({"site": site, "rule_id": rule, "rule": names.get(rule, ""), "gold": g.value, "tool": t.outcomes[rule][0].value, "tool_note": t.outcomes[rule][1],
                    "scan_id": t.scan_id, "evidence_folder": t.folder, "error_category": "", "notes": ""})
    return out


def evaluate(tool: dict[str, ToolSite], first: Annotations, second: Annotations | None, adjudicated: Annotations | None, rulebook: dict, manifest: Manifest) -> dict:
    rules = scored_rules(rulebook)
    ids = [r["id"] for r in rules]
    gold = merge_gold(first, adjudicated)
    complete = complete_sites(first, ids)
    gold_sites = {s for s, _ in gold}
    detect = detection(tool, gold, rules)
    record, problems = freeze_status()
    unresolved = 0
    agreement = inter_annotator(first, second, rules)
    if agreement:
        adjudicated_keys = set(adjudicated.labels) if adjudicated else set()
        unresolved = sum(1 for d in agreement["disagreements"] if (d["site"], d["rule_id"]) not in adjudicated_keys)
    return {
        "run": {"name": manifest.name, "started_at": manifest.started_at, "vantage": manifest.vantage, "seed": manifest.seed,
                "window_hours": manifest.window_hours, "window_exceeded": manifest.window_exceeded,
                "sites_outside_window": sorted(t.url for t in tool.values() if t.outside_window),
                "rulebook_version": rulebook.get("meta", {}).get("version", "unknown"),
                "frozen_when_run": bool(manifest.freeze.get("files")), "frozen_now": bool(record) and not problems, "freeze_problems": problems,
                "freeze_record": manifest.freeze},
        "coverage": {"planned": len(tool), "scanned_done": sum(t.status == "done" for t in tool.values()),
                     "annotated_sites": len(gold_sites), "fully_annotated_sites": len(complete), "blank_rows": first.blank_rows,
                     "annotated_but_not_scanned": sorted(s for s in gold_sites if s not in tool or tool[s].status == "not_scanned"),
                     "annotated_but_blocked_or_failed": sorted(s for s in gold_sites if s in tool and tool[s].status in ("blocked", "failed")),
                     "scanned_but_not_annotated": sorted(s for s, t in tool.items() if t.status == "done" and s not in gold_sites),
                     "sites_compared": detect["sites_compared"], "items_compared": detect["overall"]["n"],
                     "adjudicated_items": len(adjudicated.labels) if adjudicated else 0, "unresolved_disagreements": unresolved},
        "block_rate": block_rate(tool), "detection": detect, "inter_annotator": agreement,
        "scores": score_comparison(tool, gold, rulebook, rules), "errors": error_rows(tool, gold, rules),
    }


# ---------- writing ----------
def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _rate_cells(m: dict) -> list:
    return [_pct(m["precision"]), _interval(m["p_ci"]), _pct(m["recall"]), _interval(m["r_ci"]), _pct(m["f1"]), _pct(m["recall_strict"])]


def summary_markdown(result: dict) -> str:
    run, cov, blk, det, ia, sc = result["run"], result["coverage"], result["block_rate"], result["detection"], result["inter_annotator"], result["scores"]
    o = det["overall"]
    out = [f"# Evaluation report: {run['name']}", ""]
    if not run["frozen_when_run"]:
        out += ["> **TRIAL RUN: the rulebook was not frozen when this corpus was scanned. These numbers must not be reported.**", ""]
    elif not run["frozen_now"]:
        out += ["> **WARNING: a frozen file has changed since the freeze: " + "; ".join(run["freeze_problems"]) + "**", ""]
    out += ["## 1. The run", "",
            f"- Scanned from: {run['vantage']}. Rulebook {run['rulebook_version']}. Started {run['started_at']}. Site order seed {run['seed']}.",
            f"- Time window: {run['window_hours']:g} hours; " + ("**exceeded**, " + str(len(run["sites_outside_window"])) + " site(s) were scanned outside it." if run["window_exceeded"] else "kept."),
            "", "## 2. Coverage", "",
            f"- {cov['planned']} sites planned, {cov['scanned_done']} scanned successfully, {cov['annotated_sites']} annotated ({cov['fully_annotated_sites']} completely, {cov['blank_rows']} rows still blank).",
            f"- Compared: {cov['sites_compared']} sites, {cov['items_compared']} site-rule items.",
            *( [f"- Annotated but blocked or failed (left out of the comparison): {', '.join(cov['annotated_but_blocked_or_failed'])}."] if cov["annotated_but_blocked_or_failed"] else []),
            *( [f"- Scanned but not annotated yet: {', '.join(cov['scanned_but_not_annotated'])}."] if cov["scanned_but_not_annotated"] else []),
            "", "## 3. Block rate", "",
            f"- {blk['blocked']} of {blk['done'] + blk['blocked']} sites that could be reached refused the automated visit ({_pct(blk['block_rate'])}, 95% interval {_interval(blk['block_rate_ci'], sign=True)}); {blk['failed']} failed for other reasons; {blk['not_scanned']} not scanned.",
            *( [f"- Blocked: {', '.join(blk['blocked_sites'])}."] if blk["blocked_sites"] else []),
            "", "## 4. How well the tool finds violations", "",
            "Positive class = non-compliant. Intervals are 95% Wilson intervals: with this few sites they are wide, so read them with the point values.", "",
            f"- **Overall (micro): precision {_pct(o['precision'])}, recall {_pct(o['recall'])}, F1 {_pct(o['f1'])}**; macro F1 over {o['macro_f1_rules']} rules: {_pct(o['macro_f1'])}.",
            f"- Tool versus gold agreement on the three labels (kappa): {o['kappa_tool_vs_gold'] if o['kappa_tool_vs_gold'] is None else round(o['kappa_tool_vs_gold'], 3)} ({o['kappa_band']}). Plain agreement {_pct(o['agreement'])} of {o['determined']} determined items.",
            f"- The tool abstained ('unable to determine') on {o['abstained']} item{'' if o['abstained'] == 1 else 's'}, {o['abstained_gold_nc']} of them gold non-compliant. Strict recall (those counted as misses): {_pct(o['recall_strict'])}.",
            "", "### By category", "",
            _table(["Category", "Items", "Precision", "95% interval (%)", "Recall", "95% interval (%)", "F1", "Strict recall", "Macro F1"],
                   [[CATEGORY_NAMES.get(c["category"], c["category"]), c["n"], *_rate_cells(c), _pct(c["macro_f1"])] for c in det["categories"]]),
            "", "### By rule", "",
            "n/a means the number is undefined, not zero: precision is undefined when the tool never said non-compliant, recall when the gold never did.", "",
            _table(["Rule", "Name", "Items", "Gold NC", "Tool NC", "TP", "FP", "FN", "Abstained", "Precision", "95% interval (%)", "Recall", "95% interval (%)", "F1", "Strict recall"],
                   [[r["rule_id"], r["name"], r["n"], r["gold_nc"], r["tool_nc"], r["tp"], r["fp"], r["fn"], r["abstained"], *_rate_cells(r)] for r in det["rules"]])]
    if ia:
        out += ["", "## 5. Agreement between the two annotators", "",
                f"- {ia['sites']} sites, {ia['items']} items: agreement {_pct(ia['agreement'])}, kappa {None if ia['kappa'] is None else round(ia['kappa'], 3)} ({ia['kappa_band']}).",
                f"- {len(ia['disagreements'])} disagreements, {cov['unresolved_disagreements']} not yet adjudicated (see disagreements.csv).", "",
                _table(["Rule", "Items", "Agreement", "Kappa"], [[r["rule_id"], r["n"], _pct(r["agreement"]), "n/a" if r["kappa"] is None else round(r["kappa"], 2)] for r in ia["per_rule"]])]
    out += ["", "## 6. Score: tool against annotators", "",
            f"- {sc['n']} sites with a score from both. Rank correlation (Spearman) between the annotators' score and the tool's score: {sc['spearman_weighted'] if sc['spearman_weighted'] is None else round(sc['spearman_weighted'], 3)}; mean absolute difference {None if sc['mean_abs_error'] is None else round(sc['mean_abs_error'], 1)} points; same risk band for {_pct(sc['band_agreement'])}.",
            f"- Equal-weight version: Spearman {sc['spearman_equal'] if sc['spearman_equal'] is None else round(sc['spearman_equal'], 3)}.",
            f"- Sensitivity: the tool's weighted and equal-weight scores put {sc['sensitivity_n']} sites in nearly the same order when Spearman is close to 1 (here {sc['sensitivity_spearman'] if sc['sensitivity_spearman'] is None else round(sc['sensitivity_spearman'], 3)}). Never tune the weights to improve this.",
            "", "## 7. Errors", "",
            f"- {len(result['errors'])} items where the tool and the gold label differ are listed in errors.csv. Fill in the error_category column for each, using one of:", *[f"  - {c}" for c in ERROR_CATEGORIES], ""]
    return "\n".join(out)


def write_outputs(result: dict, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    det = result["detection"]
    header = ["rule_id", "name", "category", "tier", "items", "gold_nc", "tool_nc", "tp", "fp", "fn", "tn", "abstained", "abstained_gold_nc", "precision", "precision_ci_low",
              "precision_ci_high", "recall", "recall_ci_low", "recall_ci_high", "f1", "recall_strict", "agreement"]

    def row(r: dict) -> list:
        pc, rc = r["p_ci"] or ("", ""), r["r_ci"] or ("", "")
        return [r.get("rule_id", r.get("category")), r.get("name", ""), r.get("category", ""), r.get("tier", ""), r["n"], r["gold_nc"], r["tool_nc"], r["tp"], r["fp"], r["fn"], r["tn"],
                r["abstained"], r["abstained_gold_nc"], r["precision"], pc[0], pc[1], r["recall"], rc[0], rc[1], r["f1"], r["recall_strict"], r["agreement"]]
    _write_csv(directory / "per_rule.csv", header, [row(r) for r in det["rules"]])
    _write_csv(directory / "per_category.csv", header, [row(r) for r in det["categories"]])
    _write_csv(directory / "scores.csv", ["site", "gold_weighted", "gold_equal", "gold_band", "tool_weighted", "tool_equal", "tool_band"],
               [[r[k] for k in ("site", "gold_weighted", "gold_equal", "gold_band", "tool_weighted", "tool_equal", "tool_band")] for r in result["scores"]["rows"]])
    blk = result["block_rate"]
    _write_csv(directory / "block_rate.csv", ["site", "status"], [[u, "blocked"] for u in blk["blocked_sites"]] + [[u, "failed"] for u in blk["failed_sites"]])
    keys = ["site", "rule_id", "rule", "gold", "tool", "tool_note", "scan_id", "evidence_folder", "error_category", "notes"]
    _write_csv(directory / "errors.csv", keys, [[e[k] for k in keys] for e in result["errors"]])
    written = ["per_rule.csv", "per_category.csv", "scores.csv", "block_rate.csv", "errors.csv"]
    if result["inter_annotator"]:
        dkeys = ["site", "rule_id", "annotator1", "annotator2", "annotator1_notes", "annotator2_notes", "adjudicated_label", "adjudication_notes"]
        _write_csv(directory / "disagreements.csv", dkeys, [[d[k] for k in dkeys] for d in result["inter_annotator"]["disagreements"]])
        written.append("disagreements.csv")
    (directory / "summary.md").write_text(summary_markdown(result), encoding="utf-8")
    (directory / "report.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return [directory / name for name in [*written, "summary.md", "report.json"]]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Compare the tool with the annotators and write the evaluation report.")
    ap.add_argument("--run", required=True, help="the name used with ndpa.evaluation.corpus")
    ap.add_argument("--annotator1", required=True)
    ap.add_argument("--annotator2")
    ap.add_argument("--adjudicated")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--manifest-dir", default=str(MANIFEST_DIR))
    ap.add_argument("--out", help="default: data/eval_reports/<run>")
    args = ap.parse_args(argv)
    manifest = Manifest.load(args.run, Path(args.manifest_dir))
    rulebook = load_rulebook()
    ids = [r["id"] for r in scored_rules(rulebook)]
    corpus_sites = {normalise_site(u) for u in [*manifest.planned, *manifest.entries]}
    try:
        first = load_annotations(args.annotator1, ids, corpus_sites)
        second = load_annotations(args.annotator2, ids, corpus_sites) if args.annotator2 else None
        adjudicated = load_annotations(args.adjudicated, ids, corpus_sites) if args.adjudicated else None
    except AnnotationError as problem:
        raise SystemExit(f"{problem}\n\nFix the label sheet and run the report again. Nothing was written.") from None
    conn = db.connect(Path(args.db))
    result = evaluate(load_tool(conn, manifest), first, second, adjudicated, rulebook, manifest)
    written = write_outputs(result, Path(args.out or f"data/eval_reports/{args.run}"))
    print(summary_markdown(result))
    print("\nWritten:\n  " + "\n  ".join(str(p) for p in written))


if __name__ == "__main__":
    main()
''',
    "tests/unit/test_eval_metrics.py": r'''import pytest

from ndpa.evaluation import metrics


def test_precision_recall_and_f1_from_counts():
    p, r, f1 = metrics.prf(8, 2, 1)
    assert round(p, 3) == 0.8 and round(r, 3) == 0.889 and round(f1, 3) == 0.842
    assert metrics.prf(0, 0, 0) == (None, None, None)  # nothing predicted and nothing to find: not a result
    assert metrics.prf(0, 3, 0) == (0.0, None, 0.0)  # only false alarms: precision 0, recall undefined
    assert metrics.prf(0, 0, 4) == (None, 0.0, 0.0)  # everything missed: recall 0, precision undefined


def test_wilson_intervals_match_known_values_and_stay_inside_0_to_1():
    low, high = metrics.wilson(8, 10)
    assert round(low, 3) == 0.490 and round(high, 3) == 0.943
    assert metrics.wilson(0, 10)[0] == 0.0 and metrics.wilson(10, 10)[1] == 1.0
    assert metrics.wilson(0, 0) is None
    narrow, wide = metrics.wilson(50, 100), metrics.wilson(5, 10)
    assert narrow[1] - narrow[0] < wide[1] - wide[0]  # more items, a tighter interval


def test_cohens_kappa():
    assert round(metrics.cohen_kappa(list("AABBAB"), list("AABAAB")), 3) == 0.667
    assert metrics.cohen_kappa(list("ABAB"), list("ABAB")) == 1.0
    assert metrics.cohen_kappa(list("AABB"), list("BBAA")) == -1.0
    assert metrics.cohen_kappa(list("AAAA"), list("AAAA")) is None  # chance agreement is 100%: kappa is undefined
    assert metrics.cohen_kappa([], []) is None
    with pytest.raises(ValueError):
        metrics.cohen_kappa(["A"], ["A", "B"])


def test_kappa_wording():
    words = [metrics.kappa_band(k) for k in (-0.1, 0.1, 0.2, 0.35, 0.5, 0.7, 0.81, 1.0, None)]
    assert words == ["poor", "slight", "slight", "fair", "moderate", "substantial", "almost perfect", "almost perfect", "not defined"]


def test_spearman_rank_correlation_with_ties():
    assert metrics.spearman([1, 2, 3, 4], [1, 3, 2, 4]) == 0.8
    assert metrics.spearman([1, 2, 3], [10, 20, 30]) == 1.0 and metrics.spearman([1, 2, 3], [3, 2, 1]) == -1.0
    assert round(metrics.spearman([1, 2, 2, 4], [1, 2, 3, 4]), 3) == 0.949  # tied values share the average rank
    assert metrics.spearman([5, 5, 5], [1, 2, 3]) is None  # no variation: undefined
    assert metrics.spearman([1, 2], [1, 2]) is None  # fewer than 3 sites


def test_mean_absolute_error():
    assert metrics.mean_abs_error([10, 20, 30], [12, 18, 33]) == (2 + 2 + 3) / 3
    assert metrics.mean_abs_error([], []) is None
''',
    "tests/unit/test_eval_labels.py": r'''import pytest

from ndpa.evaluation.labels import AnnotationError, complete_sites, load_annotations, normalise_site, parse_label
from ndpa.models import Outcome

RULES = ["CK-01", "CN-01", "SB-03"]


def sheet(tmp_path, text, name="a.csv", encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


HEADER = "site,rule_id,label,na_reason,evidence_ref,notes\n"


def test_sites_are_compared_by_their_host_only():
    assert normalise_site("https://www.Example.com.ng/path?x=1") == "example.com.ng"
    assert normalise_site("example.com.ng") == "example.com.ng" and normalise_site("http://gtbank.com/") == "gtbank.com"
    assert normalise_site("") == ""
    assert normalise_site("http://127.0.0.1:8123/x") == "127.0.0.1:8123" and normalise_site("https://a.ng:443/") == "a.ng" and normalise_site("http://a.ng:80") == "a.ng"


@pytest.mark.parametrize("raw,expected", [("Compliant", Outcome.COMPLIANT), (" non-compliant ", Outcome.NON_COMPLIANT), ("Non_Compliant", Outcome.NON_COMPLIANT),
                                          ("NC", Outcome.NON_COMPLIANT), ("c", Outcome.COMPLIANT), ("Not Applicable", Outcome.NOT_APPLICABLE), ("N/A", Outcome.NOT_APPLICABLE),
                                          ("na", Outcome.NOT_APPLICABLE), ("", None), ("   ", None)])
def test_label_spellings(raw, expected):
    assert parse_label(raw) == expected


def test_a_good_sheet_loads_and_blank_rows_are_counted(tmp_path):
    path = sheet(tmp_path, HEADER + "https://a.ng,CK-01,Compliant,,,\nhttps://a.ng,CN-01,Non-Compliant,,shot1,no banner\nhttps://a.ng,SB-03,,,,\n"
                 "https://a.ng,CK-01,Compliant,,,\n")  # the same label twice is harmless
    ann = load_annotations(path, RULES)
    assert ann.blank_rows == 1 and set(ann.labels) == {("a.ng", "CK-01"), ("a.ng", "CN-01")}
    assert ann.labels[("a.ng", "CN-01")].notes == "no banner" and ann.labels[("a.ng", "CN-01")].evidence_ref == "shot1"
    assert complete_sites(ann, RULES) == set() and complete_sites(ann, ["CK-01", "CN-01"]) == {"a.ng"}


def test_every_problem_is_reported_together(tmp_path):
    path = sheet(tmp_path, HEADER + "a.ng,CK-01,Maybe,,,\na.ng,XX-99,Compliant,,,\na.ng,CN-01,Not Applicable,,,\nb.ng,CK-01,Compliant,,,\nb.ng,CK-01,Non-Compliant,,,\nz.ng,CK-01,Compliant,,,\n")
    with pytest.raises(AnnotationError) as caught:
        load_annotations(path, RULES, site_keys={"a.ng", "b.ng"})
    text = "\n".join(caught.value.problems)
    assert len(caught.value.problems) == 5
    assert "'Maybe' is not a label" in text and "'XX-99' is not a scored rule" in text and "needs a reason" in text
    assert "appear twice with different labels" in text and "not in the corpus" in text
    assert "row 2" in text  # a problem names the spreadsheet row, counting the header as row 1


def test_a_missing_column_or_empty_file_is_explained(tmp_path):
    with pytest.raises(AnnotationError, match="missing the column"):
        load_annotations(sheet(tmp_path, "site,rule\na.ng,CK-01\n"), RULES)
    with pytest.raises(AnnotationError, match="no rows"):
        load_annotations(sheet(tmp_path, HEADER, name="empty.csv"), RULES)


def test_sheets_saved_by_spreadsheets_in_other_locales_still_load(tmp_path):
    body = "site;rule_id;label;na_reason;evidence_ref;notes\r\na.ng;CK-01;Compliant;;;\r\na.ng;CN-01;Not Applicable;no trigger;;\r\n"
    ann = load_annotations(sheet(tmp_path, body, encoding="utf-8-sig"), RULES)  # semicolons, Windows line ends and a byte-order mark
    assert ann.labels[("a.ng", "CN-01")].outcome == Outcome.NOT_APPLICABLE and ann.labels[("a.ng", "CN-01")].na_reason == "no trigger"
    upper = HEADER.upper() + "a.ng,ck-01,compliant,,,\n"  # header case and rule id case do not matter
    assert ("a.ng", "CK-01") in load_annotations(sheet(tmp_path, upper, name="u.csv"), RULES).labels


def test_the_check_command_tells_an_annotator_what_is_missing_or_wrong(tmp_path, capsys):
    from ndpa.evaluation import labels
    from ndpa.scoring.score import load_rulebook

    ids = [r["id"] for r in load_rulebook()["rules"] if r.get("tier") != "unscored"]
    sites = tmp_path / "sites.txt"
    sites.write_text("https://a.ng\nhttps://b.ng\n")
    rows = "".join(f"https://a.ng,{rule},Compliant,,,\n" for rule in ids) + "".join(f"https://b.ng,{rule},Compliant,,,\n" for rule in ids[:5])
    good = sheet(tmp_path, HEADER + rows + "https://b.ng," + ids[5] + ",,,,\n", name="good.csv")
    labels.main([str(good), "--sites", str(sites)])
    said = capsys.readouterr().out
    assert "OK: 22 rows labelled, 1 still blank" in said and "2 site(s) started, 1 complete" in said and "b.ng: 12 rule(s) still to label" in said
    bad = sheet(tmp_path, HEADER + "https://zzz.ng,CK-01,Compliant,,,\n", name="bad.csv")
    with pytest.raises(SystemExit, match="not in the corpus"):
        labels.main([str(bad), "--sites", str(sites)])
''',
    "tests/unit/test_eval_corpus.py": r'''import json
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
''',
    "tests/unit/test_eval_report.py": r'''"""The report, checked against a small world whose every number can be worked out on paper.

Three sites were scanned (a, b, c), d was blocked, e was never scanned. Tool outcomes, with every other rule compliant:
    a.ng: CN-02 NC  SB-03 NC  PP-06 C    CN-01 C
    b.ng: CN-02 NC  SB-03 C   PP-06 UTD  CN-01 NC
    c.ng: CN-02 C   SB-03 NC  PP-06 C    CN-01 C    PP-02 NC
Annotator 1 (the gold), every other rule compliant:
    a.ng: CN-02 NC  SB-03 NC  PP-06 C    CN-01 C
    b.ng: CN-02 C   SB-03 C   PP-06 NC   CN-01 NC
    c.ng: CN-02 NC  SB-03 NC  PP-06 C    CN-01 NA
By rule (positive class = non-compliant):
    CN-02: TP 1 (a)  FP 1 (b)  FN 1 (c)        -> precision 1/2, recall 1/2
    SB-03: TP 2 (a, c)  TN 1 (b)               -> precision 1, recall 1
    PP-06: the tool abstained on b, where the gold is NC -> precision and recall undefined, strict recall 0
    CN-01: TP 1 (b), c is gold NA against tool C -> precision 1, recall 1, agreement 2 of 3
    PP-02: FP 1 (c, tool NC against gold C), nothing missed -> precision 0, recall undefined, F1 0
Overall: TP 4, FP 2, FN 1 -> precision 4/6, recall 4/5, F1 8/11.
One abstention on a gold NC, so strict recall is 4/(4+1+1) = 4/6. Asymmetric on purpose, so swapping FP and FN is caught.
"""
import csv
import json

import pytest
import web_seed as ws

from ndpa.evaluation import report
from ndpa.evaluation.corpus import Manifest
from ndpa.evaluation.labels import load_annotations
from ndpa.scoring.score import load_rulebook
from ndpa.storage import db

RULEBOOK = load_rulebook()
IDS = [r["id"] for r in report.scored_rules(RULEBOOK)]
URLS = {k: f"https://{k}" for k in ("a.ng", "b.ng", "c.ng", "d.ng", "e.ng")}


def tool_results(**overrides):
    results = ws.default_results()
    for rule, outcome in overrides.items():
        results[rule.replace("_", "-")] = ws.finding(rule.replace("_", "-"), outcome, f"tool says {outcome.value}")
    return results


def sheet(tmp_path, name, rows):
    """rows: {site: {rule: label}} with every other rule Compliant."""
    path = tmp_path / name
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "rule_id", "label", "na_reason", "evidence_ref", "notes"])
        for site, overrides in rows.items():
            for rule in IDS:
                label = overrides.get(rule, "Compliant")
                w.writerow([f"https://{site}", rule, label, "no banner appeared" if label == "Not Applicable" else "", "", ""])
    return path


@pytest.fixture
def world(tmp_path):
    conn = db.connect(tmp_path / "eval.db")
    ids = {
        "a.ng": ws.seed_scan(conn, tmp_path / "ev", "a.ng", "2026-11-10T08:00:00+00:00", tool_results(CN_02=ws.N, SB_03=ws.N)),
        "b.ng": ws.seed_scan(conn, tmp_path / "ev", "b.ng", "2026-11-10T09:00:00+00:00", tool_results(CN_02=ws.N, PP_06=ws.U, CN_01=ws.N)),
        "c.ng": ws.seed_scan(conn, tmp_path / "ev", "c.ng", "2026-11-10T10:00:00+00:00", tool_results(SB_03=ws.N, PP_02=ws.N)),
        "d.ng": ws.seed_scan(conn, tmp_path / "ev", "d.ng", "2026-11-10T11:00:00+00:00", None, status="blocked"),
    }
    manifest = Manifest(name="t", started_at="2026-11-10T08:00:00+00:00", seed=1, vantage="test lab", planned=list(URLS.values()),
                        entries={URLS[k]: {"scan_id": v, "status": "blocked" if k == "d.ng" else "done", "started_at": "x", "error": None, "attempts": 1, "outside_window": False}
                                 for k, v in ids.items()})
    gold = sheet(tmp_path, "a1.csv", {"a.ng": {"CN-02": "Non-Compliant", "SB-03": "Non-Compliant"},
                                      "b.ng": {"PP-06": "Non-Compliant", "CN-01": "Non-Compliant"},
                                      "c.ng": {"CN-02": "Non-Compliant", "SB-03": "Non-Compliant", "CN-01": "Not Applicable"}, "d.ng": {}})
    sites = {report.normalise_site(u) for u in URLS.values()}
    return {"conn": conn, "manifest": manifest, "tool": report.load_tool(conn, manifest), "first": load_annotations(gold, IDS, sites), "tmp": tmp_path, "sites": sites}


def rule_row(result, rule_id):
    return next(r for r in result["detection"]["rules"] if r["rule_id"] == rule_id)


def run(world, second=None, adjudicated=None):
    return report.evaluate(world["tool"], world["first"], second, adjudicated, RULEBOOK, world["manifest"])


def test_the_tool_side_reads_statuses_outcomes_and_scores_from_the_database(world):
    tool = world["tool"]
    assert {k: t.status for k, t in tool.items()} == {"a.ng": "done", "b.ng": "done", "c.ng": "done", "d.ng": "blocked", "e.ng": "not_scanned"}
    assert tool["b.ng"].outcomes["PP-06"][0] == ws.U and tool["a.ng"].outcomes["CN-02"][1] == "tool says non_compliant"
    assert tool["a.ng"].score_weighted is not None and tool["d.ng"].outcomes == {} and tool["d.ng"].score_weighted is None


def test_precision_recall_and_f1_per_rule_match_the_hand_calculation(world):
    result = run(world)
    cn02 = rule_row(result, "CN-02")
    assert (cn02["tp"], cn02["fp"], cn02["fn"], cn02["tn"]) == (1, 1, 1, 0) and (cn02["precision"], cn02["recall"], cn02["f1"]) == (0.5, 0.5, 0.5)
    sb03 = rule_row(result, "SB-03")
    assert (sb03["tp"], sb03["fp"], sb03["fn"], sb03["tn"]) == (2, 0, 0, 1) and (sb03["precision"], sb03["recall"], sb03["f1"]) == (1.0, 1.0, 1.0)
    pp06 = rule_row(result, "PP-06")
    assert pp06["abstained"] == 1 and pp06["abstained_gold_nc"] == 1 and (pp06["precision"], pp06["recall"], pp06["f1"]) == (None, None, None) and pp06["recall_strict"] == 0.0
    cn01 = rule_row(result, "CN-01")
    assert (cn01["tp"], cn01["tn"]) == (1, 2) and cn01["precision"] == cn01["recall"] == 1.0 and round(cn01["agreement"], 3) == round(2 / 3, 3)
    pp02 = rule_row(result, "PP-02")
    assert (pp02["tp"], pp02["fp"], pp02["fn"], pp02["tn"]) == (0, 1, 0, 2) and (pp02["precision"], pp02["recall"], pp02["f1"]) == (0.0, None, 0.0)
    quiet = rule_row(result, "CK-01")  # nothing happened here: no violation by anyone
    assert quiet["tn"] == 3 and quiet["precision"] is None and quiet["recall"] is None


def test_overall_numbers_and_the_two_ways_of_treating_abstentions(world):
    o = run(world)["detection"]["overall"]
    assert (o["tp"], o["fp"], o["fn"], o["abstained"], o["n"]) == (4, 2, 1, 1, 51)
    assert round(o["precision"], 4) == round(4 / 6, 4) and o["recall"] == 0.8 and round(o["f1"], 4) == round(8 / 11, 4)
    assert round(o["recall_strict"], 4) == round(4 / 6, 4)  # the abstention on a real violation counts as a miss
    assert o["determined"] == 50 and o["agree"] == 46 and o["agreement"] == 0.92 and o["kappa_tool_vs_gold"] is not None
    assert o["p_ci"][0] < o["precision"] < o["p_ci"][1] and o["r_ci"][0] < o["recall"] < o["r_ci"][1]


def test_categories_add_up_to_the_rules(world):
    det = run(world)["detection"]
    for cat in det["categories"]:
        members = [r for r in det["rules"] if r["category"] == cat["category"]]
        assert cat["tp"] == sum(r["tp"] for r in members) and cat["n"] == sum(r["n"] for r in members) and cat["rules"] == len(members)
        defined = [r["f1"] for r in members if r["f1"] is not None]
        assert cat["macro_f1"] == (sum(defined) / len(defined) if defined else None)
    assert sum(c["tp"] for c in det["categories"]) == det["overall"]["tp"] == 4


def test_coverage_blocked_and_unscanned_sites_are_left_out_and_explained(world):
    result = run(world)
    cov, blk = result["coverage"], result["block_rate"]
    assert (cov["planned"], cov["scanned_done"], cov["annotated_sites"], cov["fully_annotated_sites"]) == (5, 3, 4, 4)
    assert cov["sites_compared"] == 3 and cov["items_compared"] == 51 and cov["annotated_but_blocked_or_failed"] == ["d.ng"]
    assert cov["scanned_but_not_annotated"] == [] and cov["blank_rows"] == 0
    assert (blk["done"], blk["blocked"], blk["failed"], blk["not_scanned"]) == (3, 1, 0, 1)
    assert blk["block_rate"] == 0.25 and blk["blocked_sites"] == ["https://d.ng"] and blk["block_rate_ci"][0] < 0.25 < blk["block_rate_ci"][1]


def test_every_disagreement_becomes_a_row_for_error_analysis(world):
    errors = run(world)["errors"]
    assert [(e["rule_id"], e["site"], e["gold"], e["tool"]) for e in errors] == [
        ("CN-01", "c.ng", "not_applicable", "compliant"), ("CN-02", "b.ng", "compliant", "non_compliant"),
        ("CN-02", "c.ng", "non_compliant", "compliant"), ("PP-02", "c.ng", "compliant", "non_compliant"), ("PP-06", "b.ng", "non_compliant", "unable_to_determine")]
    assert errors[1]["tool_note"] == "tool says non_compliant" and errors[1]["scan_id"] and errors[1]["error_category"] == ""


def test_the_annotators_score_uses_the_same_formula_as_the_tool(world):
    sc = run(world)["scores"]
    rows = {r["site"]: r for r in sc["rows"]}
    assert set(rows) == {"a.ng", "b.ng", "c.ng"}  # d.ng was blocked
    assert rows["a.ng"]["gold_weighted"] == rows["a.ng"]["tool_weighted"] and rows["a.ng"]["gold_band"] == rows["a.ng"]["tool_band"]  # identical labels, identical score
    assert rows["b.ng"]["gold_weighted"] != rows["b.ng"]["tool_weighted"]
    assert sc["n"] == 3 and 0 <= sc["band_agreement"] <= 1 and sc["mean_abs_error"] > 0 and sc["sensitivity_n"] == 3


def test_a_site_with_unfinished_annotation_gets_no_gold_score(tmp_path, world):
    sites = world["sites"]
    partial = tmp_path / "p.csv"
    partial.write_text("site,rule_id,label,na_reason,evidence_ref,notes\nhttps://a.ng,CN-02,Non-Compliant,,,\nhttps://a.ng,SB-03,Non-Compliant,,,\nhttps://a.ng,CK-01,,,,\n")
    result = report.evaluate(world["tool"], load_annotations(partial, IDS, sites), None, None, RULEBOOK, world["manifest"])
    assert result["scores"]["rows"] == [] and result["coverage"]["fully_annotated_sites"] == 0 and result["coverage"]["blank_rows"] == 1
    assert result["detection"]["overall"]["n"] == 2  # but the two labelled items are still compared


def second_sheet(world):
    return load_annotations(sheet(world["tmp"], "a2.csv", {"a.ng": {"CN-02": "Non-Compliant", "SB-03": "Non-Compliant"},
                                                           "b.ng": {"CN-02": "Non-Compliant", "CN-01": "Non-Compliant"}}), IDS, world["sites"])


def test_agreement_between_the_two_annotators(world):
    ia = run(world, second=second_sheet(world))["inter_annotator"]
    assert ia["sites"] == 2 and ia["items"] == 34 and round(ia["agreement"], 3) == round(32 / 34, 3)
    assert round(ia["kappa"], 3) == 0.717 and ia["kappa_band"] == "substantial"  # (32/34 - 916/1156) / (1 - 916/1156)
    assert [(d["site"], d["rule_id"], d["annotator1"], d["annotator2"]) for d in ia["disagreements"]] == [
        ("b.ng", "CN-02", "compliant", "non_compliant"), ("b.ng", "PP-06", "non_compliant", "compliant")]
    assert run(world)["inter_annotator"] is None  # no second annotator, no agreement section


def test_an_adjudicated_label_replaces_the_first_annotators(world):
    adjudicated = load_annotations(_write(world["tmp"] / "adj.csv", "https://b.ng,CN-02,Non-Compliant"), IDS, world["sites"])
    result = run(world, second=second_sheet(world), adjudicated=adjudicated)
    cn02 = rule_row(result, "CN-02")
    assert (cn02["tp"], cn02["fp"], cn02["fn"]) == (2, 0, 1) and cn02["precision"] == 1.0 and round(cn02["recall"], 3) == 0.667  # b.ng is now a hit, not a false alarm
    assert result["coverage"]["adjudicated_items"] == 1 and result["coverage"]["unresolved_disagreements"] == 1  # the PP-06 disagreement is still open
    assert ("b.ng", "CN-02") not in {(e["site"], e["rule_id"]) for e in result["errors"]}


def _write(path, row):
    path.write_text("site,rule_id,label,na_reason,evidence_ref,notes\n" + row + ",,,\n")
    return path


def test_the_files_are_written_and_the_summary_explains_itself(world):
    result = run(world, second=second_sheet(world))
    out = world["tmp"] / "out"
    written = report.write_outputs(result, out)
    assert {p.name for p in written} == {"per_rule.csv", "per_category.csv", "scores.csv", "block_rate.csv", "errors.csv", "disagreements.csv", "summary.md", "report.json"}
    text = (out / "summary.md").read_text()
    assert "TRIAL RUN" in text  # this corpus was scanned with no freeze record
    assert "1 of 4 sites that could be reached refused" in text and "Positive class = non-compliant" in text and "Wilson" in text and "error_category" in text
    assert "| CN-02 |" in text and "n/a" in text  # an undefined number is shown as n/a, never as 0
    rows = list(csv.DictReader(open(out / "per_rule.csv")))
    assert next(r for r in rows if r["rule_id"] == "PP-06")["precision"] == "" and next(r for r in rows if r["rule_id"] == "SB-03")["recall"] == "1.0"
    assert len(list(csv.DictReader(open(out / "errors.csv")))) == 5 and json.loads((out / "report.json").read_text())["block_rate"]["blocked"] == 1


def test_a_frozen_run_is_not_marked_as_a_trial(world):
    world["manifest"].freeze = {"rulebook_version": "2.0.0", "files": {"rulebook/rules.v2.yaml": {"sha256": "x", "bytes": 1}}}
    text = report.summary_markdown(run(world))
    assert "TRIAL RUN" not in text  # (a changed frozen file is reported separately, with a WARNING)


def test_the_command_line_writes_a_report_and_explains_a_bad_sheet(world, capsys):
    tmp = world["tmp"]
    world["manifest"].save(tmp / "runs")
    args = ["--run", "t", "--annotator1", str(tmp / "a1.csv"), "--db", str(tmp / "eval.db"), "--manifest-dir", str(tmp / "runs"), "--out", str(tmp / "rep")]
    report.main(args)
    assert (tmp / "rep" / "summary.md").exists() and "Evaluation report: t" in capsys.readouterr().out
    bad = tmp / "bad.csv"
    bad.write_text("site,rule_id,label,na_reason,evidence_ref,notes\nhttps://a.ng,CN-02,Perhaps,,,\nhttps://zzz.ng,CN-02,Compliant,,,\n")
    with pytest.raises(SystemExit) as stop:
        report.main(["--run", "t", "--annotator1", str(bad), "--db", str(tmp / "eval.db"), "--manifest-dir", str(tmp / "runs"), "--out", str(tmp / "never")])
    assert "'Perhaps' is not a label" in str(stop.value) and "not in the corpus" in str(stop.value) and not (tmp / "never").exists()
''',
    "tests/integration/test_eval_flow.py": r'''"""The evaluation end to end: scan two local pages with a real browser, then compare with a perfect and an imperfect annotator."""
import csv

import pytest

from ndpa.capture.run import BrowserConfig
from ndpa.evaluation import corpus, report
from ndpa.evaluation.labels import load_annotations, normalise_site
from ndpa.scan import ScanOptions, run_scan
from ndpa.scoring.score import load_rulebook
from ndpa.storage import db

pytestmark = pytest.mark.browser


def write_sheet(path, site, outcomes):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "rule_id", "label", "na_reason", "evidence_ref", "notes"])
        for rule, label in outcomes.items():
            w.writerow([site, rule, label, "no trigger" if label == "Not Applicable" else "", "", ""])


def test_a_corpus_run_and_its_report(site, tmp_path):
    options = ScanOptions(observe_s=1, browser=BrowserConfig(channel=None, headless=True), vantage="test lab", retry_pause_s=0)
    db_path = tmp_path / "eval.db"

    def scanner(url):
        return run_scan(url, db_path, tmp_path / "evidence", options, say_out=lambda *_: None)

    reachable = f"{site}/banner_fake_reject.html"
    refused = site.replace("127.0.0.1", "localhost") + "/blocked.html"  # another name for the same machine, so it is a different site
    manifest = corpus.run_corpus([reachable, refused], "t", scanner, "test lab", pause_s=0, manifest_dir=tmp_path / "runs",
                                 freeze_file=tmp_path / "no-freeze.json", allow_unfrozen=True, say=lambda *a: None, sleep=lambda s: None)
    assert {u: e["status"] for u, e in manifest.entries.items()} == {reachable: "done", refused: "blocked"}

    conn = db.connect(db_path)
    tool = report.load_tool(conn, manifest)
    rulebook = load_rulebook()
    ids = [r["id"] for r in report.scored_rules(rulebook)]
    key = normalise_site(reachable)
    found = {rule: outcome.value for rule, (outcome, _note) in tool[key].outcomes.items()}
    assert found["CN-02"] == "non_compliant"  # the fake Reject still sets a cookie
    label = {"compliant": "Compliant", "non_compliant": "Non-Compliant", "not_applicable": "Not Applicable", "unable_to_determine": "Compliant"}

    perfect = tmp_path / "perfect.csv"
    write_sheet(perfect, reachable, {rule: label[found[rule]] for rule in ids})  # an annotator who agrees with the tool on everything
    sites = {normalise_site(u) for u in manifest.planned}
    result = report.evaluate(tool, load_annotations(perfect, ids, sites), None, None, rulebook, manifest)
    overall = result["detection"]["overall"]
    assert overall["fp"] == 0 and overall["fn"] == 0 and overall["tp"] >= 1 and overall["f1"] == 1.0
    assert result["errors"] == [] and result["scores"]["rows"][0]["gold_weighted"] == result["scores"]["rows"][0]["tool_weighted"]
    blk = result["block_rate"]
    assert (blk["done"], blk["blocked"], blk["block_rate"]) == (1, 1, 0.5) and blk["blocked_sites"] == [refused]

    flawed = tmp_path / "flawed.csv"  # an annotator who thinks the fake Reject was honest
    write_sheet(flawed, reachable, {rule: ("Compliant" if rule == "CN-02" else label[found[rule]]) for rule in ids})
    result = report.evaluate(tool, load_annotations(flawed, ids, sites), None, None, rulebook, manifest)
    assert result["detection"]["overall"]["fp"] == 1 and [e["rule_id"] for e in result["errors"]] == ["CN-02"]
    assert result["errors"][0]["evidence_folder"].startswith(str(tmp_path / "evidence"))  # the error sheet points at the evidence

    written = report.write_outputs(result, tmp_path / "report")
    assert (tmp_path / "report" / "summary.md").exists() and len(written) == 7
''',
}

EXPECTED_LINES = {
    "src/ndpa/evaluation/__init__.py": 1,
    "src/ndpa/evaluation/metrics.py": 94,
    "src/ndpa/evaluation/labels.py": 154,
    "src/ndpa/evaluation/corpus.py": 183,
    "src/ndpa/evaluation/report.py": 375,
    "tests/unit/test_eval_metrics.py": 48,
    "tests/unit/test_eval_labels.py": 81,
    "tests/unit/test_eval_corpus.py": 124,
    "tests/unit/test_eval_report.py": 220,
    "tests/integration/test_eval_flow.py": 63,
}


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def edit_once(path, marker, old, new):
    """Replace `old` with `new` once. `marker` is text that only exists after the edit, so running twice is harmless."""
    s = read(path)
    if marker in s:
        print("  already there:", path, "|", marker)
        return
    assert s.count(old) == 1, f"{path}: could not find the place to edit ('{old[:50]}'). Paste me the lines around it."
    pathlib.Path(path).write_text(s.replace(old, new), encoding="utf-8")
    print("  edited:", path)


def append_once(path, marker, text):
    if marker in read(path):
        print("  already there:", path, "|", marker)
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
    print("  added to:", path, "|", marker)


# 1. The code and its tests
for name, text in FILES.items():
    target = pathlib.Path(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
print(f"wrote {len(FILES)} files")

# 2. Check that every file arrived complete and compiles (a cut-off paste fails here, loudly)
problems = []
for name, expected in EXPECTED_LINES.items():
    got = len(read(name).splitlines())
    if got != expected:
        problems.append(f"{name}: {got} lines, expected {expected}")
    try:
        py_compile.compile(name, doraise=True)
    except py_compile.PyCompileError as error:
        problems.append(f"{name}: does not compile ({error.msg.splitlines()[-1]})")
assert not problems, "The paste was not complete:\n  " + "\n  ".join(problems) + "\nPaste the whole script again."
print(f"all {len(FILES)} files arrived complete and compile")

# 3. Documentation, ignore rules
edit_once("README.md", "## Evaluation", "## Where things are", """## Evaluation

The evaluation compares the tool with human annotators on a fixed corpus (`my_site_list.txt`). Run it after the rulebook is frozen.

1. Scan the whole corpus. It is resumable (run the same command again to continue), polite (a pause between sites), randomised
   with a fixed seed, and watches the 72-hour window. Add `--limit 3 --allow-unfrozen` for a trial first: a trial must not be reported.
   ```bash
   python -m ndpa.evaluation.corpus --name eval-1 --vantage "Port Harcourt, NG (home network)"
   ```
2. Each annotator copies `eval/templates/annotation_template.csv` to `eval/annotations/` and fills it in. They can check their sheet at any time:
   ```bash
   python -m ndpa.evaluation.labels eval/annotations/annotator1.csv --sites my_site_list.txt
   ```
3. Produce the report: coverage, block rate, precision, recall and F1 per rule and per category (with 95% intervals), agreement between the
   annotators, the score compared with the annotators' score, and `errors.csv` for the error analysis. Everything is written to
   `data/eval_reports/eval-1/`, starting with `summary.md`.
   ```bash
   python -m ndpa.evaluation.report --run eval-1 --annotator1 eval/annotations/annotator1.csv \\
       --annotator2 eval/annotations/annotator2.csv --adjudicated eval/annotations/adjudicated.csv
   ```
   `--annotator2` and `--adjudicated` are optional.
4. To browse the corpus scans in the dashboard: `python -m ndpa.web --db data/eval.db`.

## Where things are""")
edit_once("README.md", "`src/ndpa/evaluation/`", "| `src/ndpa/web/` |", "| `src/ndpa/evaluation/` | the evaluation: corpus runner, label-sheet checks, statistics and the report |\n| `src/ndpa/web/` |")
append_once(".gitignore", "data/eval_evidence/", "\n# evaluation corpus evidence (large). The run manifests in data/eval_runs/ and the reports in data/eval_reports/ are kept in git.\ndata/eval_evidence/\n")
append_once("docs/backlog.md", "B-40", """
## Added 7 Nov 2026 (evaluation harness)
- B-40 A dashboard Evaluation page (precision, recall and F1 tables, block rate, error list), once there are real numbers to show.
- B-41 The Cookiescanner comparison on the overlapping rules is not built: it needs that external tool and network access. Decide at the pilot whether it is still wanted.
- B-42 The report treats 'unable to determine' as an abstention. If many appear on one rule, investigate that rule before reporting.
- B-43 Per-rule intervals with about 30 sites are wide. Chapter 4 should say so, and lean on the category and overall numbers.
- B-44 Trial run first: python -m ndpa.evaluation.corpus --name trial --limit 3 --allow-unfrozen --vantage "...", then check the dashboard with --db data/eval.db. Delete the trial manifest in data/eval_runs/ afterwards.
""")
append_once("docs/decisions.md", "D-45", """
## Update 7 Nov 2026 (evaluation harness)

- D-45 The positive class is non-compliant ("the tool finds a violation"). TP, FP, FN, TN are counted per rule and summed for categories and overall (micro). Macro F1 is shown beside it. Every undefined number is shown as n/a, never as zero.
- D-46 'Unable to determine' exists only in the tool. It is reported as an abstention; recall is shown both ways: without abstentions (lenient) and with each abstention on a gold non-compliant case counted as a miss (strict).
- D-47 Gold = annotator 1, overridden by an adjudicated sheet where one exists. A second annotator gives agreement (percentage and Cohen's kappa) and a disagreements sheet for adjudication. Intervals are 95% Wilson intervals.
- D-48 Blocked and failed scans have no outcomes: they are left out of the comparison and counted in the block rate. Annotators' labels are scored with the tool's own scoring formula, so the score comparison is like for like. Weighted versus equal-weight sensitivity is reported, and the weights are never tuned.
- D-49 The corpus run is resumable, shuffled by a fixed seed, paused between sites, saved after every site, and refuses to run on an unfrozen or changed rulebook (a trial flag overrides this and marks the report as a trial). It records the freeze hashes and the 72-hour window. Sites are matched by host (without www, keeping a non-default port).
""")
print("\nDone. Now run:  python -m ruff check src tests eval   and   python -m pytest -q")