"""Pre-freeze calibration: three small changes, each with tests. Paste this whole file into script.py and run:  python script.py

1. PP-06 recognises "the right to ask us not to process your data" (the right to object) as well as the word "object".
2. FCCDCF, Google's consent-platform record, is a necessary cookie (it stores the visitor's consent choice).
3. CN-02 applies the strict reading of the Close button for real (cookies set after a Close click count) and reports the
   implied reading (R5) alongside. Before this, a Close click was silently treated as consent.
Running it twice is harmless.
"""
import pathlib


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def write(path, text):
    pathlib.Path(path).write_text(text, encoding="utf-8")


def patch(path, old, new, marker=None):
    s = read(path)
    if (marker in s) if marker else (new in s and old not in s):
        print("  already applied:", path)
        return
    assert s.count(old) == 1, f"{path}: the expected text was not found exactly once. Paste me the lines around '{old[:40]}'."
    write(path, s.replace(old, new))
    print("  patched:", path)


def replace_between(path, start, end, new):
    s = read(path)
    if new in s:
        print("  already applied:", path)
        return
    assert s.count(start) == 1 and s.count(end) == 1, f"{path}: could not find the place to change ('{start[:40]}'). Paste me that part of the file."
    a, b = s.index(start), s.index(end)
    assert a < b, f"{path}: the markers are in an unexpected order."
    write(path, s[:a] + new + s[b:])
    print("  patched:", path)


def append_once(path, marker, text):
    if marker in read(path):
        print("  already there:", path, "|", marker)
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
    print("  added to:", path, "|", marker)


# 1. PP-06: the right to object, in the wording a Nigerian news site uses
patch("src/ndpa/rules/text.py", '''    "r_object": ["object*", "objection", "opt out", "opt - out"],''',
      '''    "r_object": ["object*", "objection", "opt out", "opt - out", "not to process", "stop processing", "prevent such processing"],''')

# 2. The consent record of Google's consent platform is a necessary cookie. FCNEC is left out on purpose: what it stores is unclear.
patch("rulebook/necessary_cookies.yaml", "    - wpca_cc\n    - sb-closed\n", "    - wpca_cc\n    - sb-closed\n    - FCCDCF\n", marker="    - FCCDCF\n")

# 3. CN-02: Close is not consent (strict), with the implied reading (R5) worked out alongside
replace_between("src/ndpa/rules/checks/consent.py", "def cn_02(ev: ScanEvidence, ctx: Ctx):", "def cn_03(ev: ScanEvidence, ctx: Ctx):", r'''def _after_close(ev: ScanEvidence, ctx: Ctx) -> list[dict]:
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


''')

# 4. Tests
append_once("tests/unit/test_rules_consent.py", "def close_scan", r'''

# CN-02 and the Close button (register R5: strict reading decides, implied reading is reported alongside)
def close_scan(*events, jar=None, geo=None, action="close"):
    """A banner with only a Close control: the Accept run clicks it at 5 s, and `events` happen after that."""
    first = run(cons=consent(geo=geo), events=[tracker_request(400)])  # a tracker makes this a consent site; no cookie before consent
    accepted = run(A, cons=consent(action=action, click_ms=5000), events=list(events), jar=jar)
    return scan(first, accept=accepted)


def close_rows(r):
    return [e for e in r.evidence if e["run"] == "close"]


def test_a_cookie_set_after_close_counts_under_the_strict_reading_but_the_implied_reading_excuses_a_first_party_one():
    r = check(c.cn_02, close_scan(server_cookie(6000, "prefs")))  # the site's own server, a conspicuous banner
    assert r.outcome == Outcome.NON_COMPLIANT and r.instances_failed == 1  # Close is not consent
    row = close_rows(r)[0]
    assert row["cookie"] == "prefs" and row["excused_if_implied"] is True and row["implied_outcome"] == "compliant"
    assert "after a Close click" in r.note and "implied reading (R5) this rule would be compliant" in r.note


def test_the_implied_reading_never_excuses_a_third_party_or_tracker_cookie():
    for event in (server_cookie(6000, "uid", third_party=True, domain="ads.example"), js_cookie(6000, "_ga", vendor="Google Analytics"), js_cookie(6000, "x")):
        r = check(c.cn_02, close_scan(event))
        row = close_rows(r)[0]
        assert r.outcome == Outcome.NON_COMPLIANT and row["excused_if_implied"] is False and row["implied_outcome"] == "non_compliant"


def test_the_implied_reading_needs_a_banner_that_passed_the_obstruction_test():
    strip = geometry(position="bottom", coverage=0.03, bottom_row_only=True, passes=False)
    r = check(c.cn_02, close_scan(server_cookie(6000, "prefs"), geo=strip))
    assert close_rows(r)[0]["excused_if_implied"] is False and close_rows(r)[0]["implied_outcome"] == "non_compliant"


def test_a_cookie_of_unknown_origin_is_not_excused():
    r = check(c.cn_02, close_scan(jar=[{"name": "mystery", "domain": "shop.example", "expires": -1}]))  # in the jar, no event says who set it
    assert close_rows(r)[0]["how"] == ["jar_only"] and close_rows(r)[0]["excused_if_implied"] is False


def test_the_strict_outcome_stays_compliant_when_nothing_is_set_after_close():
    r = check(c.cn_02, close_scan())
    assert r.outcome == Outcome.COMPLIANT and not close_rows(r)


def test_an_accept_click_is_consent_so_cookies_after_it_are_fine_and_nothing_about_close_is_added():
    r = check(c.cn_02, close_scan(server_cookie(6000, "prefs"), action="accept"))
    assert r.outcome == Outcome.COMPLIANT and "Close" not in r.note and not any("run" in e and e["run"] == "close" for e in r.evidence)


def test_cookies_before_consent_still_decide_even_when_close_cookies_are_excused():
    first = run(cons=consent(), cookies=["_ga"])  # a real violation before any click
    accepted = run(A, cons=consent(action="close", click_ms=5000), events=[server_cookie(6000, "prefs")])
    r = check(c.cn_02, scan(first, accept=accepted))
    assert r.outcome == Outcome.NON_COMPLIANT and close_rows(r)[0]["excused_if_implied"] is True and close_rows(r)[0]["implied_outcome"] == "non_compliant"
''')
append_once("tests/unit/test_rules_policy.py", "test_pp06_recognises_the_right_to_ask_us", r'''

def test_pp06_recognises_the_right_to_ask_us_not_to_process_data_for_marketing():
    text = "You have the right to ask us not to process your personal data for marketing purposes."  # a Nigerian news site's wording
    r = check(p.pp_06, scan_with_policy(text))
    assert r.evidence[0]["rights"]["objection"] == "disclosed" and r.instances_failed == 6
    stop = check(p.pp_06, scan_with_policy("You are entitled to request that we stop processing your data."))
    assert stop.evidence[0]["rights"]["objection"] == "disclosed"


def test_pp06_does_not_count_a_promise_that_is_not_a_right():
    r = check(p.pp_06, scan_with_policy("It is our policy not to process data without a legal basis."))
    assert r.evidence[0]["rights"]["objection"] == "missing"
''')
append_once("tests/unit/test_necessary_cookies.py", "the_google_consent_platform_record", r'''

def test_the_google_consent_platform_record_is_necessary_but_its_other_cookie_is_not_assumed_to_be():
    assert NECESSARY.is_necessary("FCCDCF") and NECESSARY.is_consent_state("FCCDCF")  # it stores the visitor's consent choice
    assert not NECESSARY.is_necessary("FCNEC")  # what it stores is unclear, so it stays non-necessary until the pilot decides
''')
patch("tests/integration/test_scan.py", "import sqlite3\n", "import json\nimport sqlite3\n", marker="import json\nimport sqlite3\n")
append_once("tests/integration/test_scan.py", "test_a_close_only_banner_is_judged_strictly", r'''

def test_a_close_only_banner_is_judged_strictly_and_the_implied_reading_is_reported(site, tmp_path):
    scan(f"{site}/banner_close_only.html", tmp_path)
    outcome, evidence = rows(tmp_path, "SELECT outcome, evidence_json FROM finding WHERE rule_id = 'CN-02'")[0]
    after_close = [e for e in json.loads(evidence) if e["run"] == "close"]
    assert outcome == "non_compliant" and after_close and {"excused_if_implied", "implied_outcome"} <= set(after_close[0])
    other = tmp_path / "other"
    other.mkdir()
    scan(f"{site}/banner_simple.html", other)  # an Accept button: Close is not involved
    evidence = rows(other, "SELECT evidence_json FROM finding WHERE rule_id = 'CN-02'")[0][0]
    assert not any(e["run"] == "close" for e in json.loads(evidence))
''')

# 5. Record the decisions
append_once("docs/decisions.md", "D-50", """
## Update 7 Nov 2026 (pre-freeze calibration)

- D-50 PP-06 recognises 'not to process', 'stop processing' and 'prevent such processing' as naming the right to object, as well as 'object', 'objection' and 'opt out'. It still needs a rights cue ('right', 'entitled', 'request', 'ask', 'exercise') and a data word in the same sentence. Found on punchng.com, whose policy offers the right to object to marketing in other words. Annotators decide from the rulebook, not from this word list; any difference is an error-analysis category.
- D-51 FCCDCF (Google Funding Choices consent record) is on the necessary list as a consent-state cookie. FCNEC is not: sources disagree on what it stores (some list it as analytics), so it stays non-necessary until the pilot decides. Annotators use the same list, so tell them.
- D-52 CN-02 applies the strict reading of Close (R5): a Close click is not consent, so cookies set after it count, and the outcome and score are the strict ones. The implied reading is worked out alongside, stated in the note and on each Close row (excused_if_implied, implied_outcome). It excuses a cookie only if the banner passed CN-01 and the site itself plainly set the cookie (no third party, no tracker vendor). A cookie's purpose cannot be read from observation, so first-party is the only test, and the note says so. The SB rules are unchanged: the rulebook defines Close only for CN-02.
""")
append_once("docs/backlog.md", "B-45", """
## Updated 7 Nov 2026 (pre-freeze calibration)
- B-01 DONE (D-50). B-08 DONE (D-52). B-38 DONE for FCCDCF (D-51); FCNEC stays open for the pilot.
- B-45 Ask the annotators which reading of Close their CN-02 label holds, and where the other goes (the notes column). The tool's CN-02 outcome is the strict one; the implied outcome is in the finding's evidence.
- B-46 The SB rules (SB-01 to SB-03) still look only at the time before consent and after Reject. If the rulebook later says a Close click is not consent for them too, they need the same window as CN-02.
- B-47 Remaining pre-freeze items: B-03 (PP-02, PP-04 and PP-05 word lists against the annotators), B-04 (contact forms for PP-03), B-10 and B-11 (confirm the necessary-cookie list and the cookie lifetime cap).
""")
print("\nDone. Now run:  python -m ruff check src tests eval   and   python -m pytest -q")