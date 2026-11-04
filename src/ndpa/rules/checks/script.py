"""SB-01 to SB-03 (rulebook section D). Windows: all of Run 1, and the Reject run after its click."""
from ndpa.models import Outcome
from ndpa.rules.context import Ctx, ScanEvidence, by_vendor, cookie_sets, result, tracker_requests, windows

NO_TRIGGER = "no consent trigger: no non-necessary cookie and no tracker in any run"
PASSIVE_TYPES = {"script", "stylesheet", "font"}  # fetching a tracker's file is not yet 'transmitting' (register R10)


def sb_01(ev: ScanEvidence, ctx: Ctx):
    """A non-necessary script is active: it transmits to a tracker, or writes a cookie or storage item (R10)."""
    if not ctx.trigger:
        return result("SB-01", Outcome.NOT_APPLICABLE, NO_TRIGGER)
    active, dormant = [], []
    for label, run, since in windows(ev):
        requests = tracker_requests(run, since)
        active += by_vendor([e for e in requests if e.detail.get("resource_type") not in PASSIVE_TYPES], label)
        dormant += by_vendor([e for e in requests if e.detail.get("resource_type") in PASSIVE_TYPES], label)
        for e in run.events:
            if since is not None and e.t_ms < since:
                continue
            if e.kind == "storage_set" and e.vendor:
                active.append({"run": label, "vendor": e.vendor, "wrote": f"{e.detail['area']}:{e.detail['key']}", "t_ms": e.t_ms})
            if e.kind == "cookie_set_js" and not ctx.necessary.is_necessary(e.detail["name"]):
                active.append({"run": label, "script": e.detail.get("script"), "vendor": e.vendor,
                               "wrote": f"cookie:{e.detail['name']}", "t_ms": e.t_ms})
    if active:
        who = {a.get("vendor") or a.get("script") or "unknown" for a in active}
        return result("SB-01", Outcome.NON_COMPLIANT, f"{len(who)} non-necessary script source(s) active without consent",
                      active, failed=len(who), total=len(who))
    if dormant:
        return result("SB-01", Outcome.NOT_APPLICABLE, "tracker scripts were loaded but stayed dormant (no calls, no writes)", dormant)
    return result("SB-01", Outcome.COMPLIANT, "no non-necessary script was active before consent or after Reject")


def sb_02(ev: ScanEvidence, ctx: Ctx):
    """A script (or a third-party response) sets a non-necessary cookie without consent."""
    if not ctx.trigger:
        return result("SB-02", Outcome.NOT_APPLICABLE, NO_TRIGGER)
    non_necessary, any_cookie = {}, False
    for label, run, since in windows(ev):
        for name, info in cookie_sets(run, ctx.necessary, since).items():
            non_necessary[(label, name)] = info
        any_cookie = any_cookie or bool(cookie_sets(run, ctx.necessary, since, include_necessary=True))
    by_script = {k: v for k, v in non_necessary.items() if set(v["hows"]) & {"script", "server_third_party"}}
    if by_script:
        evidence = [{"run": k[0], "cookie": k[1], "how": v["hows"], "domain": v["domain"], "t_ms": v["t_ms"]}
                    for k, v in by_script.items()]
        names = {k[1] for k in by_script}
        return result("SB-02", Outcome.NON_COMPLIANT, f"scripts or third parties set {len(names)} non-necessary cookie(s) without consent",
                      evidence, failed=len(names), total=len(names))
    if non_necessary and all(v["hows"] == ["jar_only"] for v in non_necessary.values()):
        return result("SB-02", Outcome.UNABLE_TO_DETERMINE, "non-necessary cookies exist but what set them was not observed")
    if not non_necessary and any_cookie:
        return result("SB-02", Outcome.NOT_APPLICABLE, "the only cookies are Necessary")
    return result("SB-02", Outcome.COMPLIANT, "no script set a non-necessary cookie before consent or after Reject")


def sb_03(ev: ScanEvidence, ctx: Ctx):
    """Any request to a third-party tracking domain before consent or after Reject (register R8 list)."""
    if not ctx.trigger:
        return result("SB-03", Outcome.NOT_APPLICABLE, NO_TRIGGER)
    evidence = []
    for label, run, since in windows(ev):
        evidence += by_vendor(tracker_requests(run, since), label)
    if evidence:
        vendors = {row["vendor"] for row in evidence}
        return result("SB-03", Outcome.NON_COMPLIANT, f"requests to {len(vendors)} tracking vendor(s) without consent",
                      evidence, failed=len(vendors), total=len(vendors))
    return result("SB-03", Outcome.COMPLIANT, "no request to a tracking domain before consent or after Reject")
