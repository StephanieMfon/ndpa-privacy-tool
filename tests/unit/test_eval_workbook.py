import json

import pytest
from openpyxl import load_workbook

from ndpa.evaluation import labels, workbook
from ndpa.evaluation.corpus import read_sites
from ndpa.evaluation.labels import AnnotationError, load_annotations, normalise_site
from ndpa.models import Outcome
from ndpa.scoring.score import load_rulebook

RULEBOOK = load_rulebook()
IDS = [r["id"] for r in RULEBOOK["rules"] if r.get("tier") != "unscored"]
SITES = ["https://oxymon.co", "https://mtn.ng", "https://punchng.com"]


def make(tmp_path, sites=SITES, kind="main1"):
    path = tmp_path / "w.xlsx"
    workbook.build_workbook(sites, kind, RULEBOOK, workbook.Path("rulebook/necessary_cookies.yaml"), workbook.Path("data/lists/tds-snapshot.json")).save(path)
    return path


def fill(path, edits):
    """edits: {(site, rule): (label, na_reason)}. Stands in for an annotator typing into the Labels sheet."""
    book = load_workbook(path)
    sheet = book["Labels"]
    for row in sheet.iter_rows(min_row=2):
        key = (row[0].value, row[1].value)
        if key in edits:
            row[3].value, row[4].value = edits[key]
    book.save(path)


def test_the_second_annotators_share_is_spread_across_sectors_and_repeatable():
    sites = read_sites(workbook.Path("my_site_list.txt"))
    share = workbook.second_annotator_sites(sites)
    assert len(share) == 10 and set(share) <= set(sites) and share == [s for s in sites if s in share]  # a subset, in the original order
    by_sector = {}
    for s in share:
        by_sector.setdefault(workbook.sector_of(s), []).append(s)
    assert {k: len(v) for k, v in by_sector.items()} == workbook.QUOTAS
    assert share == workbook.second_annotator_sites(sites) and any(workbook.second_annotator_sites(sites, seed) != share for seed in range(1, 10))
    assert all(workbook.sector_of(s) != "Other" for s in sites)  # every corpus site has a sector


def test_the_workbook_has_every_sheet_and_one_row_per_site_and_rule(tmp_path):
    book = load_workbook(make(tmp_path))
    assert book.sheetnames == ["Read me first", "Labels", "Site context", "Rules guide", "Registers", "Necessary cookies", "Tracker lookup", "Codes explained"]
    sheet = book["Labels"]
    header = [c.value for c in sheet[1]]
    assert header == ["site", "rule_id", "rule", "label", "na_reason", "evidence_ref", "notes"]
    rows = [[c.value for c in r] for r in sheet.iter_rows(min_row=2)]
    assert len(rows) == 3 * 17 and [r[1] for r in rows[:17]] == IDS and {r[0] for r in rows} == set(SITES)
    assert all(r[3] is None and r[4] is None for r in rows)  # nothing is pre-filled
    assert len(sheet.data_validations.dataValidation) == 1 and workbook.LABEL_CHOICES[2] in sheet.data_validations.dataValidation[0].formula1
    assert sum(len(cf.rules) for cf in sheet.conditional_formatting) == 4  # three label colours and the 'reason missing' warning


def test_the_guides_come_from_the_rulebook_in_plain_words(tmp_path):
    book = load_workbook(make(tmp_path))
    guide = [[c.value for c in r] for r in book["Rules guide"].iter_rows(min_row=2)]
    assert [g[0] for g in guide] == [r["id"] for r in RULEBOOK["rules"]] and len(guide) == 18  # 17 labelled rules and TR-01
    text = " ".join(str(c) for g in guide for c in g if c)
    assert "max_days" not in text and "non_compliant" not in text and "unable_to_determine" not in text
    assert "12 months (365 days" in next(g for g in guide if g[0] == "CK-01")[4]
    assert next(g for g in guide if g[0] == "CN-02")[3].startswith("Critical:") and next(g for g in guide if g[0] == "TR-01")[3].startswith("Not labelled")
    registers = [[c.value for c in r] for r in book["Registers"].iter_rows(min_row=2)]
    assert [r[0] for r in registers] == [f"R{i}" for i in range(1, 14)] and all(r[2] and r[3] and r[2] != r[3] for r in registers)
    assert "rulebook section 0.2" in registers[0][1] and "3 by 3" in registers[3][2]
    codes = [c[0] for c in workbook.CODES]
    assert len(codes) == len(set(codes)) and "Root cause PP-01" in codes


def test_the_frozen_lists_are_in_the_workbook(tmp_path):
    book = load_workbook(make(tmp_path))
    cookies = {r[2].value for r in book["Necessary cookies"].iter_rows(min_row=2) if r[0].value}
    assert "FCCDCF" in cookies and "OptanonConsent" in cookies and "FCNEC" not in cookies
    trackers = [r[0].value for r in book["Tracker lookup"].iter_rows(min_row=2)]
    assert len(trackers) == len(json.loads(workbook.Path("data/lists/tds-snapshot.json").read_text())["trackers"]) and trackers == sorted(trackers)


def test_the_instructions_cover_the_cases_annotators_get_wrong(tmp_path):
    text = " ".join(r[0].value for r in load_workbook(make(tmp_path))["Read me first"].iter_rows() if r[0].value)
    for needed in ("Work blind", "Work alone", "R6", "R7", "72-hour window", "Implied: Compliant", "root cause: PP-01", "no consent trigger", "no cookies",
                   "There is no 'unable to determine' label", "Not Applicable always needs", "na_reason"):
        assert needed in text or needed.replace("Not Applicable always needs", "required whenever you choose Not Applicable") in text, needed
    assert "3 sites x 17 rules = 51 labels" in text
    assert "THIS IS THE PILOT" in " ".join(r[0].value for r in load_workbook(make(tmp_path, kind="pilot1"))["Read me first"].iter_rows() if r[0].value)


def test_site_context_counts_how_many_rules_are_labelled(tmp_path):
    book = load_workbook(make(tmp_path))
    sheet = book["Site context"]
    assert [r[0].value for r in sheet.iter_rows(min_row=2)] == SITES and sheet["N2"].value.startswith("=COUNTIFS(Labels!")
    assert sheet.data_validations.dataValidation  # banner position and yes/no dropdowns


def test_a_finished_workbook_is_read_back_directly(tmp_path):
    path = make(tmp_path)
    ann = load_annotations(path, IDS, {normalise_site(s) for s in SITES})
    assert ann.labels == {} and ann.blank_rows == 51  # a blank workbook has nothing labelled
    fill(path, {("https://mtn.ng", "CN-02"): ("Non-Compliant", None), ("https://mtn.ng", "CK-01"): ("Not Applicable", "no cookies"), ("https://oxymon.co", "PP-06"): ("Compliant", None)})
    ann = load_annotations(path, IDS, {normalise_site(s) for s in SITES})
    assert ann.blank_rows == 48 and ann.labels[("mtn.ng", "CN-02")].outcome == Outcome.NON_COMPLIANT
    assert ann.labels[("mtn.ng", "CK-01")].outcome == Outcome.NOT_APPLICABLE and ann.labels[("mtn.ng", "CK-01")].na_reason == "no cookies"
    assert ann.labels[("oxymon.co", "PP-06")].outcome == Outcome.COMPLIANT


def test_a_workbook_with_mistakes_is_reported_like_a_csv(tmp_path):
    path = make(tmp_path)
    fill(path, {("https://mtn.ng", "CK-01"): ("Not Applicable", None), ("https://punchng.com", "CN-01"): ("Mostly fine", None)})
    with pytest.raises(AnnotationError) as caught:
        load_annotations(path, IDS, {normalise_site(s) for s in SITES})
    text = "\n".join(caught.value.problems)
    assert "needs a reason" in text and "'Mostly fine' is not a label" in text and len(caught.value.problems) == 2


def test_the_check_command_accepts_a_workbook(tmp_path, capsys):
    path = make(tmp_path)
    fill(path, {("https://mtn.ng", rule): ("Compliant", None) for rule in IDS})
    sites = tmp_path / "sites.txt"
    sites.write_text("\n".join(SITES) + "\n")
    labels.main([str(path), "--sites", str(sites)])
    assert "OK: 17 rows labelled, 34 still blank. 1 site(s) started, 1 complete." in capsys.readouterr().out


def test_the_command_writes_both_workbooks_or_a_pilot_pair(tmp_path, capsys):
    workbook.main(["--out", str(tmp_path / "main")])
    said = capsys.readouterr().out
    assert {p.name for p in (tmp_path / "main").iterdir()} == {"annotator1.xlsx", "annotator2.xlsx"} and "annotator1.xlsx: 30 sites, 510 labels" in said and "annotator2.xlsx: 10 sites, 170 labels" in said
    sites = tmp_path / "pilot_sites.txt"
    sites.write_text("# pilot\nhttps://oxymon.co\nhttps://tekedia.com\n")
    workbook.main(["--pilot", "--sites", str(sites), "--out", str(tmp_path / "pilot")])
    assert {p.name for p in (tmp_path / "pilot").iterdir()} == {"pilot_annotator1.xlsx", "pilot_annotator2.xlsx"} and "pilot_annotator2.xlsx: 2 sites, 34 labels" in capsys.readouterr().out


def test_pilot_sites_are_never_in_the_evaluation_corpus():
    pilot = workbook.Path("eval/pilot_sites.txt")
    if not pilot.exists():
        pytest.skip("no pilot list yet")
    corpus = {normalise_site(s) for s in read_sites(workbook.Path("my_site_list.txt"))}
    assert not ({normalise_site(s) for s in read_sites(pilot)} & corpus)  # otherwise the rulebook would be tuned on the data it is judged on


def test_a_workbook_saved_as_xlsm_is_read_too(tmp_path):
    path = make(tmp_path)
    fill(path, {("https://mtn.ng", "CN-02"): ("Non-Compliant", None)})
    renamed = path.with_suffix(".xlsm")  # Excel offers this extension; the Labels sheet is the same
    path.rename(renamed)
    ann = load_annotations(renamed, IDS, {normalise_site(s) for s in SITES})
    assert ann.labels[("mtn.ng", "CN-02")].outcome == Outcome.NON_COMPLIANT and ann.blank_rows == 50
