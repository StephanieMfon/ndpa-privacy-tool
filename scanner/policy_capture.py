"""
scanner/policy_capture.py

Phase 3, Module 6 (capture half) — locates and fetches the site's Privacy
Policy / Cookie Policy page text. This is what finally resolves the
"pending_policy_crossref" placeholders left open in cookies.py (CK-04,
CK-05) and trackers.py (TR-02) since Modules 2 and 4.

** Browser-dependent, same caveat as consent_capture.py: this has not run
against a real browser in the environment it was written in. Verify PP-01
and PP-02 specifically against sites where you already know, by eye,
whether the policy is easy to find — those two labels depend entirely on
this file's link-finding heuristic working correctly. **

Scope limitation, stated plainly (Rulebook PP-01 allows "within two
clicks"): this only checks links reachable directly from the homepage (one
click). Most real sites link the policy from the footer, so this covers
the common case — but a site burying its policy inside e.g. an "About"
page one level deeper would be a false negative here. Flag any PP-01
Non-Compliant result for a quick manual click-through before trusting it
as a real finding.
"""

POLICY_LINK_MARKERS = ["privacy policy", "privacy notice", "data protection", "privacy"]
COOKIE_POLICY_LINK_MARKERS = ["cookie policy", "cookie notice", "cookies"]

_FIND_LINK_JS = """
(markers) => {
    const links = Array.from(document.querySelectorAll('a[href]'));
    for (const link of links) {
        const text = (link.innerText || '').trim().toLowerCase();
        const href = (link.getAttribute('href') || '').toLowerCase();
        if (markers.some(m => text.includes(m)) || markers.some(m => href.includes(m.replace(/ /g, '')))) {
            return link.href;  // resolved absolute URL, not the raw href attribute
        }
    }
    return null;
}
"""


def find_policy_links(page) -> dict:
    """Search the current page's links for a Privacy Policy and (separately) a standalone Cookie Policy."""
    privacy_url = page.evaluate(_FIND_LINK_JS, POLICY_LINK_MARKERS)
    cookie_url = page.evaluate(_FIND_LINK_JS, COOKIE_POLICY_LINK_MARKERS)
    return {"privacy_policy_url": privacy_url, "cookie_policy_url": cookie_url}


def fetch_page_content(context, url: str | None, timeout_ms: int = 30000) -> dict | None:
    """
    Open `url` in a new tab within the SAME browser context, extract both
    visible text AND raw HTML, close the tab. HTML is needed alongside
    plain text so BeautifulSoup4 can detect real heading structure
    (PP-02) — inner_text() alone discards all markup, so a "clearly
    headed section" check can't tell a <h2>Cookies</h2> heading from the
    word "cookie" appearing in a random sentence.
    """
    if not url:
        return None
    try:
        p = context.new_page()
        p.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        p.wait_for_timeout(1000)
        text = p.inner_text("body")
        html = p.content()
        p.close()
        return {"text": text, "html": html}
    except Exception:
        return None


def capture_policy_evidence(page, context, timeout_ms: int = 30000) -> dict:
    """
    Run against an ALREADY-OPEN page (same pattern as consent_capture's
    run_consent_interaction) — locates policy links on the current page,
    fetches each in a new tab, returns combined text AND html plus
    reachability evidence for PP-01/PP-02.
    """
    links = find_policy_links(page)
    privacy_content = fetch_page_content(context, links["privacy_policy_url"], timeout_ms)
    cookie_content = fetch_page_content(context, links["cookie_policy_url"], timeout_ms)

    privacy_text = privacy_content["text"] if privacy_content else None
    cookie_text = cookie_content["text"] if cookie_content else None
    combined_text = " ".join(t for t in (privacy_text, cookie_text) if t) or None

    privacy_html = privacy_content["html"] if privacy_content else None
    cookie_html = cookie_content["html"] if cookie_content else None
    combined_html = "\n".join(h for h in (privacy_html, cookie_html) if h) or None

    return {
        "privacy_policy_url": links["privacy_policy_url"],
        "privacy_policy_reachable": links["privacy_policy_url"] is not None and privacy_text is not None,
        "cookie_policy_url": links["cookie_policy_url"],
        "cookie_policy_reachable": links["cookie_policy_url"] is not None and cookie_text is not None,
        "cookie_policy_standalone": links["cookie_policy_url"] is not None,
        "policy_text": combined_text,
        "policy_html": combined_html,
    }