"""The evaluation end to end: scan two local pages with a real browser, then compare with a perfect and an imperfect annotator."""
import csv

import pytest

from ndpa.capture.run import BrowserConfig
from ndpa.evaluation import corpus, report
from ndpa.evaluation.labels import load_annotations, normalise_site
from ndpa.scan import ScanOptions, run_scan
from ndpa.scoring.score import load_rulebook
from ndpa.storage import db

pytestmark = pytest.mark.browser


def write_sheet(path, site, outcomes):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["site", "rule_id", "label", "na_reason", "evidence_ref", "notes"])
        for rule, label in outcomes.items():
            w.writerow([site, rule, label, "no trigger" if label == "Not Applicable" else "", "", ""])


def test_a_corpus_run_and_its_report(site, tmp_path):
    options = ScanOptions(observe_s=1, browser=BrowserConfig(channel=None, headless=True), vantage="test lab", retry_pause_s=0)
    db_path = tmp_path / "eval.db"

    def scanner(url):
        return run_scan(url, db_path, tmp_path / "evidence", options, say_out=lambda *_: None)

    reachable = f"{site}/banner_fake_reject.html"
    refused = site.replace("127.0.0.1", "localhost") + "/blocked.html"  # another name for the same machine, so it is a different site
    manifest = corpus.run_corpus([reachable, refused], "t", scanner, "test lab", pause_s=0, manifest_dir=tmp_path / "runs",
                                 freeze_file=tmp_path / "no-freeze.json", allow_unfrozen=True, say=lambda *a: None, sleep=lambda s: None)
    assert {u: e["status"] for u, e in manifest.entries.items()} == {reachable: "done", refused: "blocked"}

    conn = db.connect(db_path)
    tool = report.load_tool(conn, manifest)
    rulebook = load_rulebook()
    ids = [r["id"] for r in report.scored_rules(rulebook)]
    key = normalise_site(reachable)
    found = {rule: outcome.value for rule, (outcome, _note) in tool[key].outcomes.items()}
    assert found["CN-02"] == "non_compliant"  # the fake Reject still sets a cookie
    label = {"compliant": "Compliant", "non_compliant": "Non-Compliant", "not_applicable": "Not Applicable", "unable_to_determine": "Compliant"}

    perfect = tmp_path / "perfect.csv"
    write_sheet(perfect, reachable, {rule: label[found[rule]] for rule in ids})  # an annotator who agrees with the tool on everything
    sites = {normalise_site(u) for u in manifest.planned}
    result = report.evaluate(tool, load_annotations(perfect, ids, sites), None, None, rulebook, manifest)
    overall = result["detection"]["overall"]
    assert overall["fp"] == 0 and overall["fn"] == 0 and overall["tp"] >= 1 and overall["f1"] == 1.0
    assert result["errors"] == [] and result["scores"]["rows"][0]["gold_weighted"] == result["scores"]["rows"][0]["tool_weighted"]
    blk = result["block_rate"]
    assert (blk["done"], blk["blocked"], blk["block_rate"]) == (1, 1, 0.5) and blk["blocked_sites"] == [refused]

    flawed = tmp_path / "flawed.csv"  # an annotator who thinks the fake Reject was honest
    write_sheet(flawed, reachable, {rule: ("Compliant" if rule == "CN-02" else label[found[rule]]) for rule in ids})
    result = report.evaluate(tool, load_annotations(flawed, ids, sites), None, None, rulebook, manifest)
    assert result["detection"]["overall"]["fp"] == 1 and [e["rule_id"] for e in result["errors"]] == ["CN-02"]
    assert result["errors"][0]["evidence_folder"].startswith(str(tmp_path / "evidence"))  # the error sheet points at the evidence

    written = report.write_outputs(result, tmp_path / "report")
    assert (tmp_path / "report" / "summary.md").exists() and len(written) == 7
