"""The 'fix first' list: every failed rule with its fix and the clause it satisfies, most serious first."""
from ndpa.models import Outcome, RuleResult

TIER_ORDER = {"critical": 0, "major": 1, "minor": 2}


def fix_first(results: list[RuleResult], rulebook: dict) -> list[dict]:
    rules = {r["id"]: r for r in rulebook["rules"]}
    rows = []
    for r in results:
        if r.outcome != Outcome.NON_COMPLIANT or r.rule_id not in rules:
            continue
        rule = rules[r.rule_id]
        rows.append({"rule_id": r.rule_id, "name": rule["name"], "tier": rule["tier"],
                     "affected": r.instances_failed, "fix": rule["remediation"]["fix"],
                     "clause": rule["remediation"]["clause"], "root_cause": r.root_cause})
    rows.sort(key=lambda row: (TIER_ORDER[row["tier"]], -row["affected"], row["rule_id"]))
    return rows
