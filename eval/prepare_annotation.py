"""Build annotator sheets from the blocklist snapshot, rulebook and site list.
Run from the repo root: python eval/prepare_annotation.py"""
import collections
import csv
import json
import pathlib

import yaml

out = pathlib.Path("eval/templates")
out.mkdir(parents=True, exist_ok=True)

# 1. Tracker lookup from the frozen blocklist snapshot
tds = json.load(open("data/lists/tds-snapshot.json"))
rows = []
for domain, t in sorted(tds["trackers"].items()):
    owner = t.get("owner") or {}
    rows.append([
        domain,
        owner.get("displayName") or owner.get("name", ""),
        "; ".join(t.get("categories") or []) or "no-category",
        t.get("default", ""),
        t.get("fingerprinting", ""),
        t.get("prevalence", ""),
        "yes" if t.get("rules") else "no",
    ])
with open(out / "tracker_lookup.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["domain", "owner", "categories", "default", "fingerprinting", "prevalence", "has_url_rules"])
    w.writerows(rows)

# 2. Label sheet: one row per site per scored rule
sites = [line.strip() for line in open("my_site_list.txt") if line.strip() and not line.lstrip().startswith("#")]
rules = [r["id"] for r in yaml.safe_load(open("rulebook/rules.v2.yaml"))["rules"] if r["tier"] != "unscored"]
with open(out / "annotation_template.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["site", "rule_id", "label", "na_reason", "evidence_ref", "notes"])
    for s in sites:
        for r in rules:
            w.writerow([s, r, "", "", "", ""])

# 3. One row per site for capture details
with open(out / "site_context_template.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["site", "capture_date", "chrome_version", "banner_position",
                "covers_1_of_9_cells", "bottom_row_only", "reject_available",
                "accept_available", "close_only_case", "tr01_trackers_found",
                "policy_url", "policy_discovery"])
    for s in sites:
        w.writerow([s] + [""] * 11)

print(len(rows), "trackers loaded")
print("default field counts:", dict(collections.Counter(r[3] for r in rows)))
print(len(sites), "sites x", len(rules), "rules =", len(sites) * len(rules), "label rows")
