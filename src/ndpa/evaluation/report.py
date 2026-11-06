"""Compare the tool with the annotators and produce the numbers for Chapter 4.

    python -m ndpa.evaluation.report --run eval-1 --annotator1 eval/annotations/annotator1.csv \
        [--annotator2 eval/annotations/annotator2.csv] [--adjudicated eval/annotations/adjudicated.csv]

Definitions (also printed in summary.md, so the report explains itself):
  - The positive class is NON-COMPLIANT: "the tool finds a violation".
  - TP: tool and gold both say non-compliant.  FP: the tool says non-compliant, gold says compliant or not applicable.
    FN: gold says non-compliant, the tool says compliant or not applicable.  TN: neither says non-compliant.
  - "Unable to determine" exists only in the tool. Those cases are reported as abstentions. Recall is shown without them
    (lenient) and with each abstention on a gold non-compliant case counted as a miss (strict).
  - Gold is annotator 1, overridden by the adjudicated sheet where one is given.
  - Blocked and failed scans have no outcomes, so they are left out of the comparison and counted in the block rate.
"""
import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ndpa.evaluation import metrics
from ndpa.evaluation.corpus import DEFAULT_DB, MANIFEST_DIR, Manifest, freeze_status
from ndpa.evaluation.labels import AnnotationError, Annotations, complete_sites, load_annotations, normalise_site
from ndpa.models import Outcome, RuleResult, ScanStatus
from ndpa.scoring.score import load_rulebook, score
from ndpa.storage import db

NC, C, NA, UTD = Outcome.NON_COMPLIANT, Outcome.COMPLIANT, Outcome.NOT_APPLICABLE, Outcome.UNABLE_TO_DETERMINE
ERROR_CATEGORIES = [
    "tool defect (the code is wrong)", "word-list gap (the policy wording was not recognised)", "capture gap (the browser missed something)",
    "annotator error", "rulebook ambiguity (the rule can be read two ways)", "site changed between the two looks", "other (explain in notes)"]


@dataclass
class ToolSite:
    url: str
    status: str  # done, blocked, failed, or not_scanned
    scan_id: int | None = None
    folder: str = ""
    outcomes: dict[str, tuple[Outcome, str]] = field(default_factory=dict)  # rule id -> (outcome, the tool's note)
    score_weighted: float | None = None
    score_equal: float | None = None
    band: str | None = None
    outside_window: bool = False


def scored_rules(rulebook: dict) -> list[dict]:
    return [{"id": r["id"], "name": r["name"], "category": r["category"], "tier": r["tier"], "weight": r["weight"]}
            for r in rulebook["rules"] if r.get("tier") != "unscored"]


def load_tool(conn, manifest: Manifest) -> dict[str, ToolSite]:
    """One ToolSite per planned site, read from the database the corpus run wrote to."""
    sites: dict[str, ToolSite] = {}
    for url in dict.fromkeys([*manifest.planned, *manifest.entries]):
        entry = manifest.entries.get(url)
        site = ToolSite(url=url, status="not_scanned")
        if entry:
            site.status, site.scan_id, site.outside_window = entry["status"], entry.get("scan_id"), bool(entry.get("outside_window"))
            scan = db.get_scan(conn, entry["scan_id"]) if entry.get("scan_id") else None
            if scan:
                site.status, site.folder = scan["status"], scan.get("folder") or ""
                if scan["status"] == "done":
                    for f in db.get_findings(conn, scan["id"]):
                        site.outcomes[f["rule_id"]] = (Outcome(f["outcome"]), f["note"] or "")
                    row = conn.execute("SELECT score_weighted, score_equal, band FROM score WHERE scan_id = ?", (scan["id"],)).fetchone()
                    if row:
                        site.score_weighted, site.score_equal, site.band = row["score_weighted"], row["score_equal"], row["band"]
        sites[normalise_site(url)] = site
    return sites


def merge_gold(first: Annotations, adjudicated: Annotations | None) -> dict[tuple[str, str], Outcome]:
    gold = {key: label.outcome for key, label in first.labels.items()}
    if adjudicated:
        gold.update({key: label.outcome for key, label in adjudicated.labels.items()})
    return gold


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def _interval(ci: tuple[float, float] | None, sign: bool = False) -> str:
    if ci is None:
        return ""
    return f"{100 * ci[0]:.0f}% to {100 * ci[1]:.0f}%" if sign else f"{100 * ci[0]:.0f} to {100 * ci[1]:.0f}"


CATEGORY_NAMES = {"cookies": "Cookies", "consent": "Consent banner", "trackers": "Trackers", "script_behaviour": "Scripts", "privacy_policy": "Privacy policy"}


def _counts(pairs: list[tuple[Outcome, Outcome]]) -> dict:
    """pairs are (gold, tool). Lenient: abstentions are left out of tp/fp/fn/tn and counted on their own."""
    c = {"n": len(pairs), "tp": 0, "fp": 0, "fn": 0, "tn": 0, "abstained": 0, "abstained_gold_nc": 0, "gold_nc": 0, "tool_nc": 0, "agree": 0, "determined": 0}
    for gold, tool in pairs:
        c["gold_nc"] += gold == NC
        if tool == UTD:
            c["abstained"] += 1
            c["abstained_gold_nc"] += gold == NC
            continue
        c["determined"] += 1
        c["tool_nc"] += tool == NC
        c["agree"] += gold == tool
        if tool == NC and gold == NC:
            c["tp"] += 1
        elif tool == NC:
            c["fp"] += 1
        elif gold == NC:
            c["fn"] += 1
        else:
            c["tn"] += 1
    return c


def _metrics(c: dict) -> dict:
    p, r, f1 = metrics.prf(c["tp"], c["fp"], c["fn"])
    return {**c, "precision": p, "p_ci": metrics.wilson(c["tp"], c["tp"] + c["fp"]), "recall": r, "r_ci": metrics.wilson(c["tp"], c["tp"] + c["fn"]),
            "f1": f1, "recall_strict": metrics.safe_div(c["tp"], c["tp"] + c["fn"] + c["abstained_gold_nc"]),
            "agreement": metrics.safe_div(c["agree"], c["determined"])}


def _sum(rows: list[dict]) -> dict:
    keys = ("n", "tp", "fp", "fn", "tn", "abstained", "abstained_gold_nc", "gold_nc", "tool_nc", "agree", "determined")
    return {k: sum(r[k] for r in rows) for k in keys}


def detection(tool: dict[str, ToolSite], gold: dict[tuple[str, str], Outcome], rules: list[dict]) -> dict:
    """Per rule, per category and overall precision, recall and F1 for 'the tool finds a violation'."""
    by_rule: dict[str, list[tuple[Outcome, Outcome]]] = defaultdict(list)
    sites_compared = set()
    for (site, rule), g in gold.items():
        t = tool.get(site)
        if t is None or t.status != "done" or rule not in t.outcomes:
            continue
        by_rule[rule].append((g, t.outcomes[rule][0]))
        sites_compared.add(site)
    rule_rows = []
    for r in rules:
        m = _metrics(_counts(by_rule.get(r["id"], [])))
        rule_rows.append({"rule_id": r["id"], "name": r["name"], "category": r["category"], "tier": r["tier"], **m})
    category_rows = []
    for category in dict.fromkeys(r["category"] for r in rules):
        members = [r for r in rule_rows if r["category"] == category]
        m = _metrics(_sum(members))
        f1s = [r["f1"] for r in members if r["f1"] is not None]
        category_rows.append({"category": category, "rules": len(members), "macro_f1": sum(f1s) / len(f1s) if f1s else None,
                              "macro_f1_rules": len(f1s), **m})
    overall = _metrics(_sum(rule_rows))
    f1s = [r["f1"] for r in rule_rows if r["f1"] is not None]
    overall["macro_f1"], overall["macro_f1_rules"] = (sum(f1s) / len(f1s) if f1s else None), len(f1s)
    determined = [(g, t) for pairs in by_rule.values() for g, t in pairs if t != UTD]
    overall["kappa_tool_vs_gold"] = metrics.cohen_kappa([g.value for g, _ in determined], [t.value for _, t in determined])
    overall["kappa_band"] = metrics.kappa_band(overall["kappa_tool_vs_gold"])
    return {"rules": rule_rows, "categories": category_rows, "overall": overall, "sites_compared": len(sites_compared)}


def inter_annotator(first: Annotations, second: Annotations | None, rules: list[dict]) -> dict | None:
    if second is None:
        return None
    shared = sorted(k for k in first.labels if k in second.labels)
    per_rule = []
    for r in rules:
        keys = [k for k in shared if k[1] == r["id"]]
        a = [first.labels[k].outcome.value for k in keys]
        b = [second.labels[k].outcome.value for k in keys]
        per_rule.append({"rule_id": r["id"], "n": len(keys), "agreement": metrics.safe_div(sum(x == y for x, y in zip(a, b, strict=True)), len(keys)),
                         "kappa": metrics.cohen_kappa(a, b)})
    a = [first.labels[k].outcome.value for k in shared]
    b = [second.labels[k].outcome.value for k in shared]
    kappa = metrics.cohen_kappa(a, b)
    disagreements = [{"site": s, "rule_id": r, "annotator1": first.labels[(s, r)].outcome.value, "annotator2": second.labels[(s, r)].outcome.value,
                      "annotator1_notes": first.labels[(s, r)].notes, "annotator2_notes": second.labels[(s, r)].notes,
                      "adjudicated_label": "", "adjudication_notes": ""} for s, r in shared if first.labels[(s, r)].outcome != second.labels[(s, r)].outcome]
    return {"sites": len({s for s, _ in shared}), "items": len(shared), "agreement": metrics.safe_div(sum(x == y for x, y in zip(a, b, strict=True)), len(shared)),
            "kappa": kappa, "kappa_band": metrics.kappa_band(kappa), "per_rule": per_rule, "disagreements": disagreements}


def score_comparison(tool: dict[str, ToolSite], gold: dict[tuple[str, str], Outcome], rulebook: dict, rules: list[dict]) -> dict:
    """Score every fully annotated site from the annotator's labels, with the same formula as the tool, and compare."""
    ids = [r["id"] for r in rules]
    rows = []
    for site, t in sorted(tool.items()):
        if t.status != "done" or not all((site, i) in gold for i in ids):
            continue
        card = score([RuleResult(rule_id=i, outcome=gold[(site, i)]) for i in ids], rulebook, ScanStatus.DONE)
        rows.append({"site": site, "gold_weighted": card.score_weighted, "gold_equal": card.score_equal, "gold_band": card.band,
                     "tool_weighted": t.score_weighted, "tool_equal": t.score_equal, "tool_band": t.band})
    both = [r for r in rows if r["gold_weighted"] is not None and r["tool_weighted"] is not None]
    both_equal = [r for r in rows if r["gold_equal"] is not None and r["tool_equal"] is not None]
    tool_both = [r for r in rows if r["tool_weighted"] is not None and r["tool_equal"] is not None]
    gw, tw = [r["gold_weighted"] for r in both], [r["tool_weighted"] for r in both]
    return {"rows": rows, "n": len(both),
            "spearman_weighted": metrics.spearman(gw, tw), "mean_abs_error": metrics.mean_abs_error(gw, tw),
            "band_agreement": metrics.safe_div(sum(r["gold_band"] == r["tool_band"] for r in both), len(both)),
            "spearman_equal": metrics.spearman([r["gold_equal"] for r in both_equal], [r["tool_equal"] for r in both_equal]),
            "sensitivity_spearman": metrics.spearman([r["tool_weighted"] for r in tool_both], [r["tool_equal"] for r in tool_both]),
            "sensitivity_n": len(tool_both)}


def block_rate(tool: dict[str, ToolSite]) -> dict:
    count = lambda s: sum(1 for t in tool.values() if t.status == s)  # noqa: E731
    done, blocked, failed, unscanned = count("done"), count("blocked"), count("failed"), count("not_scanned")
    reached = done + blocked
    return {"planned": len(tool), "done": done, "blocked": blocked, "failed": failed, "not_scanned": unscanned,
            "block_rate": metrics.safe_div(blocked, reached), "block_rate_ci": metrics.wilson(blocked, reached),
            "blocked_sites": sorted(t.url for t in tool.values() if t.status == "blocked"),
            "failed_sites": sorted(t.url for t in tool.values() if t.status == "failed")}


def error_rows(tool: dict[str, ToolSite], gold: dict[tuple[str, str], Outcome], rules: list[dict]) -> list[dict]:
    names = {r["id"]: r["name"] for r in rules}
    out = []
    for (site, rule), g in sorted(gold.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        t = tool.get(site)
        if t is None or t.status != "done" or rule not in t.outcomes or t.outcomes[rule][0] == g:
            continue
        out.append({"site": site, "rule_id": rule, "rule": names.get(rule, ""), "gold": g.value, "tool": t.outcomes[rule][0].value, "tool_note": t.outcomes[rule][1],
                    "scan_id": t.scan_id, "evidence_folder": t.folder, "error_category": "", "notes": ""})
    return out


def evaluate(tool: dict[str, ToolSite], first: Annotations, second: Annotations | None, adjudicated: Annotations | None, rulebook: dict, manifest: Manifest) -> dict:
    rules = scored_rules(rulebook)
    ids = [r["id"] for r in rules]
    gold = merge_gold(first, adjudicated)
    complete = complete_sites(first, ids)
    gold_sites = {s for s, _ in gold}
    detect = detection(tool, gold, rules)
    record, problems = freeze_status()
    unresolved = 0
    agreement = inter_annotator(first, second, rules)
    if agreement:
        adjudicated_keys = set(adjudicated.labels) if adjudicated else set()
        unresolved = sum(1 for d in agreement["disagreements"] if (d["site"], d["rule_id"]) not in adjudicated_keys)
    return {
        "run": {"name": manifest.name, "started_at": manifest.started_at, "vantage": manifest.vantage, "seed": manifest.seed,
                "window_hours": manifest.window_hours, "window_exceeded": manifest.window_exceeded,
                "sites_outside_window": sorted(t.url for t in tool.values() if t.outside_window),
                "rulebook_version": rulebook.get("meta", {}).get("version", "unknown"),
                "frozen_when_run": bool(manifest.freeze.get("files")), "frozen_now": bool(record) and not problems, "freeze_problems": problems,
                "freeze_record": manifest.freeze},
        "coverage": {"planned": len(tool), "scanned_done": sum(t.status == "done" for t in tool.values()),
                     "annotated_sites": len(gold_sites), "fully_annotated_sites": len(complete), "blank_rows": first.blank_rows,
                     "annotated_but_not_scanned": sorted(s for s in gold_sites if s not in tool or tool[s].status == "not_scanned"),
                     "annotated_but_blocked_or_failed": sorted(s for s in gold_sites if s in tool and tool[s].status in ("blocked", "failed")),
                     "scanned_but_not_annotated": sorted(s for s, t in tool.items() if t.status == "done" and s not in gold_sites),
                     "sites_compared": detect["sites_compared"], "items_compared": detect["overall"]["n"],
                     "adjudicated_items": len(adjudicated.labels) if adjudicated else 0, "unresolved_disagreements": unresolved},
        "block_rate": block_rate(tool), "detection": detect, "inter_annotator": agreement,
        "scores": score_comparison(tool, gold, rulebook, rules), "errors": error_rows(tool, gold, rules),
    }


# ---------- writing ----------
def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _rate_cells(m: dict) -> list:
    return [_pct(m["precision"]), _interval(m["p_ci"]), _pct(m["recall"]), _interval(m["r_ci"]), _pct(m["f1"]), _pct(m["recall_strict"])]


def summary_markdown(result: dict) -> str:
    run, cov, blk, det, ia, sc = result["run"], result["coverage"], result["block_rate"], result["detection"], result["inter_annotator"], result["scores"]
    o = det["overall"]
    out = [f"# Evaluation report: {run['name']}", ""]
    if not run["frozen_when_run"]:
        out += ["> **TRIAL RUN: the rulebook was not frozen when this corpus was scanned. These numbers must not be reported.**", ""]
    elif not run["frozen_now"]:
        out += ["> **WARNING: a frozen file has changed since the freeze: " + "; ".join(run["freeze_problems"]) + "**", ""]
    out += ["## 1. The run", "",
            f"- Scanned from: {run['vantage']}. Rulebook {run['rulebook_version']}. Started {run['started_at']}. Site order seed {run['seed']}.",
            f"- Time window: {run['window_hours']:g} hours; " + ("**exceeded**, " + str(len(run["sites_outside_window"])) + " site(s) were scanned outside it." if run["window_exceeded"] else "kept."),
            "", "## 2. Coverage", "",
            f"- {cov['planned']} sites planned, {cov['scanned_done']} scanned successfully, {cov['annotated_sites']} annotated ({cov['fully_annotated_sites']} completely, {cov['blank_rows']} rows still blank).",
            f"- Compared: {cov['sites_compared']} sites, {cov['items_compared']} site-rule items.",
            *( [f"- Annotated but blocked or failed (left out of the comparison): {', '.join(cov['annotated_but_blocked_or_failed'])}."] if cov["annotated_but_blocked_or_failed"] else []),
            *( [f"- Scanned but not annotated yet: {', '.join(cov['scanned_but_not_annotated'])}."] if cov["scanned_but_not_annotated"] else []),
            "", "## 3. Block rate", "",
            f"- {blk['blocked']} of {blk['done'] + blk['blocked']} sites that could be reached refused the automated visit ({_pct(blk['block_rate'])}, 95% interval {_interval(blk['block_rate_ci'], sign=True)}); {blk['failed']} failed for other reasons; {blk['not_scanned']} not scanned.",
            *( [f"- Blocked: {', '.join(blk['blocked_sites'])}."] if blk["blocked_sites"] else []),
            "", "## 4. How well the tool finds violations", "",
            "Positive class = non-compliant. Intervals are 95% Wilson intervals: with this few sites they are wide, so read them with the point values.", "",
            f"- **Overall (micro): precision {_pct(o['precision'])}, recall {_pct(o['recall'])}, F1 {_pct(o['f1'])}**; macro F1 over {o['macro_f1_rules']} rules: {_pct(o['macro_f1'])}.",
            f"- Tool versus gold agreement on the three labels (kappa): {o['kappa_tool_vs_gold'] if o['kappa_tool_vs_gold'] is None else round(o['kappa_tool_vs_gold'], 3)} ({o['kappa_band']}). Plain agreement {_pct(o['agreement'])} of {o['determined']} determined items.",
            f"- The tool abstained ('unable to determine') on {o['abstained']} item{'' if o['abstained'] == 1 else 's'}, {o['abstained_gold_nc']} of them gold non-compliant. Strict recall (those counted as misses): {_pct(o['recall_strict'])}.",
            "", "### By category", "",
            _table(["Category", "Items", "Precision", "95% interval (%)", "Recall", "95% interval (%)", "F1", "Strict recall", "Macro F1"],
                   [[CATEGORY_NAMES.get(c["category"], c["category"]), c["n"], *_rate_cells(c), _pct(c["macro_f1"])] for c in det["categories"]]),
            "", "### By rule", "",
            "n/a means the number is undefined, not zero: precision is undefined when the tool never said non-compliant, recall when the gold never did.", "",
            _table(["Rule", "Name", "Items", "Gold NC", "Tool NC", "TP", "FP", "FN", "Abstained", "Precision", "95% interval (%)", "Recall", "95% interval (%)", "F1", "Strict recall"],
                   [[r["rule_id"], r["name"], r["n"], r["gold_nc"], r["tool_nc"], r["tp"], r["fp"], r["fn"], r["abstained"], *_rate_cells(r)] for r in det["rules"]])]
    if ia:
        out += ["", "## 5. Agreement between the two annotators", "",
                f"- {ia['sites']} sites, {ia['items']} items: agreement {_pct(ia['agreement'])}, kappa {None if ia['kappa'] is None else round(ia['kappa'], 3)} ({ia['kappa_band']}).",
                f"- {len(ia['disagreements'])} disagreements, {cov['unresolved_disagreements']} not yet adjudicated (see disagreements.csv).", "",
                _table(["Rule", "Items", "Agreement", "Kappa"], [[r["rule_id"], r["n"], _pct(r["agreement"]), "n/a" if r["kappa"] is None else round(r["kappa"], 2)] for r in ia["per_rule"]])]
    out += ["", "## 6. Score: tool against annotators", "",
            f"- {sc['n']} sites with a score from both. Rank correlation (Spearman) between the annotators' score and the tool's score: {sc['spearman_weighted'] if sc['spearman_weighted'] is None else round(sc['spearman_weighted'], 3)}; mean absolute difference {None if sc['mean_abs_error'] is None else round(sc['mean_abs_error'], 1)} points; same risk band for {_pct(sc['band_agreement'])}.",
            f"- Equal-weight version: Spearman {sc['spearman_equal'] if sc['spearman_equal'] is None else round(sc['spearman_equal'], 3)}.",
            f"- Sensitivity: the tool's weighted and equal-weight scores put {sc['sensitivity_n']} sites in nearly the same order when Spearman is close to 1 (here {sc['sensitivity_spearman'] if sc['sensitivity_spearman'] is None else round(sc['sensitivity_spearman'], 3)}). Never tune the weights to improve this.",
            "", "## 7. Errors", "",
            f"- {len(result['errors'])} items where the tool and the gold label differ are listed in errors.csv. Fill in the error_category column for each, using one of:", *[f"  - {c}" for c in ERROR_CATEGORIES], ""]
    return "\n".join(out)


def write_outputs(result: dict, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    det = result["detection"]
    header = ["rule_id", "name", "category", "tier", "items", "gold_nc", "tool_nc", "tp", "fp", "fn", "tn", "abstained", "abstained_gold_nc", "precision", "precision_ci_low",
              "precision_ci_high", "recall", "recall_ci_low", "recall_ci_high", "f1", "recall_strict", "agreement"]

    def row(r: dict) -> list:
        pc, rc = r["p_ci"] or ("", ""), r["r_ci"] or ("", "")
        return [r.get("rule_id", r.get("category")), r.get("name", ""), r.get("category", ""), r.get("tier", ""), r["n"], r["gold_nc"], r["tool_nc"], r["tp"], r["fp"], r["fn"], r["tn"],
                r["abstained"], r["abstained_gold_nc"], r["precision"], pc[0], pc[1], r["recall"], rc[0], rc[1], r["f1"], r["recall_strict"], r["agreement"]]
    _write_csv(directory / "per_rule.csv", header, [row(r) for r in det["rules"]])
    _write_csv(directory / "per_category.csv", header, [row(r) for r in det["categories"]])
    _write_csv(directory / "scores.csv", ["site", "gold_weighted", "gold_equal", "gold_band", "tool_weighted", "tool_equal", "tool_band"],
               [[r[k] for k in ("site", "gold_weighted", "gold_equal", "gold_band", "tool_weighted", "tool_equal", "tool_band")] for r in result["scores"]["rows"]])
    blk = result["block_rate"]
    _write_csv(directory / "block_rate.csv", ["site", "status"], [[u, "blocked"] for u in blk["blocked_sites"]] + [[u, "failed"] for u in blk["failed_sites"]])
    keys = ["site", "rule_id", "rule", "gold", "tool", "tool_note", "scan_id", "evidence_folder", "error_category", "notes"]
    _write_csv(directory / "errors.csv", keys, [[e[k] for k in keys] for e in result["errors"]])
    written = ["per_rule.csv", "per_category.csv", "scores.csv", "block_rate.csv", "errors.csv"]
    if result["inter_annotator"]:
        dkeys = ["site", "rule_id", "annotator1", "annotator2", "annotator1_notes", "annotator2_notes", "adjudicated_label", "adjudication_notes"]
        _write_csv(directory / "disagreements.csv", dkeys, [[d[k] for k in dkeys] for d in result["inter_annotator"]["disagreements"]])
        written.append("disagreements.csv")
    (directory / "summary.md").write_text(summary_markdown(result), encoding="utf-8")
    (directory / "report.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return [directory / name for name in [*written, "summary.md", "report.json"]]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Compare the tool with the annotators and write the evaluation report.")
    ap.add_argument("--run", required=True, help="the name used with ndpa.evaluation.corpus")
    ap.add_argument("--annotator1", required=True)
    ap.add_argument("--annotator2")
    ap.add_argument("--adjudicated")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--manifest-dir", default=str(MANIFEST_DIR))
    ap.add_argument("--out", help="default: data/eval_reports/<run>")
    args = ap.parse_args(argv)
    manifest = Manifest.load(args.run, Path(args.manifest_dir))
    rulebook = load_rulebook()
    ids = [r["id"] for r in scored_rules(rulebook)]
    corpus_sites = {normalise_site(u) for u in [*manifest.planned, *manifest.entries]}
    try:
        first = load_annotations(args.annotator1, ids, corpus_sites)
        second = load_annotations(args.annotator2, ids, corpus_sites) if args.annotator2 else None
        adjudicated = load_annotations(args.adjudicated, ids, corpus_sites) if args.adjudicated else None
    except AnnotationError as problem:
        raise SystemExit(f"{problem}\n\nFix the label sheet and run the report again. Nothing was written.") from None
    conn = db.connect(Path(args.db))
    result = evaluate(load_tool(conn, manifest), first, second, adjudicated, rulebook, manifest)
    written = write_outputs(result, Path(args.out or f"data/eval_reports/{args.run}"))
    print(summary_markdown(result))
    print("\nWritten:\n  " + "\n  ".join(str(p) for p in written))


if __name__ == "__main__":
    main()
