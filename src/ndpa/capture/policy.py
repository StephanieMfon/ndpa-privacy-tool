"""Find the privacy and cookie policies and save their text (rulebook PP-01 to PP-06, register R11).

Usage:
    python -m ndpa.capture.policy https://example.com.ng [--headless] [--bundled-chromium]
"""
import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from ndpa.capture.blocked import detect_block
from ndpa.capture.run import BrowserConfig
from ndpa.models import PolicyCapture, PolicyPage

MIN_TEXT_CHARS = 500   # shorter pages are placeholders
EMPTY_SHELL_CHARS = 50  # almost no text at all: probably a page that did not render
MAX_LINKS_PER_KIND = 3
MAX_HUBS = 4
COMMON_PATHS = ("/privacy", "/privacy-policy", "/privacy-notice", "/data-protection",
                "/legal/privacy", "/cookie-policy")

_PRIVACY = re.compile(r"privacy|data protection|ndpa|personal data", re.I)
_COOKIE = re.compile(r"cookie", re.I)
_TERMS = re.compile(r"\bterms\b|\bconditions of (use|service)\b", re.I)
_HUB = re.compile(r"\b(legal|policies|policy|trust|compliance|about|help|support|contact)\b", re.I)
_ABOUT_PRIVACY = re.compile(r"privacy|personal data|data protection", re.I)

LINKS_JS = """() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
  href: a.href, text: (a.innerText || a.getAttribute('aria-label') || a.title || '').trim().slice(0, 100)
})).filter(l => /^https?:/.test(l.href))"""
HEADINGS_JS = """() => Array.from(document.querySelectorAll('h1,h2,h3,h4'))
  .map(h => h.innerText.trim()).filter(Boolean).slice(0, 60)"""
TEXT_JS = "() => document.body ? document.body.innerText : ''"


def classify_link(text: str, href: str) -> set[str]:
    """Which kinds of link this is: privacy, cookie, terms, hub (a page that may list the policies)."""
    path = urlparse(href).path
    kinds = set()
    for kind, pattern in (("privacy", _PRIVACY), ("cookie", _COOKIE), ("terms", _TERMS)):
        if pattern.search(text) or pattern.search(path):
            kinds.add(kind)
    if not kinds and (_HUB.search(text) or _HUB.search(path)):
        kinds.add("hub")
    return kinds


def pick_links(links: list[dict], kind: str, current_url: str = "", limit: int = MAX_LINKS_PER_KIND) -> list[dict]:
    """Up to `limit` distinct links of one kind, links whose visible text matches first."""
    seen, picked = {current_url.split("#")[0]}, []
    for link in links:
        href = link["href"].split("#")[0]
        if href in seen or kind not in classify_link(link["text"], link["href"]):
            continue
        seen.add(href)
        picked.append(link)
    picked.sort(key=lambda lk: 0 if _kind_in_text(kind, lk["text"]) else 1)  # stable
    return picked[:limit]


def _kind_in_text(kind: str, text: str) -> bool:
    return bool({"privacy": _PRIVACY, "cookie": _COOKIE, "terms": _TERMS, "hub": _HUB}[kind].search(text))


def is_policy_text(text: str) -> bool:
    return len(text) >= MIN_TEXT_CHARS and bool(_ABOUT_PRIVACY.search(text))


def headings_mention_privacy(headings: list[str]) -> bool:
    return any(_ABOUT_PRIVACY.search(h) for h in headings)


class _Walker:
    def __init__(self, page, out_dir: Path):
        self.page, self.out_dir = page, out_dir
        self.pages: list[PolicyPage] = []
        self.problems: list[str] = []
        self.visited: set[str] = set()
        self.by_final_url: dict[str, PolicyPage] = {}  # a redirect may lead to a page already seen

    def links(self) -> list[dict]:
        try:
            return self.page.evaluate(LINKS_JS)
        except Exception:  # noqa: BLE001
            return []

    def _text_and_headings(self) -> tuple[str, list[str]]:
        """Visible text and headings of the page and of every frame in it (policies are often embedded)."""
        parts, headings = [], []
        for frame in self.page.frames:
            try:
                text, found = frame.evaluate(TEXT_JS), frame.evaluate(HEADINGS_JS)
            except Exception:  # noqa: BLE001  (frame went away)
                continue
            if text and text.strip():
                parts.append(text)
            headings.extend(found)
        return "\n".join(parts), headings[:60]

    def visit(self, url: str, kinds: set[str], via: str, click_path: list[str]) -> PolicyPage | None:
        """Open one page and record it. Pages that do not exist (404) are not recorded and are not a problem."""
        self.visited.add(url.split("#")[0])
        if urlparse(url).path.lower().endswith(".pdf"):
            if kinds & {"privacy", "cookie"}:
                self.problems.append(f"PDF policy, text not read: {url}")
            return None
        status = None
        try:
            response = self.page.goto(url, wait_until="load", timeout=20000)
            status = response.status if response else None
        except PlaywrightTimeout:
            self.problems.append(f"timeout: {url}")
        except Exception as exc:  # noqa: BLE001  (for example a PDF, which downloads instead of opening)
            self.problems.append(f"could not open {url} ({type(exc).__name__})")
            return None
        self.page.wait_for_timeout(1000)
        if status in (403, 429) or (status or 0) >= 500:
            self.problems.append(f"http {status}: {url}")
            return None
        if status is not None and status >= 400:
            return None
        final = self.page.url.split("#")[0]
        if final in self.by_final_url:
            return self.by_final_url[final]
        text, headings = self._text_and_headings()
        blocked = [r for r in detect_block(status, {}, self.page.content()).reasons if r != "empty_page"]
        if blocked:
            self.problems.append(f"blocked ({blocked[0]}): {url}")
            return None
        number = len(self.pages) + 1
        text_file = f"policy_page_{number}.txt"
        (self.out_dir / text_file).write_text(text[:300000], encoding="utf-8")
        page = PolicyPage(url=self.page.url, kinds=sorted(kinds), via=via, click_path=click_path,
                          http_status=status, text_chars=len(text), headings=headings, text_file=text_file)
        if "privacy" in kinds:
            page.is_privacy_policy = is_policy_text(text)
            if not page.is_privacy_policy and len(text) < EMPTY_SHELL_CHARS:
                self.problems.append(f"almost no text, possibly not rendered: {url}")
        if "terms" in kinds and len(text) >= MIN_TEXT_CHARS and headings_mention_privacy(headings):
            page.kinds = sorted(set(page.kinds) | {"privacy"})
            page.is_privacy_policy, page.embedded = True, True  # register R11
        self.pages.append(page)
        self.by_final_url[final] = page
        return page


def discover(page, home_url: str, out_dir: Path) -> PolicyCapture:
    out_dir.mkdir(parents=True, exist_ok=True)
    walker = _Walker(page, out_dir)
    try:
        response = page.goto(home_url, wait_until="load", timeout=30000)
        status = response.status if response else None
    except PlaywrightTimeout:
        status = None
        walker.problems.append("timeout: homepage")
    except Exception as exc:  # noqa: BLE001
        return PolicyCapture(discovery_status="uncertain", problems=[f"homepage failed ({type(exc).__name__})"])
    page.wait_for_timeout(1000)
    verdict = detect_block(status, {}, page.content())
    if verdict.blocked:
        return PolicyCapture(discovery_status="uncertain", problems=[f"homepage blocked: {verdict.reasons}"])
    home = page.url
    home_links = walker.links()
    found = False

    def try_privacy(links, via_text):
        nonlocal found
        for link in pick_links(links, "privacy", walker.page.url):
            if link["href"].split("#")[0] in walker.visited:
                continue
            visited = walker.visit(link["href"], classify_link(link["text"], link["href"]) | {"privacy"}, "link",
                                   via_text + [link["text"]])
            if visited and visited.is_privacy_policy:
                found = True
                return

    # one click: privacy links on the homepage
    try_privacy(home_links, [])
    # two clicks: a hub page ("Legal", "Policies" ...) that lists the policy
    if not found:
        for hub in pick_links(home_links, "hub", home, MAX_HUBS):
            if hub["href"].split("#")[0] in walker.visited:
                continue
            if walker.visit(hub["href"], {"hub"}, "link", [hub["text"]]) is None:
                continue
            try_privacy(walker.links(), [hub["text"]])
            if found:
                break
    # a headed privacy section inside the Terms page (register R11)
    if not found:
        for link in pick_links(home_links, "terms", home, 2):
            visited = walker.visit(link["href"], {"terms"}, "link", [link["text"]])
            if visited and visited.is_privacy_policy:
                found = True
                break
    # cookie policy links from the homepage (recorded for PP-02, they do not change the status)
    for link in pick_links(home_links, "cookie", home, 2):
        if link["href"].split("#")[0] not in walker.visited:
            walker.visit(link["href"], {"cookie"}, "link", [link["text"]])
    if found:
        return PolicyCapture(discovery_status="found_linked", pages=walker.pages, problems=walker.problems)

    # common paths
    origin = f"{urlparse(home).scheme}://{urlparse(home).netloc}"
    for path in COMMON_PATHS:
        url = urljoin(origin, path)
        if url.split("#")[0] in walker.visited:
            continue
        kinds = {"cookie"} if "cookie" in path else {"privacy"}
        visited = walker.visit(url, kinds, "probe", [])
        if visited and visited.is_privacy_policy:
            return PolicyCapture(discovery_status="found_unlinked", pages=walker.pages, problems=walker.problems)
    status_name = "uncertain" if walker.problems else "exhaustive_negative"
    return PolicyCapture(discovery_status=status_name, pages=walker.pages, problems=walker.problems)


def capture_policy(url: str, out_dir: Path, browser_config: BrowserConfig | None = None) -> PolicyCapture:
    cfg = browser_config or BrowserConfig()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=cfg.channel, headless=cfg.headless)
        context = browser.new_context(viewport={"width": cfg.viewport[0], "height": cfg.viewport[1]},
                                      locale=cfg.locale, timezone_id=cfg.timezone_id)
        result = discover(context.new_page(), url, out_dir)
        context.close()
        browser.close()
    (out_dir / "policy.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result


def summary(pc: PolicyCapture) -> str:
    lines = [f"discovery status : {pc.discovery_status}"]
    for p in pc.pages:
        path = " > ".join(p.click_path) if p.click_path else "(common path)"
        lines.append(f"  page: {p.url}\n        kinds={p.kinds} via={p.via} path={path} chars={p.text_chars} "
                     f"privacy policy={p.is_privacy_policy} embedded={p.embedded}")
    lines += [f"  problem: {x}" for x in pc.problems]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Find the privacy and cookie policies of one site.")
    ap.add_argument("url")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--bundled-chromium", action="store_true")
    args = ap.parse_args()
    host = re.sub(r"[^a-zA-Z0-9.\-]", "_", urlparse(args.url).netloc)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    out_dir = Path("data/evidence") / host / stamp / "policy"
    cfg = BrowserConfig(channel=None if args.bundled_chromium else "chrome", headless=args.headless)
    print(f"=== {args.url} [policy]")
    print(summary(capture_policy(args.url, out_dir, cfg)))
    print(f"evidence: {out_dir}")


if __name__ == "__main__":
    main()
