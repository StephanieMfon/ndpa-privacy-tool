"""Shared helpers for the rule checks: the evidence of one scan, cookie classification, run windows."""
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ndpa.models import Event, PolicyCapture, RuleResult, RunResult

NECESSARY_PATH = Path("rulebook/necessary_cookies.yaml")


class NecessaryCookies:
    """Register R1: which cookie names are Necessary (rulebook 0.2). Anything else is non-necessary."""

    def __init__(self, groups: dict[str, list[str]]):
        self.groups = {g: [p.lower() for p in patterns] for g, patterns in groups.items()}

    @classmethod
    def load(cls, path: Path = NECESSARY_PATH) -> "NecessaryCookies":
        return cls(yaml.safe_load(Path(path).read_text(encoding="utf-8"))["patterns"])

    def _matches(self, name: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatchcase(name.lower(), p) for p in patterns)

    def is_necessary(self, name: str) -> bool:
        return any(self._matches(name, p) for p in self.groups.values())

    def is_consent_state(self, name: str) -> bool:
        return self._matches(name, self.groups.get("consent_state", []))


@dataclass
class ScanEvidence:
    site_url: str
    no_action: RunResult
    accept: RunResult | None = None
    reject: RunResult | None = None
    policy: PolicyCapture | None = None

    def runs(self) -> list[RunResult]:
        return [r for r in (self.no_action, self.accept, self.reject) if r is not None]


@dataclass
class Ctx:
    ev: ScanEvidence
    necessary: NecessaryCookies
    trigger: bool = False                     # rulebook 0.6: a non-necessary cookie or a tracker, in any run
    trigger_reasons: list[str] = field(default_factory=list)
    mechanism: bool = False                   # a banner or panel appeared in at least one run


def result(rule_id: str, outcome: str, note: str = "", evidence: list[dict] | None = None,
           failed: int = 0, total: int = 0, root_cause: str | None = None) -> RuleResult:
    return RuleResult(rule_id=rule_id, outcome=outcome, note=note, evidence=evidence or [],
                      instances_failed=failed, instances_total=total, root_cause=root_cause)


def windows(ev: ScanEvidence) -> list[tuple[str, RunResult, int | None]]:
    """The 'before consent or after Reject' parts of the capture: all of Run 1, and the Reject run after its click."""
    out: list[tuple[str, RunResult, int | None]] = [("no_action", ev.no_action, None)]
    if ev.reject is not None and ev.reject.consent.click_ms is not None:
        out.append(("reject", ev.reject, ev.reject.consent.click_ms))
    return out


def _in_window(e: Event, since_ms: int | None) -> bool:
    return since_ms is None or e.t_ms >= since_ms


def cookie_sets(run: RunResult, necessary: NecessaryCookies, since_ms: int | None = None,
                include_necessary: bool = False) -> dict[str, dict]:
    """Cookies set in the window: name -> {hows, t_ms, domain}. hows: script, server, server_third_party, jar_only."""
    found: dict[str, dict] = {}

    def add(name: str, how: str, e: Event | None, domain: str | None) -> None:
        if not include_necessary and necessary.is_necessary(name):
            return
        info = found.setdefault(name, {"hows": [], "t_ms": e.t_ms if e else None, "domain": domain})
        if how not in info["hows"]:
            info["hows"].append(how)

    for e in run.events:
        if not _in_window(e, since_ms):
            continue
        if e.kind == "cookie_set_js":
            add(e.detail["name"], "script", e, e.domain)
        elif e.kind == "response":
            for name in e.detail.get("set_cookie_names", []):
                add(name, "server_third_party" if e.third_party else "server", e, e.domain)
    already = set(run.consent.pre_click_cookie_names) if since_ms is not None else set()
    for c in run.cookies:
        if c["name"] not in found and c["name"] not in already:
            add(c["name"], "jar_only", None, c["domain"])
    return found


def tracker_requests(run: RunResult, since_ms: int | None = None) -> list[Event]:
    return [e for e in run.events if e.kind == "request" and e.detail.get("tracker")
            and e.third_party and _in_window(e, since_ms)]


def by_vendor(events: list[Event], run_label: str) -> list[dict]:
    """Compact evidence: one row per vendor, with how many requests and when the first one happened."""
    rows: dict[str, dict] = {}
    for e in events:
        key = e.vendor or e.domain or "unknown"
        row = rows.setdefault(key, {"run": run_label, "vendor": key, "requests": 0, "first_t_ms": e.t_ms,
                                    "resource_types": []})
        row["requests"] += 1
        rtype = e.detail.get("resource_type")
        if rtype and rtype not in row["resource_types"]:
            row["resource_types"].append(rtype)
    return list(rows.values())


def build_ctx(ev: ScanEvidence, necessary: NecessaryCookies) -> Ctx:
    ctx = Ctx(ev=ev, necessary=necessary)
    for run in ev.runs():
        label = run.condition.value
        if cookie_sets(run, necessary):
            ctx.trigger_reasons.append(f"non-necessary cookies in the {label} run")
        if tracker_requests(run):
            ctx.trigger_reasons.append(f"tracker requests in the {label} run")
    ctx.trigger = bool(ctx.trigger_reasons)
    ctx.mechanism = any(r.consent.banner_found for r in ev.runs())
    return ctx
