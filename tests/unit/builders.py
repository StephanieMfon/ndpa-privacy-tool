"""Small builders for rule tests: runs, events, banners and policies with only the fields a test cares about."""
from ndpa.models import Condition, ConsentObservation, Event, PolicyCapture, PolicyPage, RunResult, RunStatus
from ndpa.rules.context import NecessaryCookies, ScanEvidence

NECESSARY = NecessaryCookies({
    "consent_state": ["OptanonConsent", "cmp_consent"],
    "session": ["JSESSIONID"],
})


def geometry(position="centre_modal", coverage=0.2, bottom_row_only=False, passes=True):
    return {"position": position, "coverage": coverage, "bottom_row_only": bottom_row_only, "passes_r4": passes}


def consent(found=True, reject=None, accept=None, settings=None, action="none", click_ms=None, note="",
            after_reload=None, reopen=None, pre_cookies=(), pre_storage=(), geo=None, banner_text=None, panel_text=None):
    return ConsentObservation(
        banner_found=found, banner_first_seen_ms=3010 if found else None, banner_geometry=(geo or geometry()) if found else None,
        accept_control={"text": "Accept", "reached_via": "banner"} if accept else None,
        reject_control={"text": "Reject", "reached_via": reject} if reject else None,
        settings_control={"text": "Manage", "reached_via": "banner"} if settings else None,
        action=action, click_ms=click_ms, note=note, banner_after_reload=after_reload, reopen_control=reopen,
        pre_click_cookie_names=list(pre_cookies), pre_click_local_storage_keys=list(pre_storage),
        banner_text=banner_text, panel_text=panel_text)


def run(condition=Condition.NO_ACTION, cons=None, events=(), cookies=(), storage=(), status=RunStatus.OK, jar=None,
        captured_at=1_700_000_000.0):
    """cookies: names only (session cookies on shop.example). jar: full cookie dicts, for lifespans and third parties."""
    entries = [{"name": n, "domain": "shop.example", "expires": -1} for n in cookies] + list(jar or [])
    return RunResult(url="https://shop.example/", condition=condition, status=status, observe_s=1, load_ms=3000,
                     captured_at=captured_at, consent=cons or consent(found=False), events=list(events),
                     cookies=entries, local_storage_keys=list(storage))


def js_cookie(t, name, vendor=None, script="https://cdn.example/x.js"):
    return Event(t_ms=t, kind="cookie_set_js", domain="cdn.example", third_party=True, vendor=vendor,
                 detail={"name": name, "script": script, "attributed": True})


def server_cookie(t, *names, third_party=False, domain="shop.example"):
    return Event(t_ms=t, kind="response", domain=domain, third_party=third_party,
                 detail={"set_cookie_names": list(names), "resource_type": "document"})


def tracker_request(t, vendor="Tracker Inc", rtype="xhr", domain="t.example"):
    return Event(t_ms=t, kind="request", domain=domain, third_party=True, vendor=vendor,
                 detail={"tracker": True, "resource_type": rtype})


def storage_set(t, key, vendor=None):
    return Event(t_ms=t, kind="storage_set", domain="t.example", third_party=True, vendor=vendor,
                 detail={"area": "localStorage", "key": key})


def policy_page(n=1, kinds=("privacy",), privacy=True, via="link", path=("Privacy Policy",), headings=(), chars=3000,
                embedded=False):
    return PolicyPage(url=f"https://shop.example/p{n}", kinds=list(kinds), via=via, click_path=list(path),
                      http_status=200, text_chars=chars, headings=list(headings), text_file=f"policy_page_{n}.txt",
                      is_privacy_policy=privacy, embedded=embedded)


def policy(status="found_linked", pages=(), problems=()):
    return PolicyCapture(discovery_status=status, pages=list(pages), problems=list(problems))


def scan(no_action, accept=None, reject=None, pol=None, texts=None):
    return ScanEvidence("https://shop.example/", no_action, accept, reject, pol, texts or {})


def scan_with_policy(text, *, headings=(), no_action=None, status="found_linked"):
    """A scan whose only privacy policy page has this text."""
    return scan(no_action or run(), pol=policy(status, [policy_page(headings=headings)]),
                texts={"policy_page_1.txt": text})
