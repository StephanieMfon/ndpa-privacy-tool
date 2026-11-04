"""The 'site disclosures' of rulebook 0.5: banner text, preference panel, and the policy pages that were found."""
from dataclasses import dataclass, field

from ndpa.models import Outcome
from ndpa.rules.context import ScanEvidence, result


@dataclass
class Disclosures:
    state: str                                                   # available / absent / uncertain / not_captured
    privacy: list[tuple[str, str]] = field(default_factory=list)  # (source, text) of privacy policy pages
    other: list[tuple[str, str]] = field(default_factory=list)    # banner, panel, cookie pages, other linked pages

    def all(self) -> list[tuple[str, str]]:
        return self.privacy + self.other

    def corpus_lower(self) -> str:
        return "\n".join(text for _, text in self.all()).lower()


def collect(ev: ScanEvidence) -> Disclosures:
    d = Disclosures(state="not_captured")
    banner = ev.no_action.consent.banner_text
    if banner:
        d.other.append(("banner", banner))
    for run in ev.runs():
        if run.consent.panel_text:
            d.other.append(("panel", run.consent.panel_text))
            break
    if ev.policy is None:
        return d
    for page in ev.policy.pages:
        text = ev.policy_texts.get(page.text_file or "", "")
        if not text:
            continue
        (d.privacy if page.is_privacy_policy else d.other).append((page.url, text))
    status = ev.policy.discovery_status
    if status in ("found_linked", "found_unlinked"):
        d.state = "available" if d.privacy else "uncertain"
    elif status == "exhaustive_negative":
        d.state = "absent"
    else:
        d.state = "uncertain"
    return d


def no_match(rule_id: str, d: Disclosures, what: str, evidence=None, failed: int = 0, total: int = 0):
    """The outcome when the thing a rule looks for was not found in the text we have (decision D-34)."""
    if d.state == "absent":
        return result(rule_id, Outcome.NON_COMPLIANT, f"{what}; the site has no privacy policy", evidence,
                      failed, total, root_cause="PP-01")
    if d.state in ("uncertain", "not_captured"):
        why = "policy discovery was uncertain" if d.state == "uncertain" else "the policy was not captured"
        return result(rule_id, Outcome.UNABLE_TO_DETERMINE, f"{what}, but {why}", evidence, failed, total)
    return result(rule_id, Outcome.NON_COMPLIANT, what, evidence, failed, total)
