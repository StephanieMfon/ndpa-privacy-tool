"""Shared data contracts between pipeline stages."""
from enum import Enum

from pydantic import BaseModel, Field


class Outcome(str, Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    NOT_APPLICABLE = "not_applicable"
    UNABLE_TO_DETERMINE = "unable_to_determine"  # tool only


class ScanStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"


class Condition(str, Enum):
    NO_ACTION = "no_action"
    ACCEPT = "accept"
    REJECT = "reject"


class RuleResult(BaseModel):
    rule_id: str
    outcome: Outcome
    instances_failed: int = 0
    instances_total: int = 0
    root_cause: str | None = None  # e.g. "PP-01"
    evidence: list[dict] = Field(default_factory=list)  # key names and hashes only, never raw bodies
    note: str = ""


class ScoreCard(BaseModel):
    status: ScanStatus
    score_weighted: float | None = None  # None when blocked or coverage too low
    score_equal: float | None = None
    band: str | None = None  # high / moderate / low
    critical_count: int = 0
    coverage: float = 0.0
    category_scores: dict[str, float] = Field(default_factory=dict)
    empty_categories: list[str] = Field(default_factory=list)  # categories with no applicable rule
    scored_weight: float = 0.0  # points of rules that applied (compliant or non-compliant)
    total_weight: float = 0.0  # points in the whole rulebook
    note: str = ""  # why a score is missing or hidden


class Event(BaseModel):
    """One observation on the run clock. Key names, sizes and hashes only, never raw values."""
    t_ms: int  # milliseconds since navigation start, one monotonic clock per run (D-30)
    kind: str  # request, response, cookie_set_js, storage_set, consent_click, capture_error, ...
    domain: str | None = None
    third_party: bool | None = None
    vendor: str | None = None
    detail: dict = Field(default_factory=dict)


class RunStatus(str, Enum):
    OK = "ok"
    BLOCKED = "blocked"
    FAILED = "failed"


class ConsentObservation(BaseModel):
    """What the banner looked like and what happened when it was used (rulebook 0.4)."""
    banner_found: bool = False
    banner_first_seen_ms: int | None = None
    banner_via: str | None = None  # "known" (CMP selector) or "generic"
    banner_bbox: dict | None = None
    banner_geometry: dict | None = None  # position, coverage, bottom_row_only, passes_r4 (R4)
    banner_text: str | None = None
    accept_control: dict | None = None  # {text, reached_via}
    reject_control: dict | None = None
    settings_control: dict | None = None
    close_control: dict | None = None
    action: str = "none"  # accept / reject / close / none
    click_ms: int | None = None
    note: str = ""
    pre_click_cookie_names: list[str] = Field(default_factory=list)
    pre_click_local_storage_keys: list[str] = Field(default_factory=list)
    banner_after_reload: bool | None = None
    reopen_control: str | None = None
    panel_text: str | None = None  # text of the preferences panel, when the Reject run opened one


class RunResult(BaseModel):
    url: str
    condition: Condition
    status: RunStatus
    block_reasons: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: float | None = None  # UTC epoch seconds when the run began
    browser_version: str | None = None  # e.g. 141.0.7390.37 (register R6: record the Chrome version)
    captured_at: float | None = None  # UTC epoch seconds when the cookie jar was read (lifespans are measured from here)
    load_timeout: bool = False
    load_ms: int | None = None  # when navigation finished (or timed out), on the run clock
    observe_s: float
    events: list[Event] = Field(default_factory=list)
    cookies: list[dict] = Field(default_factory=list)  # attributes and value_hash, never values
    local_storage_keys: list[str] = Field(default_factory=list)
    session_storage_keys: list[str] = Field(default_factory=list)
    indexeddb_names: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
    consent: ConsentObservation = Field(default_factory=ConsentObservation)


class PolicyPage(BaseModel):
    """One page visited while looking for the privacy or cookie policy."""
    url: str
    kinds: list[str]  # privacy, cookie, terms
    via: str  # "link" (followed from the homepage) or "probe" (common path)
    click_path: list[str] = Field(default_factory=list)  # link texts from the homepage
    http_status: int | None = None
    text_chars: int = 0
    headings: list[str] = Field(default_factory=list)
    text_file: str | None = None
    is_privacy_policy: bool = False  # long enough and about privacy (or a headed privacy section, R11)
    embedded: bool = False  # privacy section inside the Terms page


class PolicyCapture(BaseModel):
    discovery_status: str  # found_linked / found_unlinked / exhaustive_negative / uncertain
    pages: list[PolicyPage] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
