"""Runs the 17 rule checks on one scan, scores it and lists what to fix first.

Usage:
    python -m ndpa.rules.engine data/evidence/<host>/<timestamp> [--policy data/evidence/<host>/<timestamp>/policy]
"""
import argparse
from pathlib import Path

from ndpa.analyse.trackers import SNAPSHOT, TrackerList
from ndpa.models import Condition, PolicyCapture, RuleResult, RunResult, RunStatus
from ndpa.remediation.fixes import fix_first
from ndpa.rules.checks import consent, cookies, policy, script, trackers
from ndpa.rules.context import NecessaryCookies, ScanEvidence, build_ctx
from ndpa.scoring.score import load_rulebook, scan_status, score

CHECKS = {  # in rulebook order; TR-01 is detection only and has no outcome
    "CK-01": cookies.ck_01, "CK-02": cookies.ck_02,
    "CN-01": consent.cn_01, "CN-02": consent.cn_02, "CN-03": consent.cn_03,
    "CN-04": consent.cn_04, "CN-05": consent.cn_05,
    "TR-02": trackers.tr_02,
    "SB-01": script.sb_01, "SB-02": script.sb_02, "SB-03": script.sb_03,
    "PP-01": policy.pp_01, "PP-02": policy.pp_02, "PP-03": policy.pp_03,
    "PP-04": policy.pp_04, "PP-05": policy.pp_05, "PP-06": policy.pp_06,
}


def evaluate(ev: ScanEvidence, necessary: NecessaryCookies | None = None,
             tracker_list: TrackerList | None = None) -> list[RuleResult]:
    """Outcomes for every implemented rule. A scan that was blocked or failed gets no outcomes (decision D-35)."""
    if ev.no_action.status != RunStatus.OK:
        return []
    necessary = necessary or NecessaryCookies.load()
    ctx = build_ctx(ev, necessary, tracker_list)
    return [check(ev, ctx) for check in CHECKS.values()]


def load_scan(scan_dir: Path, policy_dir: Path | None = None) -> ScanEvidence:
    scan_dir = Path(scan_dir)

    def load(condition: Condition) -> RunResult | None:
        path = scan_dir / condition.value / "run.json"
        return RunResult.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    no_action = load(Condition.NO_ACTION)
    if no_action is None:
        raise SystemExit(f"No no_action/run.json in {scan_dir}")
    policy, texts = None, {}
    folder = Path(policy_dir or scan_dir / "policy")
    if (folder / "policy.json").exists():
        policy = PolicyCapture.model_validate_json((folder / "policy.json").read_text(encoding="utf-8"))
        for page in policy.pages:
            file = folder / (page.text_file or "")
            if page.text_file and file.exists():
                texts[page.text_file] = file.read_text(encoding="utf-8")
    return ScanEvidence(no_action.url, no_action, load(Condition.ACCEPT), load(Condition.REJECT), policy, texts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate the capture-based rules for one scan folder.")
    ap.add_argument("scan_dir")
    ap.add_argument("--policy", default=None)
    ap.add_argument("--evidence", action="store_true", help="also print the first evidence rows of each failed rule")
    args = ap.parse_args()
    ev = load_scan(Path(args.scan_dir), Path(args.policy) if args.policy else None)
    necessary = NecessaryCookies.load()
    tracker_list = TrackerList() if SNAPSHOT.exists() else None
    ctx = build_ctx(ev, necessary, tracker_list)
    rulebook = load_rulebook()
    print(f"site: {ev.site_url}")
    print(f"consent trigger: {ctx.trigger} {ctx.trigger_reasons}; banner or panel seen: {ctx.mechanism}")
    results = evaluate(ev, necessary, tracker_list)
    if not results:
        print(f"no outcomes: the scan status is {ev.no_action.status.value}")
    for r in results:
        root = f" [root cause {r.root_cause}]" if r.root_cause else ""
        print(f"{r.rule_id}  {r.outcome.value:<20} {r.note}{root}")
        if args.evidence and r.outcome.value == "non_compliant":
            for row in r.evidence[:5]:
                print(f"        evidence: {row}")
    card = score(results, rulebook, scan_status(ev.no_action.status))
    print()
    if card.score_weighted is None:
        print(f"score: none. {card.note}")
    else:
        print(f"score: {card.score_weighted} (equal-weight {card.score_equal}), risk band: {card.band}, "
              f"critical failures: {card.critical_count}, coverage: {card.coverage:.0%}")
    if card.status.value == "done":
        print(f"categories: {card.category_scores}  (nothing to assess: {card.empty_categories})")
        fixes = fix_first(results, rulebook)
        print("fix first:")
        for f in fixes[:6]:
            print(f"  [{f['tier']}] {f['rule_id']} {f['name']}: {f['fix']}")
        if len(fixes) > 6:
            print(f"  ... and {len(fixes) - 6} more")


if __name__ == "__main__":
    main()
