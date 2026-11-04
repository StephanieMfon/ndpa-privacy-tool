"""SQLite storage (decision D-21). Evidence files stay canonical; this indexes scans for history and the dashboard."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ndpa.models import Event, RunResult, ScoreCard

DEFAULT_DB = Path("data/ndpa.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS scan (
  id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, host TEXT NOT NULL, status TEXT NOT NULL,
  rulebook_version TEXT, rulebook_sha256 TEXT, tracker_list_sha256 TEXT, tool_version TEXT, browser_version TEXT,
  vantage TEXT, started_at TEXT, finished_at TEXT, folder TEXT, manifest_hash TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS ix_scan_host ON scan(host, id);
CREATE TABLE IF NOT EXISTS run (
  id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id INTEGER NOT NULL REFERENCES scan(id), condition TEXT NOT NULL,
  status TEXT NOT NULL, attempts INTEGER, consent_click_ms INTEGER, load_ms INTEGER, block_reasons TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES run(id), t_ms INTEGER NOT NULL,
  kind TEXT NOT NULL, domain TEXT, third_party INTEGER, vendor TEXT, detail_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_event_run_t ON event(run_id, t_ms);
CREATE TABLE IF NOT EXISTS finding (
  id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id INTEGER NOT NULL REFERENCES scan(id), rule_id TEXT NOT NULL,
  tier TEXT, category TEXT, outcome TEXT NOT NULL, instances_failed INTEGER, instances_total INTEGER,
  root_cause TEXT, note TEXT, evidence_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_finding_scan ON finding(scan_id, rule_id);
CREATE TABLE IF NOT EXISTS score (
  scan_id INTEGER PRIMARY KEY REFERENCES scan(id), score_weighted REAL, score_equal REAL, band TEXT,
  critical_count INTEGER, coverage REAL, scored_weight REAL, total_weight REAL, category_json TEXT,
  empty_categories_json TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS artifact (
  id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id INTEGER NOT NULL REFERENCES scan(id), path TEXT NOT NULL,
  sha256 TEXT NOT NULL, bytes INTEGER, chain_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS progress (
  id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id INTEGER NOT NULL REFERENCES scan(id), at TEXT NOT NULL,
  stage TEXT NOT NULL, message TEXT
);
CREATE INDEX IF NOT EXISTS ix_progress_scan ON progress(scan_id, id);
"""

SCAN_COLUMNS = {"status", "rulebook_version", "rulebook_sha256", "tracker_list_sha256", "tool_version",
                "browser_version", "vantage", "started_at", "finished_at", "folder", "manifest_hash", "error"}
FINAL_STATUSES = {"done", "blocked", "failed"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path = DEFAULT_DB, share_across_threads: bool = False) -> sqlite3.Connection:
    """share_across_threads: the web framework opens a connection in one worker thread and closes it in another.
    A connection is only ever used by one request at a time, so this is safe."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=not share_across_threads)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


def create_scan(conn: sqlite3.Connection, url: str, host: str, vantage: str, status: str = "queued") -> int:
    """A scan row that has not started yet (the dashboard needs its id before the scan runs)."""
    cur = conn.execute("INSERT INTO scan (url, host, status, started_at, vantage) VALUES (?,?,?,?,?)",
                       (url, host, status, now(), vantage))
    conn.commit()
    return cur.lastrowid


def insert_scan(conn: sqlite3.Connection, url: str, host: str, folder: str, vantage: str, **env) -> int:
    scan_id = create_scan(conn, url, host, vantage, status="running")
    update_scan(conn, scan_id, folder=folder, **env)
    return scan_id


def update_scan(conn: sqlite3.Connection, scan_id: int, **fields) -> None:
    unknown = set(fields) - SCAN_COLUMNS
    if unknown:
        raise ValueError(f"unknown scan columns: {sorted(unknown)}")
    names = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE scan SET {names} WHERE id = ?", (*fields.values(), scan_id))
    conn.commit()


def log_progress(conn: sqlite3.Connection, scan_id: int, stage: str, message: str = "") -> None:
    conn.execute("INSERT INTO progress (scan_id, at, stage, message) VALUES (?,?,?,?)", (scan_id, now(), stage, message))
    conn.commit()


def progress_rows(conn: sqlite3.Connection, scan_id: int, after_id: int = 0) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, at, stage, message FROM progress WHERE scan_id = ? AND id > ? ORDER BY id", (scan_id, after_id))]


def insert_run(conn: sqlite3.Connection, scan_id: int, run: RunResult, attempts: int = 1) -> int:
    cur = conn.execute(
        "INSERT INTO run (scan_id, condition, status, attempts, consent_click_ms, load_ms, block_reasons, error) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (scan_id, run.condition.value, run.status.value, attempts, run.consent.click_ms, run.load_ms,
         json.dumps(run.block_reasons), run.error))
    run_id = cur.lastrowid
    insert_events(conn, run_id, run.events)
    conn.commit()
    return run_id


def insert_events(conn: sqlite3.Connection, run_id: int, events: list[Event]) -> None:
    conn.executemany(
        "INSERT INTO event (run_id, t_ms, kind, domain, third_party, vendor, detail_json) VALUES (?,?,?,?,?,?,?)",
        [(run_id, e.t_ms, e.kind, e.domain, None if e.third_party is None else int(e.third_party), e.vendor,
          json.dumps(e.detail)) for e in events])


def insert_findings(conn: sqlite3.Connection, scan_id: int, rows: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO finding (scan_id, rule_id, tier, category, outcome, instances_failed, instances_total, root_cause, "
        "note, evidence_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(scan_id, r["rule_id"], r["tier"], r["category"], r["outcome"], r["instances_failed"], r["instances_total"],
          r["root_cause"], r["note"], json.dumps(r["evidence"])) for r in rows])
    conn.commit()


def insert_score(conn: sqlite3.Connection, scan_id: int, card: ScoreCard) -> None:
    conn.execute(
        "INSERT INTO score (scan_id, score_weighted, score_equal, band, critical_count, coverage, scored_weight, "
        "total_weight, category_json, empty_categories_json, note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (scan_id, card.score_weighted, card.score_equal, card.band, card.critical_count, card.coverage,
         card.scored_weight, card.total_weight, json.dumps(card.category_scores), json.dumps(card.empty_categories),
         card.note))
    conn.commit()


def insert_artifacts(conn: sqlite3.Connection, scan_id: int, entries: list[dict]) -> None:
    conn.executemany("INSERT INTO artifact (scan_id, path, sha256, bytes, chain_sha256) VALUES (?,?,?,?,?)",
                     [(scan_id, e["path"], e["sha256"], e["bytes"], e["chain"]) for e in entries])
    conn.commit()


def get_scan(conn: sqlite3.Connection, scan_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM scan WHERE id = ?", (scan_id,)).fetchone()
    return dict(row) if row else None


def list_scans(conn: sqlite3.Connection, host: str | None = None, limit: int | None = None) -> list[dict]:
    """Newest first, with the headline score. Used for history and re-scan comparison."""
    sql = ("SELECT scan.id, scan.url, scan.host, scan.status, scan.started_at, score.score_weighted, score.band, "
           "score.critical_count, score.coverage FROM scan LEFT JOIN score ON score.scan_id = scan.id")
    args: list = []
    if host:
        sql += " WHERE scan.host = ?"
        args.append(host)
    sql += " ORDER BY scan.id DESC"
    if limit:
        sql += " LIMIT ?"
        args.append(limit)
    return [dict(r) for r in conn.execute(sql, args)]


def get_findings(conn: sqlite3.Connection, scan_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM finding WHERE scan_id = ? ORDER BY id", (scan_id,))]
