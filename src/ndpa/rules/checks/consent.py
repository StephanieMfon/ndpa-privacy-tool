"""CN-01 to CN-05 (rulebook section B). Conventions for sites without cookies, trigger or mechanism: rulebook 0.6."""
from ndpa.models import Outcome
from ndpa.rules.context import Ctx, ScanEvidence, cookie_sets, result, windows

NO_TRIGGER = "no consent trigger: no non-necessary cookie and no tracker in any run"
NO_MECHANISM = "no banner or panel appeared in any run"


def cn_01(ev: ScanEvidence, ctx: Ctx):
    """Banner present at first observation and significantly obstructing (register R4)."""
    if not ctx.trigger:
        return result("CN-01", Outcome.NOT_APPLICABLE, NO_TRIGGER)
    c = ev.no_action.consent
    if not c.banner_found:
        return result("CN-01", Outcome.NON_COMPLIANT, "no consent banner was visible", [{"banner": "not found"}])
    g = c.banner_geometry
    seen = (c.banner_first_seen_ms or 0) - (ev.no_action.load_ms or 0)
    evidence = [{"position": g["position"], "coverage": g["coverage"], "bottom_row_only": g["bottom_row_only"],
                 "first_seen_after_load_ms": seen}]
    if g["passes_r4"]:
        return result("CN-01", Outcome.COMPLIANT, f"banner at the {g['position']} covering {g['coverage']:.0%}", evidence)
    why = "confined to the bottom row" if g["bottom_row_only"] else f"covers only {g['coverage']:.0%} of the screen"
    return result("CN-01", Outcome.NON_COMPLIANT, f"banner is {why} (position {g['position']})", evidence)


def _after_close(ev: ScanEvidence, ctx: Ctx) -> list[dict]:
    """Non-necessary cookies set after a Close click, each marked with whether the implied reading (R5) would excuse it.

    R5: Close counts as implied consent only if the banner passed the obstruction test (CN-01), and only for first-party
    cookies whose purpose is site functionality or first-party analytics. The tool cannot read a cookie's purpose, so the
    implied reading excuses a cookie only when the site itself plainly set it (no third party and no tracker vendor was
    involved) and the banner passed CN-01. A cookie of unknown origin is never excused."""
    acc = ev.accept
    if acc is None or acc.consent.action != "close" or acc.consent.click_ms is None:
        return []
    since = acc.consent.click_ms
    geometry = ev.no_action.consent.banner_geometry
    conspicuous = bool(geometry and geometry.get("passes_r4"))
    plainly_first_party: dict[str, bool] = {}
    for e in acc.events:
        if e.t_ms < since:
            continue
        names = [e.detail.get("name")] if e.kind == "cookie_set_js" else e.detail.get("set_cookie_names", []) if e.kind == "response" else []
        for name in names:
            plainly_first_party[name] = plainly_first_party.get(name, True) and e.third_party is False and not e.vendor
    return [{"cookie": name, "how": info["hows"], "t_ms": info["t_ms"], "excused_if_implied": conspicuous and plainly_first_party.get(name, False)}
            for name, info in cookie_sets(acc, ctx.necessary, since).items()]


def cn_02(ev: ScanEvidence, ctx: Ctx):
    """No non-necessary cookie before consent (Run 1) or after Reject (Reject run).

    Strict reading of Close (R5): a Close click is not consent, so cookies set after it count too. The implied reading is
    worked out alongside and stated in the note and on each Close row. The outcome, and so the score, is the strict one."""
    if not ctx.trigger:
        return result("CN-02", Outcome.NOT_APPLICABLE, NO_TRIGGER)
    evidence, total = [], set()
    for label, run, since in windows(ev):
        for name, info in cookie_sets(run, ctx.necessary, since).items():
            total.add(name)
            evidence.append({"run": label, "cookie": name, "how": info["hows"], "t_ms": info["t_ms"]})
    closed = _after_close(ev, ctx)
    counted_if_implied = {c["cookie"] for c in closed if not c["excused_if_implied"]} | {e["cookie"] for e in evidence}
    implied = "non_compliant" if counted_if_implied else "compliant"
    for c in closed:
        total.add(c["cookie"])
        evidence.append({"run": "close", "cookie": c["cookie"], "how": c["how"], "t_ms": c["t_ms"],
                         "excused_if_implied": c["excused_if_implied"], "implied_outcome": implied})
    note = "" if ev.reject and ev.reject.consent.click_ms is not None else "no Reject run: only cookies before consent were assessed"
    if evidence:
        names = sorted({e["cookie"] for e in evidence})
        text = f"{len(names)} non-necessary cookie(s) set without consent. {note}".strip()
        if closed:
            text += (f" {len(closed)} cookie(s) were set after a Close click, which is not consent (strict reading). "
                     f"Under the implied reading (R5) this rule would be {implied}.")
        return result("CN-02", Outcome.NON_COMPLIANT, text, evidence, failed=len(names), total=len(names))
    return result("CN-02", Outcome.COMPLIANT, f"no non-necessary cookie before consent or after Reject. {note}".strip())


def cn_03(ev: ScanEvidence, ctx: Ctx):
    """A reject control exists in the banner flow (a preferences panel counts)."""
    if not ctx.trigger:
        return result("CN-03", Outcome.NOT_APPLICABLE, NO_TRIGGER)
    if not ctx.mechanism:
        return result("CN-03", Outcome.NON_COMPLIANT, f"{NO_MECHANISM}, so no reject option is offered",
                      [{"banner": "not found"}], root_cause="CN-01")
    for run in ev.runs():
        reject = run.consent.reject_control
        if reject:
            return result("CN-03", Outcome.COMPLIANT, f"reject option '{reject['text']}' found ({reject['reached_via']})",
                          [{"run": run.condition.value, **reject}])
    return result("CN-03", Outcome.NON_COMPLIANT, "the banner offers no reject option",
                  [{"controls": {k: getattr(ev.no_action.consent, k) for k in ("accept_control", "settings_control", "close_control")}}])


def _accept_run(ev: ScanEvidence, rule_id: str, ctx: Ctx):
    """Common start for CN-04 and CN-05: returns (early result or None, accept run)."""
    if not ctx.trigger:
        return result(rule_id, Outcome.NOT_APPLICABLE, NO_TRIGGER), None
    if not ctx.mechanism:
        return result(rule_id, Outcome.NOT_APPLICABLE, f"{NO_MECHANISM}: nothing to record or withdraw "
                      "(captured under CN-01 and CN-03)"), None
    acc = ev.accept
    if acc is None or acc.consent.action not in ("accept", "close"):
        why = acc.consent.note if acc is not None and acc.consent.note else "no Accept run"
        return result(rule_id, Outcome.UNABLE_TO_DETERMINE, f"the Accept run could not be completed ({why})"), None
    return None, acc


def cn_04(ev: ScanEvidence, ctx: Ctx):
    """After Accept and a reload the choice is remembered (the banner does not come back). Client-observable only."""
    early, acc = _accept_run(ev, "CN-04", ctx)
    if early:
        return early
    c = acc.consent
    if c.banner_after_reload is None:
        return result("CN-04", Outcome.UNABLE_TO_DETERMINE, "the page could not be reloaded to check")
    new_cookies = [x["name"] for x in acc.cookies if x["name"] not in c.pre_click_cookie_names]
    new_storage = [k for k in acc.local_storage_keys if k not in c.pre_click_local_storage_keys]
    state_items = [n for n in new_cookies + new_storage if ctx.necessary.is_consent_state(n)]
    evidence = [{"banner_after_reload": c.banner_after_reload, "new_cookies": len(new_cookies),
                 "new_storage_keys": len(new_storage), "consent_state_items": state_items}]
    if c.banner_after_reload:
        return result("CN-04", Outcome.NON_COMPLIANT, "the banner came back after reload: no observable record of the choice", evidence)
    return result("CN-04", Outcome.COMPLIANT, "the choice persisted after reload", evidence)


def cn_05(ev: ScanEvidence, ctx: Ctx):
    """After consent there is an in-site control to revisit the choice."""
    early, acc = _accept_run(ev, "CN-05", ctx)
    if early:
        return early
    control = acc.consent.reopen_control
    if control:
        return result("CN-05", Outcome.COMPLIANT, f"re-open control found: '{control}'", [{"control": control}])
    return result("CN-05", Outcome.NON_COMPLIANT, "no in-site control to change the choice was found after consent")
