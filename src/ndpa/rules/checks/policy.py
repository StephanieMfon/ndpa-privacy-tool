"""PP-01 to PP-06 (rulebook section E). They apply to every site, with or without a consent trigger."""
from ndpa.models import Outcome
from ndpa.rules.context import Ctx, ScanEvidence, result
from ndpa.rules.disclosures import collect, no_match
from ndpa.rules.text import (DURATION_RE, EMAIL_RE, PRIVACY_CUE_RE, PRIVACY_LOCAL_PART_RE, TRIGGER_RE,
                             VAGUE_RETENTION_RE, analyse, snippet)

RIGHTS = {  # right -> label of the lexicon group that names it
    "access": "r_access", "rectification": "r_rectify", "erasure": "r_erase",
    "restriction": "r_restrict", "portability": "r_port", "objection": "r_object",
}


def pp_01(ev: ScanEvidence, ctx: Ctx):
    """A privacy policy is reachable within two clicks of the homepage."""
    pc = ev.policy
    if pc is None:
        return result("PP-01", Outcome.UNABLE_TO_DETERMINE, "policy discovery was not run")
    pages = [p for p in pc.pages if p.is_privacy_policy]
    if pc.discovery_status == "found_linked":
        p = pages[0]
        how = "inside the Terms page" if p.embedded else " > ".join(p.click_path)
        return result("PP-01", Outcome.COMPLIANT, f"privacy policy reached by links: {how}",
                      [{"url": p.url, "click_path": p.click_path, "embedded": p.embedded}])
    if pc.discovery_status == "found_unlinked":
        return result("PP-01", Outcome.NON_COMPLIANT, "a policy exists but is not linked within two clicks (found by common address)",
                      [{"url": pages[0].url}])
    if pc.discovery_status == "exhaustive_negative":
        return result("PP-01", Outcome.NON_COMPLIANT, "no privacy policy found by links or common addresses")
    return result("PP-01", Outcome.UNABLE_TO_DETERMINE, "policy discovery was uncertain", [{"problems": pc.problems[:3]}])


def pp_02(ev: ScanEvidence, ctx: Ctx):
    """A cookie policy: a standalone page, a headed section in the privacy policy, or banner or panel text stating presence and purpose."""
    pc, d = ev.policy, collect(ev)
    if pc is not None:
        for p in pc.pages:
            if "cookie" in p.kinds and p.text_chars >= 200 and p.via == "link":
                return result("PP-02", Outcome.COMPLIANT, "a separate cookie policy page was found", [{"url": p.url}])
        for p in pc.pages:
            if p.is_privacy_policy and any("cookie" in h.lower() for h in p.headings):
                heading = next(h for h in p.headings if "cookie" in h.lower())
                return result("PP-02", Outcome.COMPLIANT, "the privacy policy has a cookie section", [{"url": p.url, "heading": heading}])
    for source, text in d.other:
        if source in ("banner", "panel"):
            for s in analyse(text):
                if {"cookie", "cookie_purpose"} <= s.labels:
                    return result("PP-02", Outcome.COMPLIANT, f"the {source} states that cookies are used and why",
                                  [{"source": source, "text": snippet(s.text)}])
    return no_match("PP-02", d, "no cookie policy, cookie section, or banner text stating what cookies are used for")


def _privacy_sentences(d):
    return [(src, s) for src, text in d.privacy for s in analyse(text)]


def pp_03(ev: ScanEvidence, ctx: Ctx):
    """A contact channel for privacy matters (register R12: a general contact form or address does not count)."""
    d = collect(ev)
    for source, text in d.privacy:
        for m in EMAIL_RE.finditer(text):
            near = PRIVACY_CUE_RE.search(text[max(0, m.start() - 250): m.end() + 250])
            local = m.group(0).split("@")[0]
            if near or PRIVACY_LOCAL_PART_RE.match(local):
                domain = m.group(0).split("@")[1]
                return result("PP-03", Outcome.COMPLIANT, "a privacy contact email is given",
                              [{"email_domain": domain, "matched_by": "privacy-named address" if PRIVACY_LOCAL_PART_RE.match(local) else "privacy wording nearby"}])
    return no_match("PP-03", d, "no email address linked to privacy or data protection matters was found in the policy")


def pp_04(ev: ScanEvidence, ctx: Ctx):
    """Purpose of collection (register R13): a sentence that names a data category and a specific use."""
    d = collect(ev)
    for _src, s in _privacy_sentences(d):
        if {"data_cat", "purpose_cue"} <= s.labels:
            return result("PP-04", Outcome.COMPLIANT, "the policy states a specific use for a named type of data",
                          [{"text": snippet(s.text)}])
    return no_match("PP-04", d, "no sentence names a type of data together with a specific use")


def pp_05(ev: ScanEvidence, ctx: Ctx):
    """Retention: a duration, or a clear end-trigger the data subject can act on."""
    d = collect(ev)
    vague = []
    for _src, s in _privacy_sentences(d):
        if "ret_cue" not in s.labels:
            continue
        if DURATION_RE.search(s.text) or TRIGGER_RE.search(s.text):
            return result("PP-05", Outcome.COMPLIANT, "the policy states how long data is kept",
                          [{"text": snippet(s.text)}])
        if VAGUE_RETENTION_RE.search(s.text):
            vague.append(snippet(s.text))
    ev_rows = [{"vague_only": vague[:2]}] if vague else None
    return no_match("PP-05", d, "no retention period or clear end-trigger" + (" (only 'as long as necessary')" if vague else ""), ev_rows)


def pp_06(ev: ScanEvidence, ctx: Ctx):
    """All seven core rights are disclosed, or each omission is explained (rulebook PP-06)."""
    d = collect(ev)
    if not d.privacy:
        return no_match("PP-06", d, "no data subject rights could be checked")
    status = {right: "missing" for right in [*RIGHTS, "complaint_to_NDPC"]}
    for _src, s in _privacy_sentences(d):
        for right, label in RIGHTS.items():
            if label not in s.labels or "data_word" not in s.labels:
                continue
            if "limit" in s.labels:  # 'the right to X does not apply when ...' explains an omission, it does not offer the right
                if status[right] == "missing":
                    status[right] = "explained"
            elif "cue_right" in s.labels:
                status[right] = "disclosed"
        if {"c_verb", "c_authority"} <= s.labels:
            status["complaint_to_NDPC"] = "disclosed"
    missing = [r for r, v in status.items() if v == "missing"]
    evidence = [{"rights": status}]
    if not missing:
        return result("PP-06", Outcome.COMPLIANT, "all seven core rights are disclosed or explained", evidence)
    note = f"{len(missing)} core right(s) not disclosed: {', '.join(missing)}"
    if missing == ["complaint_to_NDPC"]:
        note += " (only the right to complain to the NDPC is missing: partial-compliance sub-finding)"
    return result("PP-06", Outcome.NON_COMPLIANT, note, evidence, failed=len(missing), total=7)
