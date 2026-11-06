"""The dashboard: FastAPI, Jinja2 templates, server-drawn SVG charts, no front-end framework.

Run from the repository root:  python -m ndpa.web
"""
import hashlib
import json
import re
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from ndpa.storage import db
from ndpa.web import views
from ndpa.web.jobs import QueueFull, ScanManager, Settings
from ndpa.web.security import check_target, normalise_url, same_origin

HERE = Path(__file__).parent
ALLOWED_FILE = re.compile(r"^(?:(?:no_action|accept|reject)/(?:screenshot|after_click)\.png|results\.json|meta\.json|manifest\.json|verify\.py)$")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
       "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")


def _asset_version() -> str:
    h = hashlib.sha256()
    for name in ("app.css", "app.js"):
        h.update((HERE / "static" / name).read_bytes())
    return h.hexdigest()[:10]


def create_app(settings: Settings | None = None, manager: ScanManager | None = None) -> FastAPI:
    settings = settings or Settings()
    manager = manager or ScanManager(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        manager.start()  # also marks scans interrupted by a restart as failed
        yield

    app = FastAPI(title="NDPA Privacy Check", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.manager = manager
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters.update(
        dt=views.format_dt, short=lambda v, n=12: (v or "")[:n],
        signed=lambda v: "" if v is None else ("+" if v > 0 else "−" if v < 0 else "±") + f"{abs(v):g}",
        size=lambda n: f"{n / 1024:.0f} KB" if n and n >= 1024 else f"{n or 0} B",
        seconds=lambda ms: f"{ms / 1000:.1f} s", block_reason=views.describe_block)
    asset_version = _asset_version()

    def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
        base = {"settings": settings, "asset_version": asset_version, "rulebook_version": views.rulebook().get("meta", {}).get("version", ""),
                "rule_total": len([r for r in views.rulebook()["rules"] if r["tier"] != "unscored"]),
                "area_counts": {c: len([r for r in views.rulebook()["rules"] if r["category"] == c and r["tier"] != "unscored"])
                                for c in views.CATEGORY_LABELS}}
        return templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status_code)

    def get_conn(request: Request) -> Iterator:
        conn = db.connect(settings.db_path, share_across_threads=True)
        try:
            yield conn
        finally:
            conn.close()

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update({"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY"})
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    def not_found(request: Request, what: str = "page") -> HTMLResponse:
        return render(request, "error.html", 404, title="Not found", message=f"We could not find that {what}.")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return not_found(request)
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        return not_found(request)  # for example /scans/abc

    # ---------- home and starting scans ----------
    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, conn=Depends(get_conn)):
        return render(request, "home.html", recent=views.recent_view(conn, 8), error=None, typed="")

    @app.post("/scans")
    async def start_scan(request: Request, conn=Depends(get_conn)):
        if not same_origin(request.headers.get("origin"), request.headers.get("host"), request.headers.get("sec-fetch-site")):
            return render(request, "error.html", 403, title="Request refused", message="That request did not come from this dashboard.")
        body = await request.body()
        raw = (parse_qs(body[:4096].decode("utf-8", "replace")).get("url") or [""])[0]
        url = normalise_url(raw)
        error = await run_in_threadpool(check_target, url, settings.allow_private_targets)
        if not error:
            try:
                scan_id = app.state.manager.submit(url)
                return RedirectResponse(f"/scans/{scan_id}", status_code=303)
            except QueueFull as exc:
                error = str(exc)
        return render(request, "home.html", 400, recent=views.recent_view(conn, 8), error=error, typed=raw[:300])

    # ---------- one scan ----------
    @app.get("/scans/{scan_id}", response_class=HTMLResponse)
    def scan_page(request: Request, scan_id: int, conn=Depends(get_conn)):
        scan = db.get_scan(conn, scan_id)
        if scan is None:
            return not_found(request, "scan")
        if scan["status"] in ("queued", "running"):
            rows = db.progress_rows(conn, scan_id)
            return render(request, "progress.html", scan=scan, stages=views.stage_states(rows, scan["status"]),
                          last_id=rows[-1]["id"] if rows else 0, position=app.state.manager.queue_position(scan_id),
                          started=views.format_dt(scan["started_at"]))
        return render(request, "scan.html", tab="overview", v=views.scan_view(conn, scan_id))

    @app.get("/scans/{scan_id}/events")
    def scan_events(request: Request, scan_id: int):
        last = int(request.query_params.get("after") or request.headers.get("last-event-id") or 0)

        def stream() -> Iterator[str]:
            conn = db.connect(settings.db_path, share_across_threads=True)  # it may be closed from another thread when the visitor leaves

            def state(rows: list[dict], status: str) -> str:
                payload = json.dumps({"status": status, "stages": views.stage_states(rows, status),
                                      "position": app.state.manager.queue_position(scan_id)})
                return f"id: {rows[-1]['id'] if rows else 0}\nevent: state\ndata: {payload}\n\n"

            try:
                yield "retry: 2000\n\n"
                started, idle, cursor, sent = time.monotonic(), 0.0, last, None
                while time.monotonic() - started < 1800:
                    scan = db.get_scan(conn, scan_id)
                    if scan is None:
                        return
                    rows = db.progress_rows(conn, scan_id)
                    new = [r for r in rows if r["id"] > cursor]
                    for r in new:  # one update per step, in order, however quickly the steps happened
                        status = scan["status"] if r is new[-1] else "running"
                        yield state([x for x in rows if x["id"] <= r["id"]], status)
                        sent, cursor = status, r["id"]
                    if sent is None or (scan["status"] in db.FINAL_STATUSES and sent != scan["status"]):
                        yield state(rows, scan["status"])  # nothing new to say, but bring the page up to date
                        sent = scan["status"]
                    if scan["status"] in db.FINAL_STATUSES:
                        yield f"event: finished\ndata: {json.dumps({'status': scan['status']})}\n\n"
                        return
                    idle += 0.5
                    if idle >= 15:
                        idle = 0
                        yield ": keep-alive\n\n"
                    time.sleep(0.5)
            finally:
                conn.close()

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def finished_scan(request: Request, conn, scan_id: int):
        scan = db.get_scan(conn, scan_id)
        if scan is None:
            return None, not_found(request, "scan")
        if scan["status"] not in db.FINAL_STATUSES:
            return None, RedirectResponse(f"/scans/{scan_id}", status_code=303)
        return scan, None

    @app.get("/scans/{scan_id}/timeline", response_class=HTMLResponse)
    def timeline_page(request: Request, scan_id: int, conn=Depends(get_conn)):
        scan, early = finished_scan(request, conn, scan_id)
        if early:
            return early
        return render(request, "timeline.html", tab="timeline", v=views.scan_view(conn, scan_id), runs=views.timeline_view(conn, scan_id))

    @app.get("/scans/{scan_id}/evidence", response_class=HTMLResponse)
    def evidence_page(request: Request, scan_id: int, conn=Depends(get_conn)):
        scan, early = finished_scan(request, conn, scan_id)
        if early:
            return early
        return render(request, "evidence.html", tab="evidence", v=views.scan_view(conn, scan_id), artifacts=views.artifacts_view(conn, scan_id))

    @app.get("/scans/{scan_id}/file/{name:path}")
    def evidence_file(request: Request, scan_id: int, name: str, conn=Depends(get_conn)):
        scan = db.get_scan(conn, scan_id)
        if scan is None or not scan.get("folder") or not ALLOWED_FILE.match(name):
            return not_found(request, "file")
        folder = Path(scan["folder"]).resolve()
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            return not_found(request, "file")
        media = {".png": "image/png", ".json": "application/json", ".py": "text/plain; charset=utf-8"}[path.suffix]
        return FileResponse(path, media_type=media)

    @app.get("/api/scans/{scan_id}")
    def scan_json(scan_id: int, conn=Depends(get_conn)):
        scan = db.get_scan(conn, scan_id)
        if scan is None:
            return JSONResponse({"error": "scan not found"}, status_code=404)
        v = views.scan_view(conn, scan_id)
        keep = ("rule_id", "name", "tier", "category", "outcome", "instances_failed", "instances_total", "root_cause", "note", "evidence")
        return {"scan": scan, "score": v["card"], "findings": [{k: f[k] for k in keep} for f in v["findings"]],
                "fix_first": [f["rule_id"] for f in v["fixes"]]}

    # ---------- history and comparison ----------
    @app.get("/history", response_class=HTMLResponse)
    def history_index(request: Request, conn=Depends(get_conn)):
        return render(request, "hosts.html", hosts=views.hosts_view(conn))

    @app.get("/history/{host}", response_class=HTMLResponse)
    def history_page(request: Request, host: str, conn=Depends(get_conn)):
        h = views.history_view(conn, host)
        return not_found(request, "site") if h is None else render(request, "history.html", h=h)

    @app.get("/compare", response_class=HTMLResponse)
    def compare_page(request: Request, a: int = 0, b: int = 0, pick: list[int] = Query(default=[]), conn=Depends(get_conn)):
        if not (a and b) and len(set(pick)) == 2:  # the history page sends the two ticked scans as pick
            a, b = sorted(set(pick))
        c = views.compare_view(conn, a, b) if a and b and a != b else None
        if c is None:
            return not_found(request, "pair of scans")
        return render(request, "compare.html", c=c)

    return app
