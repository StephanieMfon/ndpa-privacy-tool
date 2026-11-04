"""Tracker matching against the frozen blocklist snapshot (register R8)."""
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import tldextract

_extract = tldextract.TLDExtract(suffix_list_urls=())  # bundled suffix list, no network call

SNAPSHOT = Path("data/lists/tds-snapshot.json")


@dataclass(frozen=True)
class TrackerMatch:
    domain: str
    owner: str
    categories: tuple[str, ...]
    reason: str


def registrable_domain(url_or_host: str) -> str:
    return _extract(url_or_host).top_domain_under_public_suffix


def is_third_party(url: str, site_url: str) -> bool:
    return _extract(url).top_domain_under_public_suffix != _extract(site_url).top_domain_under_public_suffix


class TrackerList:
    def __init__(self, path: Path = SNAPSHOT):
        self._trackers = json.loads(Path(path).read_text())["trackers"]

    def owner_of(self, host: str) -> str | None:
        """The organisation behind a domain according to the list, whatever the domain's default action."""
        parts = host.lower().split(".")
        for i in range(len(parts) - 1):
            entry = self._trackers.get(".".join(parts[i:]))
            if entry:
                owner = entry.get("owner") or {}
                return owner.get("displayName") or owner.get("name") or None
        return None

    def match(self, url: str) -> TrackerMatch | None:
        """Return a TrackerMatch if this request URL is a tracker request, else None."""
        parts = (urlparse(url).hostname or "").lower().split(".")
        for i in range(len(parts) - 1):
            domain = ".".join(parts[i:])
            if domain in self._trackers:
                return self._decide(domain, self._trackers[domain], url)
        return None

    @staticmethod
    def _decide(domain: str, entry: dict, url: str) -> TrackerMatch | None:
        owner = entry.get("owner") or {}
        name = owner.get("displayName") or owner.get("name", "")
        cats = tuple(entry.get("categories") or ())
        bare = re.sub(r"^[a-z]+://", "", url, flags=re.I)
        for rule in entry.get("rules") or []:
            try:
                hit = re.search(rule["rule"], bare, re.I) or re.search(rule["rule"], url, re.I)
            except re.error:
                continue
            if hit:
                if rule.get("action", "block") == "ignore":
                    return None
                return TrackerMatch(domain, name, cats, f"url rule: {rule['rule']}")
        if entry.get("default") == "block":
            return TrackerMatch(domain, name, cats, "default: block")
        return None
