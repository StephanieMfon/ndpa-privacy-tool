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
