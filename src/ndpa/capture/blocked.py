"""Blocked-scan detection (decision D-35).

If the site refused to serve us, the scan status is 'blocked' and nothing is scored.
"""
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

BLOCK_STATUSES = {403, 429}
MIN_TEXT_CHARS = 100            # less visible text than this = empty page
BLOCK_PAGE_MAX_TEXT_CHARS = 5000  # phrase check only on small pages
CHALLENGE_MARKERS = (  # v1: fixed before the evaluation scans, never extended per site
    "performing security verification",
    "verify you are human",
    "checking your browser before accessing",
    "just a moment",
    "attention required",
    "enable javascript and cookies to continue",
    "this request was blocked by our security service",
    "request unsuccessful. incapsula incident id",
    "_incapsula_resource",
    "pardon our interruption",
    "press & hold",
    "access denied",
)


@dataclass
class BlockVerdict:
    blocked: bool
    reasons: list[str] = field(default_factory=list)


def visible_text(html_source: str) -> str:
    no_code = re.sub(r"(?is)<(script|style)\b.*?</\1>|<!--.*?-->", " ", html_source)
    text = re.sub(r"(?s)<[^>]+>", " ", no_code)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def detect_block(main_status: int | None, headers: dict | None, dom_html: str) -> BlockVerdict:
    reasons = []
    if main_status in BLOCK_STATUSES:
        reasons.append(f"http_{main_status}")
    lowered = {k.lower(): str(v).lower() for k, v in (headers or {}).items()}
    if lowered.get("cf-mitigated") == "challenge":
        reasons.append("cloudflare_challenge_header")
    text = visible_text(dom_html)
    if len(text) < MIN_TEXT_CHARS:
        reasons.append("empty_page")
    elif len(text) <= BLOCK_PAGE_MAX_TEXT_CHARS:
        haystack = text.lower()
        reasons.extend(f"marker: {m}" for m in CHALLENGE_MARKERS if m in haystack)
    return BlockVerdict(bool(reasons), reasons)


def main_document(har: dict) -> tuple[int | None, dict]:
    """Status and headers of the first non-redirect response (end of the redirect chain)."""
    for entry in har["log"]["entries"]:
        response = entry["response"]
        if not 300 <= response["status"] < 400:
            headers = {h["name"].lower(): h["value"] for h in response.get("headers", [])}
            return response["status"], headers
    return None, {}


def check_evidence_folder(folder: Path) -> BlockVerdict:
    har = json.loads((folder / "network.har").read_text())
    status, headers = main_document(har)
    dom = (folder / "dom_snapshot.html").read_text(encoding="utf-8", errors="replace")
    return detect_block(status, headers, dom)
