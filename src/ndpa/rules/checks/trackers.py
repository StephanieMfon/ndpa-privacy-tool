"""TR-02 (rulebook section C): every detected tracker is named by vendor or product in the disclosures (register R9)."""
from ndpa.models import Outcome
from ndpa.rules.context import Ctx, ScanEvidence, result, tracker_requests
from ndpa.rules.disclosures import collect, no_match
from ndpa.rules.text import mentions, vendor_names


def tr_02(ev: ScanEvidence, ctx: Ctx):
    vendors: dict[str, set[str]] = {}
    for run in ev.runs():
        for e in tracker_requests(run):
            vendors.setdefault(e.vendor or e.domain or "unknown", set()).add(e.domain or "")
    if not vendors:
        return result("TR-02", Outcome.NOT_APPLICABLE, "no trackers were detected")
    d = collect(ev)
    corpus = d.corpus_lower()
    rows = [{"vendor": v, "named": any(mentions(n, corpus) for n in vendor_names(v, domains)),
             "domains": sorted(domains)[:2]} for v, domains in sorted(vendors.items())]
    unnamed = [r for r in rows if not r["named"]]
    if not unnamed:
        return result("TR-02", Outcome.COMPLIANT, f"all {len(rows)} detected trackers are named", rows[:40],
                      failed=0, total=len(rows))
    return no_match("TR-02", d, f"{len(unnamed)} of {len(rows)} detected trackers are not named",
                    unnamed[:40], failed=len(unnamed), total=len(rows))
