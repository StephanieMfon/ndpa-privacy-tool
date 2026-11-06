from ndpa.web.summary import plain_summary


def f(rule_id, outcome, evidence=None, failed=0, total=0, root=None, name="x"):
    return {"rule_id": rule_id, "outcome": outcome, "evidence": evidence or [], "instances_failed": failed,
            "instances_total": total, "root_cause": root, "name": name}


def card(band="high", weighted=40.0):
    return {"weighted": weighted, "band": band}


def test_no_score_gives_no_claims():
    s = plain_summary({"weighted": None, "band": None}, [])
    assert s["points"] == [] and "not enough" in s["headline"]
    assert plain_summary(None, [])["band"] is None


def test_a_high_risk_site_with_tracking_before_consent():
    findings = [f("SB-03", "non_compliant", [{"run": "no_action", "vendor": "Google Ads (Google)"}, {"run": "no_action", "vendor": "Criteo"},
                                           {"run": "no_action", "vendor": "Taboola"}, {"run": "no_action", "vendor": "OpenX"}]),
                f("CN-02", "non_compliant", [{"run": "no_action", "cookie": "_ga"}, {"run": "no_action", "cookie": "_fbp"}])]
    s = plain_summary(card(), findings)
    assert s["headline"].startswith("High risk")
    text = " ".join(s["points"])
    assert "4 tracking companies" in text and "Google Ads, Criteo, Taboola and 1 more" in text and "(Google)" not in text
    assert "2 cookies that are not strictly necessary" in text


def test_singular_wording_and_after_reject():
    findings = [f("SB-03", "non_compliant", [{"run": "no_action", "vendor": "Criteo"}, {"run": "reject", "vendor": "Criteo"}]),
                f("CN-02", "non_compliant", [{"run": "no_action", "cookie": "_ga"}, {"run": "reject", "cookie": "_late"}])]
    text = " ".join(plain_summary(card(), findings)["points"])
    assert "1 tracking company (Criteo)" in text and "1 cookie that is not strictly necessary" in text
    assert "After a visitor clicked Reject, it still contacted Criteo and set 1 more cookie" in text


def test_a_respectful_site_is_told_so():
    findings = [f("SB-03", "compliant"), f("CN-02", "compliant"), f("CN-01", "compliant")]
    s = plain_summary(card("low", 100.0), findings)
    assert s["headline"].startswith("Low risk. None of the checks")
    assert any("No tracking was seen" in p for p in s["points"]) and any("clearly visible" in p for p in s["points"])


def test_banner_findings():
    bottom = f("CN-01", "non_compliant", [{"position": "bottom", "coverage": 0.08}])
    assert "sits at the bottom and covers 8% of the screen" in " ".join(plain_summary(card(), [bottom])["points"])
    assert "No cookie banner was shown at all." in plain_summary(card(), [f("CN-01", "non_compliant", [{"banner": "not found"}])])["points"]
    no_reject = f("CN-03", "non_compliant", root=None)
    assert "does not offer a Reject option" in " ".join(plain_summary(card(), [no_reject])["points"])
    cascade = f("CN-03", "non_compliant", root="CN-01")
    assert "Reject option" not in " ".join(plain_summary(card(), [cascade])["points"])  # already said by the banner finding


def test_policy_findings():
    missing = plain_summary(card(), [f("PP-01", "non_compliant")])["points"]
    assert "No privacy policy could be found within two clicks of the homepage." in missing
    findings = [f("PP-01", "compliant"), f("PP-02", "compliant"), f("PP-04", "non_compliant", name="Purpose"), f("PP-05", "non_compliant"),
                f("PP-06", "compliant"), f("TR-02", "non_compliant", failed=11, total=12)]
    text = " ".join(plain_summary(card(), findings)["points"])
    assert "2 of 4 content checks passed" in text and "does not cover why data is collected and how long data is kept" in text
    assert "11 of the 12 trackers found are not named" in text


def test_moderate_headline_and_small_gap_wording():
    assert plain_summary(card("moderate", 80), [])["headline"].startswith("Moderate risk")
    assert "Only small gaps" in plain_summary(card("low", 95), [f("CN-04", "non_compliant")])["headline"]
