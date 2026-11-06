"""The report, checked against a small world whose every number can be worked out on paper.

Three sites were scanned (a, b, c), d was blocked, e was never scanned. Tool outcomes, with every other rule compliant:
    a.ng: CN-02 NC  SB-03 NC  PP-06 C    CN-01 C
    b.ng: CN-02 NC  SB-03 C   PP-06 UTD  CN-01 NC
    c.ng: CN-02 C   SB-03 NC  PP-06 C    CN-01 C    PP-02 NC
Annotator 1 (the gold), every other rule compliant:
    a.ng: CN-02 NC  SB-03 NC  PP-06 C    CN-01 C
    b.ng: CN-02 C   SB-03 C   PP-06 NC   CN-01 NC
    c.ng: CN-02 NC  SB-03 NC  PP-06 C    CN-01 NA
By rule (positive class = non-compliant):
    CN-02: TP 1 (a)  FP 1 (b)  FN 1 (c)        -> precision 1/2, recall 1/2
    SB-03: TP 2 (a, c)  TN 1 (b)               -> precision 1, recall 1
    PP-06: the tool abstained on b, where the gold is NC -> precision and recall undefined, strict recall 0
    CN-01: TP 1 (b), c is gold NA against tool C -> precision 1, recall 1, agreement 2 of 3
    PP-02: FP 1 (c, tool NC against gold C), nothing missed -> precision 0, recall undefined, F1 0
Overall: TP 4, FP 2, FN 1 -> precision 4/6, recall 4/5, F1 8/11.
One abstention on a gold NC, so strict recall is 4/(4+1+1) = 4/6. Asymmetric on purpose, so swapping FP and FN is caught.
"""
import csv
import json

import pytest
import web_seed as ws

from ndpa.evaluation import report
from ndpa.evaluation.corpus import Manifest
from ndpa.evaluation.labels import load_annotations
from ndpa.scoring.score import load_rulebook
from ndpa.storage import db

RULEBOOK = load_rulebook()
IDS = [r["id"] for r in report.scored_rules(RULEBOOK)]
URLS = {k: f"https://{k}" for k in ("a.ng", "b.ng", "c.ng", "d.ng", "e.ng")}


def tool_results(**overrides):
    results = ws.default_results()
    for rule, outcome in overrides.items():
        results[rule.replace("_", "-")] = ws.finding(rule.replace("_", "-"), outcome, f"tool says {outcome.value}")
    return results


def sheet(tmp_path, name, rows):
    """rows: {site: {rule: label}} with every other rule Compliant."""
    path = tmp_path / name
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "rule_id", "label", "na_reason", "evidence_ref", "notes"])
        for site, overrides in rows.items():
            for rule in IDS:
                label = overrides.get(rule, "Compliant")
                w.writerow([f"https://{site}", rule, label, "no banner appeared" if label == "Not Applicable" else "", "", ""])
    return path


@pytest.fixture
def world(tmp_path):
    conn = db.connect(tmp_path / "eval.db")
    ids = {
        "a.ng": ws.seed_scan(conn, tmp_path / "ev", "a.ng", "2026-11-10T08:00:00+00:00", tool_results(CN_02=ws.N, SB_03=ws.N)),
        "b.ng": ws.seed_scan(conn, tmp_path / "ev", "b.ng", "2026-11-10T09:00:00+00:00", tool_results(CN_02=ws.N, PP_06=ws.U, CN_01=ws.N)),
        "c.ng": ws.seed_scan(conn, tmp_path / "ev", "c.ng", "2026-11-10T10:00:00+00:00", tool_results(SB_03=ws.N, PP_02=ws.N)),
        "d.ng": ws.seed_scan(conn, tmp_path / "ev", "d.ng", "2026-11-10T11:00:00+00:00", None, status="blocked"),
    }
    manifest = Manifest(name="t", started_at="2026-11-10T08:00:00+00:00", seed=1, vantage="test lab", planned=list(URLS.values()),
                        entries={URLS[k]: {"scan_id": v, "status": "blocked" if k == "d.ng" else "done", "started_at": "x", "error": None, "attempts": 1, "outside_window": False}
                                 for k, v in ids.items()})
    gold = sheet(tmp_path, "a1.csv", {"a.ng": {"CN-02": "Non-Compliant", "SB-03": "Non-Compliant"},
                                      "b.ng": {"PP-06": "Non-Compliant", "CN-01": "Non-Compliant"},
                                      "c.ng": {"CN-02": "Non-Compliant", "SB-03": "Non-Compliant", "CN-01": "Not Applicable"}, "d.ng": {}})
    sites = {report.normalise_site(u) for u in URLS.values()}
    return {"conn": conn, "manifest": manifest, "tool": report.load_tool(conn, manifest), "first": load_annotations(gold, IDS, sites), "tmp": tmp_path, "sites": sites}


def rule_row(result, rule_id):
    return next(r for r in result["detection"]["rules"] if r["rule_id"] == rule_id)


def run(world, second=None, adjudicated=None):
    return report.evaluate(world["tool"], world["first"], second, adjudicated, RULEBOOK, world["manifest"])


def test_the_tool_side_reads_statuses_outcomes_and_scores_from_the_database(world):
    tool = world["tool"]
    assert {k: t.status for k, t in tool.items()} == {"a.ng": "done", "b.ng": "done", "c.ng": "done", "d.ng": "blocked", "e.ng": "not_scanned"}
    assert tool["b.ng"].outcomes["PP-06"][0] == ws.U and tool["a.ng"].outcomes["CN-02"][1] == "tool says non_compliant"
    assert tool["a.ng"].score_weighted is not None and tool["d.ng"].outcomes == {} and tool["d.ng"].score_weighted is None


def test_precision_recall_and_f1_per_rule_match_the_hand_calculation(world):
    result = run(world)
    cn02 = rule_row(result, "CN-02")
    assert (cn02["tp"], cn02["fp"], cn02["fn"], cn02["tn"]) == (1, 1, 1, 0) and (cn02["precision"], cn02["recall"], cn02["f1"]) == (0.5, 0.5, 0.5)
    sb03 = rule_row(result, "SB-03")
    assert (sb03["tp"], sb03["fp"], sb03["fn"], sb03["tn"]) == (2, 0, 0, 1) and (sb03["precision"], sb03["recall"], sb03["f1"]) == (1.0, 1.0, 1.0)
    pp06 = rule_row(result, "PP-06")
    assert pp06["abstained"] == 1 and pp06["abstained_gold_nc"] == 1 and (pp06["precision"], pp06["recall"], pp06["f1"]) == (None, None, None) and pp06["recall_strict"] == 0.0
    cn01 = rule_row(result, "CN-01")
    assert (cn01["tp"], cn01["tn"]) == (1, 2) and cn01["precision"] == cn01["recall"] == 1.0 and round(cn01["agreement"], 3) == round(2 / 3, 3)
    pp02 = rule_row(result, "PP-02")
    assert (pp02["tp"], pp02["fp"], pp02["fn"], pp02["tn"]) == (0, 1, 0, 2) and (pp02["precision"], pp02["recall"], pp02["f1"]) == (0.0, None, 0.0)
    quiet = rule_row(result, "CK-01")  # nothing happened here: no violation by anyone
    assert quiet["tn"] == 3 and quiet["precision"] is None and quiet["recall"] is None


def test_overall_numbers_and_the_two_ways_of_treating_abstentions(world):
    o = run(world)["detection"]["overall"]
    assert (o["tp"], o["fp"], o["fn"], o["abstained"], o["n"]) == (4, 2, 1, 1, 51)
    assert round(o["precision"], 4) == round(4 / 6, 4) and o["recall"] == 0.8 and round(o["f1"], 4) == round(8 / 11, 4)
    assert round(o["recall_strict"], 4) == round(4 / 6, 4)  # the abstention on a real violation counts as a miss
    assert o["determined"] == 50 and o["agree"] == 46 and o["agreement"] == 0.92 and o["kappa_tool_vs_gold"] is not None
    assert o["p_ci"][0] < o["precision"] < o["p_ci"][1] and o["r_ci"][0] < o["recall"] < o["r_ci"][1]


def test_categories_add_up_to_the_rules(world):
    det = run(world)["detection"]
    for cat in det["categories"]:
        members = [r for r in det["rules"] if r["category"] == cat["category"]]
        assert cat["tp"] == sum(r["tp"] for r in members) and cat["n"] == sum(r["n"] for r in members) and cat["rules"] == len(members)
        defined = [r["f1"] for r in members if r["f1"] is not None]
        assert cat["macro_f1"] == (sum(defined) / len(defined) if defined else None)
    assert sum(c["tp"] for c in det["categories"]) == det["overall"]["tp"] == 4


def test_coverage_blocked_and_unscanned_sites_are_left_out_and_explained(world):
    result = run(world)
    cov, blk = result["coverage"], result["block_rate"]
    assert (cov["planned"], cov["scanned_done"], cov["annotated_sites"], cov["fully_annotated_sites"]) == (5, 3, 4, 4)
    assert cov["sites_compared"] == 3 and cov["items_compared"] == 51 and cov["annotated_but_blocked_or_failed"] == ["d.ng"]
    assert cov["scanned_but_not_annotated"] == [] and cov["blank_rows"] == 0
    assert (blk["done"], blk["blocked"], blk["failed"], blk["not_scanned"]) == (3, 1, 0, 1)
    assert blk["block_rate"] == 0.25 and blk["blocked_sites"] == ["https://d.ng"] and blk["block_rate_ci"][0] < 0.25 < blk["block_rate_ci"][1]


def test_every_disagreement_becomes_a_row_for_error_analysis(world):
    errors = run(world)["errors"]
    assert [(e["rule_id"], e["site"], e["gold"], e["tool"]) for e in errors] == [
        ("CN-01", "c.ng", "not_applicable", "compliant"), ("CN-02", "b.ng", "compliant", "non_compliant"),
        ("CN-02", "c.ng", "non_compliant", "compliant"), ("PP-02", "c.ng", "compliant", "non_compliant"), ("PP-06", "b.ng", "non_compliant", "unable_to_determine")]
    assert errors[1]["tool_note"] == "tool says non_compliant" and errors[1]["scan_id"] and errors[1]["error_category"] == ""


def test_the_annotators_score_uses_the_same_formula_as_the_tool(world):
    sc = run(world)["scores"]
    rows = {r["site"]: r for r in sc["rows"]}
    assert set(rows) == {"a.ng", "b.ng", "c.ng"}  # d.ng was blocked
    assert rows["a.ng"]["gold_weighted"] == rows["a.ng"]["tool_weighted"] and rows["a.ng"]["gold_band"] == rows["a.ng"]["tool_band"]  # identical labels, identical score
    assert rows["b.ng"]["gold_weighted"] != rows["b.ng"]["tool_weighted"]
    assert sc["n"] == 3 and 0 <= sc["band_agreement"] <= 1 and sc["mean_abs_error"] > 0 and sc["sensitivity_n"] == 3


def test_a_site_with_unfinished_annotation_gets_no_gold_score(tmp_path, world):
    sites = world["sites"]
    partial = tmp_path / "p.csv"
    partial.write_text("site,rule_id,label,na_reason,evidence_ref,notes\nhttps://a.ng,CN-02,Non-Compliant,,,\nhttps://a.ng,SB-03,Non-Compliant,,,\nhttps://a.ng,CK-01,,,,\n")
    result = report.evaluate(world["tool"], load_annotations(partial, IDS, sites), None, None, RULEBOOK, world["manifest"])
    assert result["scores"]["rows"] == [] and result["coverage"]["fully_annotated_sites"] == 0 and result["coverage"]["blank_rows"] == 1
    assert result["detection"]["overall"]["n"] == 2  # but the two labelled items are still compared


def second_sheet(world):
    return load_annotations(sheet(world["tmp"], "a2.csv", {"a.ng": {"CN-02": "Non-Compliant", "SB-03": "Non-Compliant"},
                                                           "b.ng": {"CN-02": "Non-Compliant", "CN-01": "Non-Compliant"}}), IDS, world["sites"])


def test_agreement_between_the_two_annotators(world):
    ia = run(world, second=second_sheet(world))["inter_annotator"]
    assert ia["sites"] == 2 and ia["items"] == 34 and round(ia["agreement"], 3) == round(32 / 34, 3)
    assert round(ia["kappa"], 3) == 0.717 and ia["kappa_band"] == "substantial"  # (32/34 - 916/1156) / (1 - 916/1156)
    assert [(d["site"], d["rule_id"], d["annotator1"], d["annotator2"]) for d in ia["disagreements"]] == [
        ("b.ng", "CN-02", "compliant", "non_compliant"), ("b.ng", "PP-06", "non_compliant", "compliant")]
    assert run(world)["inter_annotator"] is None  # no second annotator, no agreement section


def test_an_adjudicated_label_replaces_the_first_annotators(world):
    adjudicated = load_annotations(_write(world["tmp"] / "adj.csv", "https://b.ng,CN-02,Non-Compliant"), IDS, world["sites"])
    result = run(world, second=second_sheet(world), adjudicated=adjudicated)
    cn02 = rule_row(result, "CN-02")
    assert (cn02["tp"], cn02["fp"], cn02["fn"]) == (2, 0, 1) and cn02["precision"] == 1.0 and round(cn02["recall"], 3) == 0.667  # b.ng is now a hit, not a false alarm
    assert result["coverage"]["adjudicated_items"] == 1 and result["coverage"]["unresolved_disagreements"] == 1  # the PP-06 disagreement is still open
    assert ("b.ng", "CN-02") not in {(e["site"], e["rule_id"]) for e in result["errors"]}


def _write(path, row):
    path.write_text("site,rule_id,label,na_reason,evidence_ref,notes\n" + row + ",,,\n")
    return path


def test_the_files_are_written_and_the_summary_explains_itself(world):
    result = run(world, second=second_sheet(world))
    out = world["tmp"] / "out"
    written = report.write_outputs(result, out)
    assert {p.name for p in written} == {"per_rule.csv", "per_category.csv", "scores.csv", "block_rate.csv", "errors.csv", "disagreements.csv", "summary.md", "report.json"}
    text = (out / "summary.md").read_text()
    assert "TRIAL RUN" in text  # this corpus was scanned with no freeze record
    assert "1 of 4 sites that could be reached refused" in text and "Positive class = non-compliant" in text and "Wilson" in text and "error_category" in text
    assert "| CN-02 |" in text and "n/a" in text  # an undefined number is shown as n/a, never as 0
    rows = list(csv.DictReader(open(out / "per_rule.csv")))
    assert next(r for r in rows if r["rule_id"] == "PP-06")["precision"] == "" and next(r for r in rows if r["rule_id"] == "SB-03")["recall"] == "1.0"
    assert len(list(csv.DictReader(open(out / "errors.csv")))) == 5 and json.loads((out / "report.json").read_text())["block_rate"]["blocked"] == 1


def test_a_frozen_run_is_not_marked_as_a_trial(world):
    world["manifest"].freeze = {"rulebook_version": "2.0.0", "files": {"rulebook/rules.v2.yaml": {"sha256": "x", "bytes": 1}}}
    text = report.summary_markdown(run(world))
    assert "TRIAL RUN" not in text  # (a changed frozen file is reported separately, with a WARNING)


def test_the_command_line_writes_a_report_and_explains_a_bad_sheet(world, capsys):
    tmp = world["tmp"]
    world["manifest"].save(tmp / "runs")
    args = ["--run", "t", "--annotator1", str(tmp / "a1.csv"), "--db", str(tmp / "eval.db"), "--manifest-dir", str(tmp / "runs"), "--out", str(tmp / "rep")]
    report.main(args)
    assert (tmp / "rep" / "summary.md").exists() and "Evaluation report: t" in capsys.readouterr().out
    bad = tmp / "bad.csv"
    bad.write_text("site,rule_id,label,na_reason,evidence_ref,notes\nhttps://a.ng,CN-02,Perhaps,,,\nhttps://zzz.ng,CN-02,Compliant,,,\n")
    with pytest.raises(SystemExit) as stop:
        report.main(["--run", "t", "--annotator1", str(bad), "--db", str(tmp / "eval.db"), "--manifest-dir", str(tmp / "runs"), "--out", str(tmp / "never")])
    assert "'Perhaps' is not a label" in str(stop.value) and "not in the corpus" in str(stop.value) and not (tmp / "never").exists()
