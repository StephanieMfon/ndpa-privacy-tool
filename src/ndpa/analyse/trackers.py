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


def is_third_party(url: str, site_url: str) -> bool:
    return _extract(url).registered_domain != _extract(site_url).registered_domain


class TrackerList:
    def __init__(self, path: Path = SNAPSHOT):
        self._trackers = json.loads(Path(path).read_text())["trackers"]

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
