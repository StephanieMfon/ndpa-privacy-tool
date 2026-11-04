from ndpa.capture.run import after_click_activity
from ndpa.models import Condition, ConsentObservation, Event, RunResult, RunStatus


def result(click_ms):
    events = [
        Event(t_ms=100, kind="cookie_set_js", detail={"name": "before"}),
        Event(t_ms=900, kind="request", vendor="Tracker Inc", detail={"tracker": True}),
        Event(t_ms=1000, kind="consent_click", detail={"action": "reject"}),
        Event(t_ms=1200, kind="cookie_set_js", detail={"name": "late_js"}),
        Event(t_ms=1300, kind="response", detail={"set_cookie_names": ["late_srv"]}),
        Event(t_ms=1400, kind="request", vendor="Tracker Inc", detail={"tracker": True}),
        Event(t_ms=1500, kind="request", vendor=None, detail={"tracker": False}),
    ]
    return RunResult(url="https://x.example/", condition=Condition.REJECT, status=RunStatus.OK, observe_s=1,
                     events=events, consent=ConsentObservation(click_ms=click_ms, action="reject"))


def test_only_events_after_the_click_count():
    after = after_click_activity(result(1000))
    assert after == {"tracker_requests": 1, "tracker_vendors": ["Tracker Inc"],
                     "cookie_names": ["late_js", "late_srv"]}


def test_no_click_means_nothing_after_it():
    assert after_click_activity(result(None))["cookie_names"] == []
