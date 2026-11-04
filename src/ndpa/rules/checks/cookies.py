"""CK-01 and CK-02 (rulebook section A)."""
from ndpa.analyse.trackers import is_third_party, registrable_domain
from ndpa.models import Outcome
from ndpa.rules.context import Ctx, ScanEvidence, result
from ndpa.rules.disclosures import collect, no_match
from ndpa.rules.text import DURATION_RE, analyse, mentions, snippet, vendor_names

MAX_DAYS = 365  # register R3: a methodological threshold, not a statutory limit


def ck_01(ev: ScanEvidence, ctx: Ctx):
    """A persistent cookie lasts no longer than 12 months, or its lifetime is justified in the disclosures.

    Lifespan is measured from when the jar was read, so it can only be understated, never overstated.
    """
    persistent: dict[tuple[str, str], float] = {}
    start_missing = False
    for run in ev.runs():
        for c in run.cookies:
            expires = c.get("expires")
            if not expires or expires <= 0:
                continue  # session cookie
            if run.captured_at is None:
                start_missing = True
                continue
            key = (c["name"], c["domain"])
            persistent[key] = max(persistent.get(key, 0.0), (expires - run.captured_at) / 86400)
    if not persistent:
        if start_missing:
            return result("CK-01", Outcome.UNABLE_TO_DETERMINE, "the time the cookies were read was not recorded, so lifespans cannot be computed")
        return result("CK-01", Outcome.NOT_APPLICABLE, "no persistent cookies (only session cookies, or none)")
    too_long = {k: v for k, v in persistent.items() if v > MAX_DAYS}
    if not too_long:
        return result("CK-01", Outcome.COMPLIANT, f"no persistent cookie lasts longer than {MAX_DAYS} days",
                      failed=0, total=len(persistent))
    d = collect(ev)
    sentences = [s for _src, text in d.all() for s in analyse(text)]
    rows, unjustified = [], 0
    for (name, domain), days in sorted(too_long.items()):
        justified = any(mentions(name.lower(), s.text.lower()) and (DURATION_RE.search(s.text) or "ret_cue" in s.labels)
                        for s in sentences)
        unjustified += not justified
        rows.append({"cookie": name, "domain": domain, "lifespan_days": round(days), "justified": justified})
    if unjustified == 0:
        return result("CK-01", Outcome.COMPLIANT, "every long-lived cookie is justified in the disclosures", rows[:30],
                      failed=0, total=len(persistent))
    return no_match("CK-01", d, f"{unjustified} cookie(s) last longer than {MAX_DAYS} days with no justification",
                    rows[:30], failed=unjustified, total=len(persistent))


def ck_02(ev: ScanEvidence, ctx: Ctx):
    """Every third-party cookie's organisation is named in the disclosures (register R9: vendor or product name)."""
    owners: dict[str, dict] = {}
    for run in ev.runs():
        for c in run.cookies:
            host = c["domain"].lstrip(".")
            if not is_third_party(f"https://{host}/", ev.site_url):
                continue
            owner = (ctx.trackers.owner_of(host) if ctx.trackers else None) or registrable_domain(host)
            row = owners.setdefault(owner, {"cookies": set(), "domains": set()})
            row["cookies"].add(c["name"])
            row["domains"].add(registrable_domain(host))
    if not owners:
        return result("CK-02", Outcome.NOT_APPLICABLE, "no third-party cookies in any run")
    d = collect(ev)
    corpus = d.corpus_lower()
    rows = []
    for owner, info in sorted(owners.items()):
        named = any(mentions(n, corpus) for n in vendor_names(owner, info["domains"]))
        rows.append({"owner": owner, "named": named, "cookies": sorted(info["cookies"])[:5], "cookie_count": len(info["cookies"])})
    unnamed = [r for r in rows if not r["named"]]
    if not unnamed:
        return result("CK-02", Outcome.COMPLIANT, f"all {len(rows)} third-party cookie owners are named", rows[:40],
                      failed=0, total=len(rows))
    return no_match("CK-02", d, f"{len(unnamed)} of {len(rows)} third-party cookie owners are not named",
                    [r for r in rows if not r["named"]][:40], failed=len(unnamed), total=len(rows))
