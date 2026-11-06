"""Builds realistic scans (database rows plus a sealed evidence folder) for the dashboard tests and demos."""
import json
import shutil
from pathlib import Path

from ndpa.evidence import chain
from ndpa.models import Condition, ConsentObservation, Event, Outcome, RuleResult, RunResult, RunStatus, ScanStatus
from ndpa.scoring.score import load_rulebook, score
from ndpa.storage import db

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")
C, N, A, U = (Outcome.COMPLIANT, Outcome.NON_COMPLIANT, Outcome.NOT_APPLICABLE, Outcome.UNABLE_TO_DETERMINE)
VENDORS = ["Google Ads (Google)", "Google Analytics (Google)", "Criteo", "Taboola", "Amazon.com", "Microsoft", "Index Exchange",
           "OpenX", "The Trade Desk", "Verizon Media", "Lotame Solutions", "RTB House"]


def finding(rule_id, outcome, note="", evidence=None, failed=0, total=0, root=None):
    return RuleResult(rule_id=rule_id, outcome=outcome, note=note, evidence=evidence or [], instances_failed=failed,
                      instances_total=total, root_cause=root)


def default_results() -> dict[str, RuleResult]:
    rb = load_rulebook()
    return {r["id"]: finding(r["id"], C, "Passed.") for r in rb["rules"] if r["tier"] != "unscored"}


def problem_site() -> dict[str, RuleResult]:
    """Results shaped like a site with trackers and no banner."""
    r = default_results()
    rows = [{"run": "no_action", "vendor": v, "requests": 3 + i, "first_t_ms": 700 + 300 * i, "resource_types": ["script", "xhr"]}
            for i, v in enumerate(VENDORS)]
    cookies = [{"run": "no_action", "cookie": c, "how": ["script"], "t_ms": 900 + 100 * i} for i, c in enumerate(["_ga", "_gid", "_fbp", "IDE", "cto_bundle", "_gcl_au", "tluid", "uuid2", "MUID"])]
    r["CN-01"] = finding("CN-01", N, "no consent banner was visible", [{"banner": "not found"}])
    r["CN-02"] = finding("CN-02", N, "9 non-necessary cookie(s) set without consent. no Reject run: only cookies before consent were assessed", cookies, 9, 9)
    r["CN-03"] = finding("CN-03", N, "no banner or panel appeared in any run, so no reject option is offered", [{"banner": "not found"}], root="CN-01")
    r["CN-04"] = finding("CN-04", A, "no banner or panel appeared in any run: nothing to record or withdraw (captured under CN-01 and CN-03)")
    r["CN-05"] = finding("CN-05", A, "no banner or panel appeared in any run: nothing to record or withdraw (captured under CN-01 and CN-03)")
    r["SB-01"] = finding("SB-01", N, "12 non-necessary script source(s) active without consent", rows, 12, 12)
    r["SB-02"] = finding("SB-02", N, "scripts or third parties set 9 non-necessary cookie(s) without consent", cookies, 9, 9)
    r["SB-03"] = finding("SB-03", N, "requests to 12 tracking vendor(s) without consent", rows, 12, 12)
    r["TR-02"] = finding("TR-02", N, "11 of 12 detected trackers are not named", [{"vendor": v, "named": False, "domains": ["x.example"]} for v in VENDORS[1:]], 11, 12)
    r["CK-01"] = finding("CK-01", N, "3 cookie(s) last longer than 365 days with no justification", [{"cookie": "_fbp", "domain": ".facebook.com", "lifespan_days": 400, "justified": False}], 3, 9)
    r["CK-02"] = finding("CK-02", N, "5 of 5 third-party cookie owners are not named", [{"owner": "Criteo", "named": False, "cookies": ["cto_bundle"], "cookie_count": 1}], 5, 5)
    r["PP-02"] = finding("PP-02", N, "no cookie policy, cookie section, or banner text stating what cookies are used for")
    r["PP-04"] = finding("PP-04", N, "no sentence names a type of data together with a specific use")
    r["PP-05"] = finding("PP-05", N, "no retention period or clear end-trigger")
    r["PP-06"] = finding("PP-06", N, "7 core right(s) not disclosed: access, rectification, erasure, restriction, portability, objection, complaint_to_NDPC",
                         [{"rights": {"access": "missing", "rectification": "missing", "erasure": "missing", "restriction": "missing", "portability": "missing", "objection": "missing", "complaint_to_NDPC": "missing"}}], 7, 7)
    r["PP-03"] = finding("PP-03", C, "a privacy contact email is given", [{"email_domain": "shop.example", "matched_by": "privacy-named address"}])
    return r


def better_site() -> dict[str, RuleResult]:
    r = problem_site()
    r["CN-01"] = finding("CN-01", C, "banner at the centre_modal covering 26%", [{"position": "centre_modal", "coverage": 0.26, "bottom_row_only": False, "first_seen_after_load_ms": 14}])
    r["CN-02"] = finding("CN-02", C, "no non-necessary cookie before consent or after Reject.")
    r["CN-03"] = finding("CN-03", C, "reject option 'Reject all' found (banner)")
    r["CN-04"] = finding("CN-04", C, "the choice persisted after reload")
    r["CN-05"] = finding("CN-05", C, "re-open control found: 'Cookie settings'")
    r["SB-02"] = finding("SB-02", C, "no script set a non-necessary cookie before consent or after Reject")
    r["SB-03"] = finding("SB-03", N, "requests to 2 tracking vendor(s) without consent", [{"run": "no_action", "vendor": "Google Analytics (Google)", "requests": 4, "first_t_ms": 800, "resource_types": ["xhr"]}], 2, 2)
    r["SB-01"] = finding("SB-01", N, "2 non-necessary script source(s) active without consent", [{"run": "no_action", "vendor": "Google Analytics (Google)", "requests": 4, "first_t_ms": 800, "resource_types": ["xhr"]}], 2, 2)
    r["PP-06"] = finding("PP-06", C, "all seven core rights are disclosed or explained")
    r["PP-05"] = finding("PP-05", C, "the policy states how long data is kept", [{"text": "We keep order records for seven years to comply with tax law."}])
    return r


def _events(kind: str) -> list[Event]:
    ev = []
    for i in range(40):
        ev.append(Event(t_ms=800 + i * 220, kind="request", domain="t.example", third_party=True, vendor=VENDORS[i % len(VENDORS)],
                        detail={"tracker": True, "resource_type": ["script", "xhr", "image"][i % 3], "url": "https://t.example/x"}))
    for i, name in enumerate(["_ga", "_gid", "JSESSIONID", "_fbp", "IDE", "cmp_consent", "cto_bundle"]):
        ev.append(Event(t_ms=1500 + i * 700, kind="cookie_set_js", domain="t.example", third_party=True, detail={"name": name, "script": "https://t.example/a.js", "attributed": True}))
    ev.append(Event(t_ms=300, kind="response", domain="shop.example", third_party=False, detail={"set_cookie_names": ["PHPSESSID", "lang"], "resource_type": "document"}))
    ev.append(Event(t_ms=2600, kind="response", domain="ads.example", third_party=True, detail={"set_cookie_names": ["uid"], "resource_type": "image"}))
    for i in range(5):
        ev.append(Event(t_ms=2000 + i * 900, kind="storage_set", domain="t.example", third_party=True, vendor=VENDORS[i] if i % 2 == 0 else None, detail={"area": "localStorage", "key": f"k{i}"}))
    return ev


def seed_scan(conn, root: Path, host="shop.ng", started="2026-11-04T22:05:21+00:00", results=None, status="done",
              vantage="Port Harcourt, NG", screenshot: bytes | None = PNG, error=None) -> int:
    results = results or problem_site()
    rb = load_rulebook()
    scan_id = db.create_scan(conn, f"https://{host}/", host, vantage, status="running")
    folder = root / host / started.replace(":", "-")
    folder.mkdir(parents=True, exist_ok=True)
    scan_status = {"done": ScanStatus.DONE, "blocked": ScanStatus.BLOCKED, "failed": ScanStatus.FAILED}[status]
    items = list(results.values()) if status == "done" else []
    card = score(items, rb, scan_status)
    rules = {r["id"]: r for r in rb["rules"]}
    rows = [{"rule_id": r.rule_id, "tier": rules[r.rule_id]["tier"], "category": rules[r.rule_id]["category"], "outcome": r.outcome.value,
             "instances_failed": r.instances_failed, "instances_total": r.instances_total, "root_cause": r.root_cause, "note": r.note,
             "evidence": r.evidence} for r in items]
    if status != "failed":
        for cond, click in ((Condition.NO_ACTION, None), (Condition.ACCEPT, 14000), (Condition.REJECT, 13800)):
            if status == "blocked" and cond != Condition.NO_ACTION:
                continue
            run = RunResult(url=f"https://{host}/", condition=cond, status=RunStatus.BLOCKED if status == "blocked" else RunStatus.OK, observe_s=10,
                            load_ms=3200, events=[] if status == "blocked" else _events(cond.value),
                            block_reasons=["http_403", "marker: just a moment"] if status == "blocked" else [],
                            consent=ConsentObservation(click_ms=click if status == "done" else None))
            db.insert_run(conn, scan_id, run)
            if screenshot and status == "done":
                name = "screenshot.png" if cond == Condition.NO_ACTION else "after_click.png"
                (folder / cond.value).mkdir(exist_ok=True)
                (folder / cond.value / name).write_bytes(screenshot)
    (folder / "results.json").write_text(json.dumps({"status": status, "rules": rows}))
    (folder / "meta.json").write_text(json.dumps({"url": f"https://{host}/", "status": status}))
    shutil.copy(Path(chain.__file__), folder / chain.VERIFIER)
    manifest = chain.build_manifest(folder)
    db.insert_findings(conn, scan_id, rows)
    db.insert_score(conn, scan_id, card)
    db.insert_artifacts(conn, scan_id, manifest["entries"])
    db.update_scan(conn, scan_id, status=status, started_at=started, finished_at=started, folder=str(folder), manifest_hash=manifest["final"],
                   browser_version="141.0.7390.37", tool_version="a1b2c3d", rulebook_version=str(rb.get("meta", {}).get("version", "2.0.0-draft2")),
                   rulebook_sha256="9f" * 32, tracker_list_sha256="3c" * 32, error=error)
    for stage, msg in (("no_action", "capturing"), ("no_action", "ok"), ("done", status)):
        db.log_progress(conn, scan_id, stage, msg)
    return scan_id
