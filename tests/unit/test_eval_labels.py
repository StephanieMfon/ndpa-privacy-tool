import pytest

from ndpa.evaluation.labels import AnnotationError, complete_sites, load_annotations, normalise_site, parse_label
from ndpa.models import Outcome

RULES = ["CK-01", "CN-01", "SB-03"]


def sheet(tmp_path, text, name="a.csv", encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


HEADER = "site,rule_id,label,na_reason,evidence_ref,notes\n"


def test_sites_are_compared_by_their_host_only():
    assert normalise_site("https://www.Example.com.ng/path?x=1") == "example.com.ng"
    assert normalise_site("example.com.ng") == "example.com.ng" and normalise_site("http://gtbank.com/") == "gtbank.com"
    assert normalise_site("") == ""
    assert normalise_site("http://127.0.0.1:8123/x") == "127.0.0.1:8123" and normalise_site("https://a.ng:443/") == "a.ng" and normalise_site("http://a.ng:80") == "a.ng"


@pytest.mark.parametrize("raw,expected", [("Compliant", Outcome.COMPLIANT), (" non-compliant ", Outcome.NON_COMPLIANT), ("Non_Compliant", Outcome.NON_COMPLIANT),
                                          ("NC", Outcome.NON_COMPLIANT), ("c", Outcome.COMPLIANT), ("Not Applicable", Outcome.NOT_APPLICABLE), ("N/A", Outcome.NOT_APPLICABLE),
                                          ("na", Outcome.NOT_APPLICABLE), ("", None), ("   ", None)])
def test_label_spellings(raw, expected):
    assert parse_label(raw) == expected


def test_a_good_sheet_loads_and_blank_rows_are_counted(tmp_path):
    path = sheet(tmp_path, HEADER + "https://a.ng,CK-01,Compliant,,,\nhttps://a.ng,CN-01,Non-Compliant,,shot1,no banner\nhttps://a.ng,SB-03,,,,\n"
                 "https://a.ng,CK-01,Compliant,,,\n")  # the same label twice is harmless
    ann = load_annotations(path, RULES)
    assert ann.blank_rows == 1 and set(ann.labels) == {("a.ng", "CK-01"), ("a.ng", "CN-01")}
    assert ann.labels[("a.ng", "CN-01")].notes == "no banner" and ann.labels[("a.ng", "CN-01")].evidence_ref == "shot1"
    assert complete_sites(ann, RULES) == set() and complete_sites(ann, ["CK-01", "CN-01"]) == {"a.ng"}


def test_every_problem_is_reported_together(tmp_path):
    path = sheet(tmp_path, HEADER + "a.ng,CK-01,Maybe,,,\na.ng,XX-99,Compliant,,,\na.ng,CN-01,Not Applicable,,,\nb.ng,CK-01,Compliant,,,\nb.ng,CK-01,Non-Compliant,,,\nz.ng,CK-01,Compliant,,,\n")
    with pytest.raises(AnnotationError) as caught:
        load_annotations(path, RULES, site_keys={"a.ng", "b.ng"})
    text = "\n".join(caught.value.problems)
    assert len(caught.value.problems) == 5
    assert "'Maybe' is not a label" in text and "'XX-99' is not a scored rule" in text and "needs a reason" in text
    assert "appear twice with different labels" in text and "not in the corpus" in text
    assert "row 2" in text  # a problem names the spreadsheet row, counting the header as row 1


def test_a_missing_column_or_empty_file_is_explained(tmp_path):
    with pytest.raises(AnnotationError, match="missing the column"):
        load_annotations(sheet(tmp_path, "site,rule\na.ng,CK-01\n"), RULES)
    with pytest.raises(AnnotationError, match="no rows"):
        load_annotations(sheet(tmp_path, HEADER, name="empty.csv"), RULES)


def test_sheets_saved_by_spreadsheets_in_other_locales_still_load(tmp_path):
    body = "site;rule_id;label;na_reason;evidence_ref;notes\r\na.ng;CK-01;Compliant;;;\r\na.ng;CN-01;Not Applicable;no trigger;;\r\n"
    ann = load_annotations(sheet(tmp_path, body, encoding="utf-8-sig"), RULES)  # semicolons, Windows line ends and a byte-order mark
    assert ann.labels[("a.ng", "CN-01")].outcome == Outcome.NOT_APPLICABLE and ann.labels[("a.ng", "CN-01")].na_reason == "no trigger"
    upper = HEADER.upper() + "a.ng,ck-01,compliant,,,\n"  # header case and rule id case do not matter
    assert ("a.ng", "CK-01") in load_annotations(sheet(tmp_path, upper, name="u.csv"), RULES).labels


def test_the_check_command_tells_an_annotator_what_is_missing_or_wrong(tmp_path, capsys):
    from ndpa.evaluation import labels
    from ndpa.scoring.score import load_rulebook

    ids = [r["id"] for r in load_rulebook()["rules"] if r.get("tier") != "unscored"]
    sites = tmp_path / "sites.txt"
    sites.write_text("https://a.ng\nhttps://b.ng\n")
    rows = "".join(f"https://a.ng,{rule},Compliant,,,\n" for rule in ids) + "".join(f"https://b.ng,{rule},Compliant,,,\n" for rule in ids[:5])
    good = sheet(tmp_path, HEADER + rows + "https://b.ng," + ids[5] + ",,,,\n", name="good.csv")
    labels.main([str(good), "--sites", str(sites)])
    said = capsys.readouterr().out
    assert "OK: 22 rows labelled, 1 still blank" in said and "2 site(s) started, 1 complete" in said and "b.ng: 12 rule(s) still to label" in said
    bad = sheet(tmp_path, HEADER + "https://zzz.ng,CK-01,Compliant,,,\n", name="bad.csv")
    with pytest.raises(SystemExit, match="not in the corpus"):
        labels.main([str(bad), "--sites", str(sites)])
