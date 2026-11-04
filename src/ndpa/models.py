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


class Event(BaseModel):
    """One observation on the run clock. Key names, sizes and hashes only, never raw values."""
    t_ms: int  # milliseconds since navigation start, one monotonic clock per run (D-30)
    kind: str  # request, response, cookie_set_js, storage_set, capture_error
    domain: str | None = None
    third_party: bool | None = None
    vendor: str | None = None
    detail: dict = Field(default_factory=dict)


class RunStatus(str, Enum):
    OK = "ok"
    BLOCKED = "blocked"
    FAILED = "failed"


class RunResult(BaseModel):
    url: str
    condition: Condition
    status: RunStatus
    block_reasons: list[str] = Field(default_factory=list)
    error: str | None = None
    load_timeout: bool = False
    observe_s: float
    events: list[Event] = Field(default_factory=list)
    cookies: list[dict] = Field(default_factory=list)  # attributes and value_hash, never values
    local_storage_keys: list[str] = Field(default_factory=list)
    session_storage_keys: list[str] = Field(default_factory=list)
    indexeddb_names: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)


class Event(BaseModel):
    """One observation on the run clock. Key names, sizes and hashes only, never raw values."""
    t_ms: int  # milliseconds since navigation start, one monotonic clock per run (D-30)
    kind: str  # request, response, cookie_set_js, storage_set, capture_error
    domain: str | None = None
    third_party: bool | None = None
    vendor: str | None = None
    detail: dict = Field(default_factory=dict)


class RunStatus(str, Enum):
    OK = "ok"
    BLOCKED = "blocked"
    FAILED = "failed"


class RunResult(BaseModel):
    url: str
    condition: Condition
    status: RunStatus
    block_reasons: list[str] = Field(default_factory=list)
    error: str | None = None
    load_timeout: bool = False
    observe_s: float
    events: list[Event] = Field(default_factory=list)
    cookies: list[dict] = Field(default_factory=list)  # attributes and value_hash, never values
    local_storage_keys: list[str] = Field(default_factory=list)
    session_storage_keys: list[str] = Field(default_factory=list)
    indexeddb_names: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
