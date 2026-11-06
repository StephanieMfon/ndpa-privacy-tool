"""The plain-language summary of a scan: no jargon, built only from what the rules found."""
import re

TOPICS = {"PP-02": "a cookie policy", "PP-03": "a privacy contact", "PP-04": "why data is collected",
          "PP-05": "how long data is kept", "PP-06": "people's rights"}


def _clean(name: str) -> str:
    """'Google Ads (Google)' -> 'Google Ads': the owner in brackets is noise in a sentence."""
    return re.sub(r"\s*\(.*?\)", "", name).strip() or name


def _names(items: list[str], limit: int = 3) -> str:
    items = list(dict.fromkeys(_clean(i) for i in items))
    if len(items) <= limit:
        return ", ".join(items[:-1]) + (" and " if len(items) > 1 else "") + items[-1] if items else ""
    return ", ".join(items[:limit]) + f" and {len(items) - limit} more"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _rows(finding: dict | None, run: str, key: str) -> list[str]:
    if not finding:
        return []
    return [str(r[key]) for r in finding["evidence"] if isinstance(r, dict) and r.get("run") == run and key in r]


def plain_summary(card: dict | None, findings: list[dict]) -> dict:
    """Returns {headline, band, points}. `findings` are the enriched findings of one scan."""
    f = {x["rule_id"]: x for x in findings}
    out = lambda rid: f.get(rid, {}).get("outcome")  # noqa: E731
    if card is None or card.get("weighted") is None:
        return {"headline": "There is not enough information to give this site a score.", "band": None, "points": []}
    band = card["band"]
    headline = {
        "high": "High risk. The site tracked or stored visitor data before the visitor agreed, or kept doing so after a "
                "visitor clicked Reject.",
        "moderate": "Moderate risk. Nothing was tracked without consent, but a consent or transparency feature is missing "
                    "or incomplete.",
        "low": "Low risk. " + ("Only small gaps were found." if any(x["outcome"] == "non_compliant" for x in findings)
                               else "None of the checks that applied found a problem."),
    }[band]
    points: list[str] = []

    vendors = _rows(f.get("SB-03"), "no_action", "vendor")
    cookies = _rows(f.get("CN-02"), "no_action", "cookie")
    if vendors or cookies:
        said = []
        if vendors:
            said.append(f"contacted {_plural(len({_clean(v) for v in vendors}), 'tracking company', 'tracking companies')} ({_names(vendors)})")
        if cookies:
            said.append(f"set {_plural(len(set(cookies)), 'cookie', 'cookies')} that "
                        f"{'is' if len(set(cookies)) == 1 else 'are'} not strictly necessary")
        points.append("Before anyone chose anything on the banner, the site " + " and ".join(said) + ".")
    after_v, after_c = _rows(f.get("SB-03"), "reject", "vendor"), _rows(f.get("CN-02"), "reject", "cookie")
    if after_v or after_c:
        bits = []
        if after_v:
            bits.append(f"contacted {_names(after_v)}")
        if after_c:
            bits.append(f"set {_plural(len(set(after_c)), 'more cookie', 'more cookies')}")
        points.append("After a visitor clicked Reject, it still " + " and ".join(bits) + ".")
    elif out("SB-03") == "compliant" and out("CN-02") == "compliant":
        points.append("No tracking was seen before consent or after a visitor clicked Reject.")

    banner = (f.get("CN-01") or {}).get("evidence") or []
    if out("CN-01") == "non_compliant":
        if banner and banner[0].get("banner") == "not found":
            points.append("No cookie banner was shown at all.")
        elif banner and "position" in banner[0]:
            points.append(f"The cookie banner sits at the {banner[0]['position'].replace('_', ' ')} and covers "
                          f"{banner[0]['coverage']:.0%} of the screen, so it is easy to ignore.")
    elif out("CN-01") == "compliant":
        points.append("The cookie banner is clearly visible.")
    if out("CN-03") == "non_compliant" and f["CN-03"].get("root_cause") != "CN-01":
        points.append("The banner does not offer a Reject option.")
    if out("CN-05") == "non_compliant":
        points.append("There is no way for a visitor to change their cookie choice later.")

    if out("PP-01") == "non_compliant":
        points.append("No privacy policy could be found within two clicks of the homepage.")
    elif out("PP-01") == "compliant":
        policy = [x for x in findings if x["rule_id"].startswith("PP-") and x["rule_id"] != "PP-01"
                  and x["outcome"] in ("compliant", "non_compliant")]
        failed = [TOPICS.get(x["rule_id"], x["name"].lower()) for x in policy if x["outcome"] == "non_compliant"]
        points.append(f"The privacy policy was found. {len(policy) - len(failed)} of {len(policy)} content checks passed"
                      + (f"; it does not cover {_names(failed, 4)}." if failed else "."))
    tr = f.get("TR-02")
    if tr and tr["outcome"] == "non_compliant" and tr["instances_total"]:
        points.append(f"{tr['instances_failed']} of the {tr['instances_total']} trackers found are not named in the policy.")
    return {"headline": headline, "band": band, "points": points}
