import web_seed as ws

from ndpa.storage import db
from ndpa.web import views


def conn_for(tmp_path):
    return db.connect(tmp_path / "t.db")


def two_scans(tmp_path):
    conn = conn_for(tmp_path)
    a = ws.seed_scan(conn, tmp_path / "ev", "shop.ng", "2026-10-28T09:12:44+00:00", ws.problem_site())
    b = ws.seed_scan(conn, tmp_path / "ev", "shop.ng", "2026-11-04T22:06:59+00:00", ws.better_site())
    return conn, a, b


# ---------- progress ----------
def rows(*pairs):
    return [{"id": i + 1, "at": "t", "stage": s, "message": m} for i, (s, m) in enumerate(pairs)]


def states(rs, status="running"):
    return {s["key"]: s["state"] for s in views.stage_states(rs, status)}


def test_stages_move_from_pending_to_running_to_done():
    assert set(states([], "queued").values()) == {"pending"}
    s = states(rows(("no_action", "capturing"), ("no_action", "ok"), ("accept", "capturing")))
    assert s["no_action"] == "done" and s["accept"] == "running" and s["reject"] == "pending"


def test_a_retry_keeps_the_stage_running_with_an_explanation():
    out = views.stage_states(rows(("no_action", "capturing"), ("no_action", "failed (net::ERR_EMPTY_RESPONSE); trying again in 20 s")), "running")
    assert out[0]["state"] == "running" and "once more" in out[0]["message"]


def test_a_blocked_scan_skips_the_remaining_stages():
    s = states(rows(("no_action", "capturing"), ("no_action", "blocked"), ("rules", "evaluating"), ("saving", "x"), ("done", "blocked")), "blocked")
    assert s["no_action"] == "blocked" and s["accept"] == "skipped" and s["policy"] == "skipped"


def test_an_error_fails_the_stage_that_was_running_and_done_completes_everything():
    s = states(rows(("no_action", "capturing"), ("error", "Chrome not found")), "failed")
    assert s["no_action"] == "failed" and s["accept"] == "skipped"
    assert set(states(rows(("saving", "x"), ("done", "done")), "done").values()) == {"done"}


def test_policy_messages_are_translated():
    out = {s["key"]: s for s in views.stage_states(rows(("policy", "looking for the privacy and cookie policies"), ("policy", "found_unlinked")), "running")}
    assert out["policy"]["state"] == "done" and "guessing" in out["policy"]["message"]


# ---------- one scan ----------
def test_scan_view_has_findings_in_rulebook_groups_and_the_headline_numbers(tmp_path):
    conn, _a, b = two_scans(tmp_path)
    v = views.scan_view(conn, b)
    assert len(v["findings"]) == 17 and v["card"]["band"] == "high" and v["card"]["total_weight"] == 28
    assert [g["key"] for g in v["groups"]] == ["consent", "script_behaviour", "trackers", "cookies", "privacy_policy"]
    assert v["counts"]["non_compliant"] == len(v["fixes"]) and "gauge" in v and "radar" in v and len(v["bars"]) == 5
    assert v["previous"]["id"] == _a and [s["path"] for s in v["screenshots"]][0] == "no_action/screenshot.png"
    assert v["verify_command"].endswith(v["scan"]["manifest_hash"])


def test_findings_are_enriched_with_the_rulebook_and_evidence_is_tabulated(tmp_path):
    conn, _a, b = two_scans(tmp_path)
    f = {x["rule_id"]: x for x in views.scan_view(conn, b)["findings"]}
    assert f["SB-03"]["name"] and f["SB-03"]["fix"] and f["SB-03"]["tier_label"] == "Critical" and f["SB-03"]["tone"] == "bad"
    table = f["SB-03"]["evidence_table"]
    assert table["columns"][0] == "Run" and "First seen (ms)" in table["columns"] and table["total"] == 1


def test_fix_first_orders_by_tier_then_how_many_are_affected(tmp_path):
    conn, a, _b = two_scans(tmp_path)
    fixes = views.scan_view(conn, a)["fixes"]
    tiers = [f["tier"] for f in fixes]
    assert tiers == sorted(tiers, key=lambda t: {"critical": 0, "major": 1, "minor": 2}[t])
    critical = [f for f in fixes if f["tier"] == "critical"]
    assert [f["instances_failed"] for f in critical] == sorted([f["instances_failed"] for f in critical], reverse=True)


def test_blocked_and_failed_scans_have_no_gauge_or_radar(tmp_path):
    conn = conn_for(tmp_path)
    blocked = ws.seed_scan(conn, tmp_path / "ev", "gt.com", results=None, status="blocked")
    failed = ws.seed_scan(conn, tmp_path / "ev", "old.ng", "2026-11-01T10:00:00+00:00", results=None, status="failed", error="DNS")
    vb = views.scan_view(conn, blocked)
    assert "radar" not in vb and vb["findings"] == [] and vb["runs"][0]["block_reasons"]
    assert "radar" not in views.scan_view(conn, failed)
    assert views.scan_view(conn, 999) is None


def test_the_first_scan_of_a_site_has_no_previous(tmp_path):
    conn, a, _b = two_scans(tmp_path)
    assert views.scan_view(conn, a)["previous"] is None


# ---------- history and comparison ----------
def test_history_deltas_stats_and_the_latest_two(tmp_path):
    conn, a, b = two_scans(tmp_path)
    h = views.history_view(conn, "shop.ng")
    assert [s["id"] for s in h["scans"]] == [b, a] and h["scans"][0]["delta"] > 0 and h["scans"][1]["delta"] is None
    assert h["latest_two"] == [b, a] and h["stats"]["count"] == 2 and h["stats"]["change"] == round(h["stats"]["latest"] - h["stats"]["first"], 1)
    assert views.history_view(conn, "nope.ng") is None


def test_hosts_view_shows_the_trend(tmp_path):
    conn, _a, _b = two_scans(tmp_path)
    ws.seed_scan(conn, tmp_path / "ev", "other.ng", "2026-11-05T10:00:00+00:00", ws.better_site())
    hosts = views.hosts_view(conn)
    assert [h["host"] for h in hosts] == ["other.ng", "shop.ng"]
    assert hosts[0]["trend"] is None and hosts[1]["trend"] > 0 and hosts[1]["count"] == 2


def test_compare_groups_changes_and_orders_the_scans(tmp_path):
    conn, a, b = two_scans(tmp_path)
    c = views.compare_view(conn, b, a)  # asked in the wrong order on purpose
    assert c["a"]["id"] == a and c["b"]["id"] == b and c["delta"] > 0
    fixed = {r["rule_id"] for r in c["groups"]["fixed"]}
    assert {"CN-01", "CN-02", "CN-03", "SB-02", "PP-06", "PP-05"} <= fixed
    assert {r["rule_id"] for r in c["groups"]["still"]} >= {"SB-01", "SB-03"} and c["groups"]["new"] == []
    assert sum(len(v) for v in c["groups"].values()) == 17 and c["radar"] and len(c["category_rows"]) == 5
    assert views.compare_view(conn, a, 999) is None


def test_compare_warns_when_the_scans_were_run_differently(tmp_path):
    conn, a, b = two_scans(tmp_path)
    conn.execute("UPDATE scan SET browser_version = '142.0.1', vantage = 'Lagos, NG' WHERE id = ?", (b,))
    conn.commit()
    labels = {d["label"] for d in views.compare_view(conn, a, b)["differences"]}
    assert labels == {"Chrome version", "Scanned from"}
    conn2, x, y = two_scans(tmp_path / "again")
    assert views.compare_view(conn2, x, y)["differences"] == []


# ---------- timeline and evidence ----------
def test_timeline_tallies_before_and_after_the_click(tmp_path):
    conn, _a, b = two_scans(tmp_path)
    runs = {r["condition"]: r for r in views.timeline_view(conn, b)}
    assert set(runs) == {"no_action", "accept", "reject"}
    first = runs["no_action"]
    assert first["after"] is None and first["before"]["trackers"] == 40 and len(first["before"]["vendors"]) == 12
    assert "_ga" in first["before"]["cookies"] and "JSESSIONID" not in first["before"]["cookies"]  # a Necessary cookie is not flagged
    reject = runs["reject"]
    assert reject["click_ms"] == 13800 and reject["after"] is not None and reject["action"] == "Reject" and "tl-click" in str(reject["svg"])
    assert len(first["first_events"]) == 14 and first["total_marks"] > 14


def test_artifacts_and_evidence_tables(tmp_path):
    conn, _a, b = two_scans(tmp_path)
    paths = {a["path"] for a in views.artifacts_view(conn, b)}
    assert {"results.json", "meta.json", "no_action/screenshot.png"} <= paths
    assert "verify.py" not in paths and "manifest.json" not in paths  # the verifier and the manifest are outside the chain
    t = views.evidence_display([{"a_ms": 1, "list": ["x", "y"], "flag": True, "none": None, "d": {"k": "v"}}] * 10)
    assert t["columns"][0] == "A (ms)" and t["rows"][0] == ["1", "x, y", "yes", "", "k: v"] and len(t["rows"]) == 8 and len(t["more"]) == 2
    assert views.evidence_display(["not a dict"])["rows"] == []


def test_formatting_helpers():
    assert views.format_dt("2026-11-04T22:05:21+00:00") == "4 Nov 2026, 22:05 UTC" and views.format_dt(None) == ""
    assert "403" in views.describe_block("http_403") and "just a moment" in views.describe_block("marker: just a moment")
    assert views.describe_block("odd") == "odd"
