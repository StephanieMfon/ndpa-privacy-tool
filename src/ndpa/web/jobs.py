"""Runs scans one at a time in a background thread, each in its own process (decision D-32).

A scan opens a real browser, so scans wait their turn instead of running side by side. Every scan is a separate
process: if Chrome crashes, the dashboard keeps working. Progress is read from the database, never from the process.
"""
import os
import queue
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from ndpa.storage import db
from ndpa.urls import host_of


@dataclass
class Settings:
    db_path: Path = db.DEFAULT_DB
    evidence_root: Path = Path("data/evidence")
    log_dir: Path = Path("data/logs")
    vantage: str = "unspecified"        # where the scans run from; shown on every result (decision D-19)
    headless: bool = False
    bundled_chromium: bool = False
    observe_s: float = 10.0
    allow_private_targets: bool = False  # only for tests against a local fixture site
    max_queue: int = 10
    scan_timeout_s: float = 900.0


class QueueFull(Exception):
    pass


class ScanManager:
    def __init__(self, settings: Settings, runner=None):
        self.settings = settings
        self.runner = runner or self._subprocess_runner
        self._queue: queue.Queue = queue.Queue()
        self._pending: list[int] = []
        self._current: int | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Mark scans that were interrupted by a restart as failed, then start the worker."""
        conn = db.connect(self.settings.db_path)
        conn.execute("UPDATE scan SET status = 'failed', finished_at = ?, error = ? WHERE status IN ('queued', 'running')",
                     (db.now(), "The dashboard was restarted before this scan finished."))
        conn.commit()
        conn.close()
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="scan-worker", daemon=True)
            self._thread.start()

    def submit(self, url: str) -> int:
        with self._lock:
            if len(self._pending) + (1 if self._current else 0) >= self.settings.max_queue:
                raise QueueFull("Too many scans are waiting. Try again in a few minutes.")
            conn = db.connect(self.settings.db_path)
            scan_id = db.create_scan(conn, url, host_of(url), self.settings.vantage)
            db.log_progress(conn, scan_id, "queued", "waiting for its turn")
            conn.close()
            self._pending.append(scan_id)
            self._queue.put((scan_id, url))
            return scan_id

    def queue_position(self, scan_id: int) -> int | None:
        """0 means it is running now, 1 means next in line, None means it is not waiting."""
        with self._lock:
            if self._current == scan_id:
                return 0
            return self._pending.index(scan_id) + 1 if scan_id in self._pending else None

    def _loop(self) -> None:
        while True:
            scan_id, url = self._queue.get()
            with self._lock:
                self._pending.remove(scan_id)
                self._current = scan_id
            try:
                self._run_one(scan_id, url)
            finally:
                with self._lock:
                    self._current = None

    def _run_one(self, scan_id: int, url: str) -> None:
        problem = None
        try:
            self.runner(scan_id, url)
        except Exception as exc:  # noqa: BLE001
            problem = f"{type(exc).__name__}: {exc}"
        conn = db.connect(self.settings.db_path)
        status = (db.get_scan(conn, scan_id) or {}).get("status")
        if status not in db.FINAL_STATUSES:  # the process ended without recording a result
            message = problem or "The scan stopped unexpectedly."
            db.log_progress(conn, scan_id, "error", message)
            db.update_scan(conn, scan_id, status="failed", finished_at=db.now(), error=message)
        conn.close()

    def _subprocess_runner(self, scan_id: int, url: str) -> None:
        s = self.settings
        cmd = [sys.executable, "-m", "ndpa.scan", url, "--scan-id", str(scan_id), "--db", str(s.db_path),
               "--out-root", str(s.evidence_root), "--vantage", s.vantage, "--observe", str(s.observe_s)]
        if s.headless:
            cmd.append("--headless")
        if s.bundled_chromium:
            cmd.append("--bundled-chromium")
        s.log_dir.mkdir(parents=True, exist_ok=True)
        with open(s.log_dir / f"scan-{scan_id}.log", "wb") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                proc.wait(timeout=s.scan_timeout_s)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)  # the whole group, so Chrome goes too
                proc.wait()
                raise TimeoutError(f"The scan took longer than {s.scan_timeout_s / 60:g} minutes and was stopped.") from None
