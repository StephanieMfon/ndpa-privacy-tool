"""Runs the rule checks on one scan. Rules still to come: CK-01, CK-02, TR-02, PP-01 to PP-06.

Usage:
    python -m ndpa.rules.engine data/evidence/<host>/<timestamp> [--policy data/evidence/<host>/<timestamp>/policy]
"""
import argparse
from pathlib import Path

from ndpa.models import Condition, PolicyCapture, RuleResult, RunResult, RunStatus
from ndpa.rules.checks import consent, script
from ndpa.rules.context import NecessaryCookies, ScanEvidence, build_ctx

CHECKS = {
    "CN-01": consent.cn_01, "CN-02": consent.cn_02, "CN-03": consent.cn_03,
    "CN-04": consent.cn_04, "CN-05": consent.cn_05,
    "SB-01": script.sb_01, "SB-02": script.sb_02, "SB-03": script.sb_03,
}


def evaluate(ev: ScanEvidence, necessary: NecessaryCookies | None = None) -> list[RuleResult]:
    """Outcomes for every implemented rule. A scan that was blocked or failed gets no outcomes (decision D-35)."""
    if ev.no_action.status != RunStatus.OK:
        return []
    necessary = necessary or NecessaryCookies.load()
    ctx = build_ctx(ev, necessary)
    return [check(ev, ctx) for check in CHECKS.values()]


def load_scan(scan_dir: Path, policy_dir: Path | None = None) -> ScanEvidence:
    scan_dir = Path(scan_dir)

    def load(condition: Condition) -> RunResult | None:
        path = scan_dir / condition.value / "run.json"
        return RunResult.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    no_action = load(Condition.NO_ACTION)
    if no_action is None:
        raise SystemExit(f"No no_action/run.json in {scan_dir}")
    policy = None
    policy_file = Path(policy_dir or scan_dir / "policy") / "policy.json"
    if policy_file.exists():
        policy = PolicyCapture.model_validate_json(policy_file.read_text(encoding="utf-8"))
    return ScanEvidence(no_action.url, no_action, load(Condition.ACCEPT), load(Condition.REJECT), policy)


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate the capture-based rules for one scan folder.")
    ap.add_argument("scan_dir")
    ap.add_argument("--policy", default=None)
    args = ap.parse_args()
    ev = load_scan(Path(args.scan_dir), Path(args.policy) if args.policy else None)
    necessary = NecessaryCookies.load()
    ctx = build_ctx(ev, necessary)
    print(f"site: {ev.site_url}")
    print(f"consent trigger: {ctx.trigger} {ctx.trigger_reasons}; banner or panel seen: {ctx.mechanism}")
    results = evaluate(ev, necessary)
    if not results:
        print(f"no outcomes: the scan status is {ev.no_action.status.value}")
    for r in results:
        root = f" [root cause {r.root_cause}]" if r.root_cause else ""
        print(f"{r.rule_id}  {r.outcome.value:<20} {r.note}{root}")


if __name__ == "__main__":
    main()
