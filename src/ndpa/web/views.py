"""Everything the pages need, shaped from the database and the rulebook. No HTML here."""
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from ndpa.rules.context import NecessaryCookies
from ndpa.scoring.score import load_rulebook
from ndpa.storage import db
from ndpa.web import charts

CATEGORY_ORDER = ["consent", "script_behaviour", "trackers", "cookies", "privacy_policy"]
CATEGORY_LABELS = {"cookies": "Cookies", "consent": "Consent banner", "trackers": "Trackers",
                   "script_behaviour": "Scripts", "privacy_policy": "Privacy policy"}
OUTCOMES = {"compliant": ("Passed", "ok"), "non_compliant": ("Failed", "bad"),
            "not_applicable": ("Not applicable", "na"), "unable_to_determine": ("Could not check", "unk")}
TIERS = {"critical": "Critical", "major": "Major", "minor": "Minor"}
TIER_ORDER = {"critical": 0, "major": 1, "minor": 2}
STAGES = [("no_action", "First visit, no clicks"), ("accept", "Visit, then click Accept"),
          ("reject", "Visit, then click Reject"), ("policy", "Find the privacy policy"),
          ("rules", "Check the 17 rules"), ("saving", "Save and seal the evidence")]
SHOWN_FILES = [("no_action/screenshot.png", "First visit, before any click"),
               ("accept/after_click.png", "After clicking Accept"), ("reject/after_click.png", "After clicking Reject")]


@lru_cache(maxsize=1)
def rulebook() -> dict:
    return load_rulebook()


@lru_cache(maxsize=1)
def necessary() -> NecessaryCookies:
    return NecessaryCookies.load()


def describe_block(reason: str) -> str:
    """The detector's codes (http_403, marker: just a moment, ...) in words a visitor can read."""
    known = {"http_403": "the server answered 'forbidden' (403)", "http_429": "the server said there were too many requests (429)",
             "cloudflare_challenge_header": "a Cloudflare challenge page", "empty_page": "a page with almost no content"}
    if reason in known:
        return known[reason]
    if reason.startswith("marker: "):
        return f"a security page saying \"{reason[8:]}\""
    return reason


def format_dt(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%-d %b %Y, %H:%M UTC")
    except ValueError:
        return iso


# ---------- progress ----------
def stage_states(rows: list[dict], scan_status: str) -> list[dict]:
    """The six stages of a scan with a state each: pending, running, done, blocked, failed or skipped."""
    state = {key: {"key": key, "label": label, "state": "pending", "message": ""} for key, label in STAGES}
    last_running = None
    for r in rows:
        stage, msg = r["stage"], r["message"] or ""
        if stage in ("run", "done", "queued"):
            continue
        if stage == "error":
            if last_running:
                state[last_running].update(state="failed", message=msg)
            continue
        if stage not in state:
            continue
        s = state[stage]
        if stage in ("no_action", "accept", "reject"):
            if msg == "capturing":
                s.update(state="running", message="Opening the site in Chrome")
                last_running = stage
            elif msg.startswith("failed ("):
                s.update(state="running", message="Could not load it. Trying once more.")
            else:
                s.update(state={"ok": "done", "blocked": "blocked", "failed": "failed"}.get(msg, "done"),
                         message={"blocked": "The site refused an automated visit.", "failed": "The site could not be loaded."}.get(msg, ""))
        elif stage == "policy":
            if msg.startswith("looking"):
                s.update(state="running", message="Following links in the footer")
                last_running = stage
            else:
                s.update(state="done", message={"found_linked": "Found by following links.", "found_unlinked": "Only found by guessing the address.",
                                                "exhaustive_negative": "No policy found.", "uncertain": "Could not be sure."}.get(msg, msg))
        elif stage in ("rules", "saving"):
            s.update(state="running", message="Working it out" if stage == "rules" else "Storing results and sealing the evidence")
            last_running = stage
    if scan_status == "done":
        for s in state.values():
            if s["state"] in ("pending", "running"):
                s["state"] = "done"
    elif scan_status in ("blocked", "failed"):
        for s in state.values():
            if s["state"] == "pending":
                s["state"] = "skipped"
            elif s["state"] == "running":
                s["state"] = "failed" if scan_status == "failed" else "skipped"
    return list(state.values())


# ---------- one scan ----------
def _cell(value) -> str:
    if isinstance(value, dict):
        text = "; ".join(f"{str(k).replace('_', ' ')}: {_cell(v)}" for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        text = ", ".join(_cell(v) for v in value) if value else "none"
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    else:
        text = "" if value is None else str(value)
    return text if len(text) <= 180 else text[:177] + "..."


def evidence_display(rows: list, shown: int = 8) -> dict:
    """Evidence rows as a small table: columns are the keys the rows share, longest values are shortened."""
    dicts = [r for r in rows if isinstance(r, dict)]
    columns: list[str] = []
    for r in dicts:
        for k in r:
            if k not in columns and len(columns) < 6:
                columns.append(k)
    runs = {"no_action": "No clicks", "accept": "After Accept", "reject": "After Reject"}
    table = [[runs.get(str(r.get(c)), _cell(r.get(c))) if c == "run" else _cell(r.get(c)) for c in columns] for r in dicts]
    names = {"first_t_ms": "First seen (ms)", "t_ms": "Time (ms)", "first_seen_after_load_ms": "First seen after load (ms)"}

    def title(name: str) -> str:
        if name in names:
            return names[name]
        name = name[:-3] + " (ms)" if name.endswith("_ms") else name
        text = name.replace("_", " ")
        return text[:1].upper() + text[1:]

    return {"columns": [title(c) for c in columns], "rows": table[:shown], "more": table[shown:], "total": len(table)}


def _findings(conn, scan_id: int) -> list[dict]:
    rules = {r["id"]: r for r in rulebook()["rules"]}
    out = []
    for row in db.get_findings(conn, scan_id):
        rule = rules.get(row["rule_id"], {})
        label, tone = OUTCOMES[row["outcome"]]
        out.append({**row, "name": rule.get("name", row["rule_id"]), "legal": rule.get("legal", []),
                    "fix": (rule.get("remediation") or {}).get("fix", ""), "clause": (rule.get("remediation") or {}).get("clause", ""),
                    "evidence": json.loads(row["evidence_json"] or "[]"),
                    "evidence_table": evidence_display(json.loads(row["evidence_json"] or "[]")), "outcome_label": label, "tone": tone,
                    "tier_label": TIERS.get(row["tier"], ""), "category_label": CATEGORY_LABELS.get(row["category"], row["category"]),
                    "anchor": row["rule_id"].lower()})
    return out


def _card(conn, scan_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM score WHERE scan_id = ?", (scan_id,)).fetchone()
    if row is None:
        return None
    return {"weighted": row["score_weighted"], "equal": row["score_equal"], "band": row["band"],
            "critical_count": row["critical_count"], "coverage": row["coverage"], "scored_weight": row["scored_weight"],
            "total_weight": row["total_weight"], "categories": json.loads(row["category_json"] or "{}"),
            "empty": json.loads(row["empty_categories_json"] or "[]"), "note": row["note"] or ""}


def radar_axes(card: dict) -> list[dict]:
    return [{"key": k, "label": CATEGORY_LABELS[k], "value": card["categories"].get(k, 0), "empty": k in card["empty"]}
            for k in rulebook()["scoring"]["category_axes"]]


def previous_scan(conn, scan: dict) -> dict | None:
    row = conn.execute("SELECT scan.id, scan.started_at, score.category_json FROM scan JOIN score ON score.scan_id = scan.id "
                       "WHERE scan.host = ? AND scan.id < ? AND scan.status = 'done' AND score.score_weighted IS NOT NULL "
                       "ORDER BY scan.id DESC LIMIT 1", (scan["host"], scan["id"])).fetchone()
    return None if row is None else {"id": row["id"], "started_at": row["started_at"], "categories": json.loads(row["category_json"])}


def fix_first(findings: list[dict]) -> list[dict]:
    rows = [f for f in findings if f["outcome"] == "non_compliant"]
    return sorted(rows, key=lambda f: (TIER_ORDER.get(f["tier"], 9), -(f["instances_failed"] or 0), f["rule_id"]))


def grouped(findings: list[dict]) -> list[dict]:
    by_cat = {}
    for f in findings:
        by_cat.setdefault(f["category"], []).append(f)
    return [{"key": c, "label": CATEGORY_LABELS[c], "findings": by_cat[c]} for c in CATEGORY_ORDER if c in by_cat]


def scan_view(conn, scan_id: int) -> dict | None:
    from ndpa.web.summary import plain_summary
    scan = db.get_scan(conn, scan_id)
    if scan is None:
        return None
    card, findings = _card(conn, scan_id), _findings(conn, scan_id)
    prev = previous_scan(conn, scan)
    folder = Path(scan["folder"]) if scan.get("folder") else None
    runs = [dict(r) for r in conn.execute("SELECT * FROM run WHERE scan_id = ? ORDER BY id", (scan_id,))]
    for r in runs:
        r["block_reasons"] = json.loads(r["block_reasons"] or "[]")
    screenshots = [{"path": p, "label": label} for p, label in SHOWN_FILES if folder and (folder / p).exists()]
    counts = {k: sum(1 for f in findings if f["outcome"] == k) for k in OUTCOMES}
    view = {"scan": scan, "card": card, "findings": findings, "groups": grouped(findings), "fixes": fix_first(findings),
            "counts": counts, "runs": runs, "screenshots": screenshots, "previous": prev,
            "summary": plain_summary(card, findings), "started": format_dt(scan["started_at"]),
            "finished": format_dt(scan["finished_at"])}
    if card and card["categories"]:
        view["gauge"] = charts.gauge_svg(card["weighted"], card["band"])
        view["radar"] = charts.radar_svg(radar_axes(card), prev["categories"] if prev else None)
        view["bars"] = [{"label": a["label"], "value": a["value"], "empty": a["empty"],
                         "svg": charts.bar_svg(a["value"], prev["categories"].get(a["key"]) if prev else None, f"{a['label']}: {a['value']:g} out of 100")}
                        for a in radar_axes(card)]
    elif card:
        view["gauge"] = charts.gauge_svg(None, None)
    if card:
        view["coverage_bar"] = charts.bar_svg(round(card["coverage"] * 100), label=f"{card['coverage']:.0%} of the rulebook could be assessed")
    view["verify_command"] = (f"python {folder / 'verify.py'} --expect {scan['manifest_hash']}" if folder and scan.get("manifest_hash") else "")
    return view


# ---------- history ----------
def hosts_view(conn) -> list[dict]:
    hosts = []
    for (host,) in conn.execute("SELECT host FROM scan GROUP BY host ORDER BY MAX(id) DESC").fetchall():
        scans = db.list_scans(conn, host)
        scored = [s for s in scans if s["score_weighted"] is not None]
        latest = scans[0]
        trend = None
        if len(scored) >= 2:
            trend = round(scored[0]["score_weighted"] - scored[1]["score_weighted"], 1)
        hosts.append({"host": host, "count": len(scans), "latest": latest, "trend": trend})
    return hosts


def history_view(conn, host: str) -> dict | None:
    scans = db.list_scans(conn, host)
    if not scans:
        return None
    oldest_first = list(reversed(scans))
    last_score = None
    for s in oldest_first:
        s["delta"] = None
        if s["score_weighted"] is not None:
            if last_score is not None:
                s["delta"] = round(s["score_weighted"] - last_score, 1)
            last_score = s["score_weighted"]
        s["when"] = format_dt(s["started_at"])
    scored = [s["score_weighted"] for s in oldest_first if s["score_weighted"] is not None]
    stats = None
    if scored:
        stats = {"first": scored[0], "latest": scored[-1], "change": round(scored[-1] - scored[0], 1), "count": len(scored)}
    return {"host": host, "scans": scans, "spark": charts.sparkline_svg([s["score_weighted"] for s in oldest_first]), "stats": stats,
            "latest_two": [s["id"] for s in scans if s["status"] == "done"][:2]}


# ---------- comparison ----------
GOOD_AFTER = {"compliant", "not_applicable"}


def _change(before: str, after: str) -> str:
    if before == "non_compliant" and after in GOOD_AFTER:
        return "fixed"
    if after == "non_compliant" and before != "non_compliant":
        return "new"
    if before == after == "non_compliant":
        return "still"
    return "same" if before == after else "other"


def compare_view(conn, a_id: int, b_id: int) -> dict | None:
    a_id, b_id = sorted((a_id, b_id))
    sa, sb = db.get_scan(conn, a_id), db.get_scan(conn, b_id)
    if not sa or not sb:
        return None
    ca, cb = _card(conn, a_id), _card(conn, b_id)
    fa, fb = {f["rule_id"]: f for f in _findings(conn, a_id)}, {f["rule_id"]: f for f in _findings(conn, b_id)}
    rows = []
    for rule in rulebook()["rules"]:
        rid = rule["id"]
        if rid in fa and rid in fb:
            before, after = fa[rid], fb[rid]
            rows.append({"rule_id": rid, "name": rule["name"], "tier_label": TIERS.get(rule["tier"], ""), "tier": rule["tier"],
                         "before": before, "after": after, "change": _change(before["outcome"], after["outcome"])})
    groups = {k: [r for r in rows if r["change"] == k] for k in ("fixed", "new", "still", "other", "same")}
    for k in groups:
        groups[k].sort(key=lambda r: (TIER_ORDER.get(r["tier"], 9), r["rule_id"]))
    differences = []
    for label, key in (("Rulebook version", "rulebook_version"), ("Rulebook file", "rulebook_sha256"), ("Tracker list", "tracker_list_sha256"),
                       ("Tool version", "tool_version"), ("Chrome version", "browser_version"), ("Scanned from", "vantage")):
        va, vb = sa.get(key), sb.get(key)
        if va != vb:
            def short(v, is_hash=key.endswith("sha256")):
                return (v or "unknown")[:12] if is_hash else (v or "unknown")
            differences.append({"label": label, "a": short(va), "b": short(vb)})
    delta = None
    if ca and cb and ca["weighted"] is not None and cb["weighted"] is not None:
        delta = round(cb["weighted"] - ca["weighted"], 1)
    view = {"a": sa, "b": sb, "ca": ca, "cb": cb, "groups": groups, "delta": delta, "differences": differences,
            "a_when": format_dt(sa["started_at"]), "b_when": format_dt(sb["started_at"]), "same_host": sa["host"] == sb["host"]}
    if ca and cb and ca["categories"] and cb["categories"]:
        view["radar"] = charts.radar_svg(radar_axes(cb), ca["categories"])
        view["category_rows"] = [{"label": a["label"], "a": ca["categories"].get(a["key"], 0), "b": cb["categories"].get(a["key"], 0)}
                                 for a in radar_axes(cb)]
        for r in view["category_rows"]:
            r["delta"] = round(r["b"] - r["a"], 1)
    return view


# ---------- timeline ----------
def _vendor_label(e: dict) -> str:
    return e["vendor"] or e["domain"] or "unknown"


def timeline_view(conn, scan_id: int) -> list[dict]:
    nec = necessary()
    out = []
    for run in conn.execute("SELECT * FROM run WHERE scan_id = ? ORDER BY id", (scan_id,)).fetchall():
        events = [dict(r) for r in conn.execute("SELECT t_ms, kind, domain, third_party, vendor, detail_json FROM event WHERE run_id = ? ORDER BY t_ms", (run["id"],))]
        marks = []
        for e in events:
            d = json.loads(e["detail_json"] or "{}")
            if e["kind"] == "request" and d.get("tracker") and e["third_party"]:
                marks.append({"lane": "tracker", "t_ms": e["t_ms"], "label": f"{_vendor_label(e)} ({d.get('resource_type', 'request')})", "flag": True,
                              "vendor": _vendor_label(e)})
            elif e["kind"] == "cookie_set_js":
                bad = not nec.is_necessary(d["name"])
                marks.append({"lane": "script_cookie", "t_ms": e["t_ms"], "label": f"{d['name']} set by {d.get('script') or 'an unknown script'}",
                              "flag": bad, "cookie": d["name"] if bad else None})
            elif e["kind"] == "response":
                for name in d.get("set_cookie_names", []):
                    bad = not nec.is_necessary(name)
                    marks.append({"lane": "server_cookie", "t_ms": e["t_ms"], "flag": bad, "cookie": name if bad else None,
                                  "label": f"{name} sent by {e['domain']}" + (" (third party)" if e["third_party"] else "")})
            elif e["kind"] == "storage_set":
                marks.append({"lane": "storage", "t_ms": e["t_ms"], "label": f"{d.get('area')}: {d.get('key')}", "flag": bool(e["vendor"])})
        click = run["consent_click_ms"]
        t_max = max([e["t_ms"] for e in events] + [click or 0, run["load_ms"] or 0, 1000]) + 600
        action = {"accept": "Accept", "reject": "Reject"}.get(run["condition"], "")
        before = [m for m in marks if click is None or m["t_ms"] < click]
        after = [m for m in marks if click is not None and m["t_ms"] >= click]

        def tally(ms):
            return {"trackers": len([m for m in ms if m["lane"] == "tracker"]),
                    "vendors": sorted({m["vendor"] for m in ms if m["lane"] == "tracker"}),
                    "cookies": sorted({m["cookie"] for m in ms if m.get("cookie")})}
        out.append({"condition": run["condition"], "status": run["status"], "action": action, "click_ms": click, "load_ms": run["load_ms"],
                    "before": tally(before), "after": tally(after) if click is not None else None,
                    "svg": charts.timeline_svg(marks, t_max, click, f"You click {action}" if action else "", run["load_ms"]),
                    "first_events": sorted(marks, key=lambda m: m["t_ms"])[:14], "total_marks": len(marks)})
    return out


# ---------- evidence ----------
def artifacts_view(conn, scan_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT path, sha256, bytes, chain_sha256 FROM artifact WHERE scan_id = ? ORDER BY id", (scan_id,))]


# ---------- home ----------
def recent_view(conn, limit: int = 8) -> list[dict]:
    rows = db.list_scans(conn, limit=limit)
    for r in rows:
        r["when"] = format_dt(r["started_at"])
    return rows
