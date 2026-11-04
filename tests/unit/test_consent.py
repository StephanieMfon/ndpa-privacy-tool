import pytest

from ndpa.capture.consent import classify_control, classify_geometry, describe_first_layer, roles

VIEWPORT = {"width": 1366, "height": 768}


@pytest.mark.parametrize("text,aria,expected", [
    ("Accept all", "", "accept"),
    ("I agree", "", "accept"),
    ("OK", "", "accept"),
    ("Got it!", "", "accept"),
    ("Reject all", "", "reject"),
    ("Decline", "", "reject"),
    ("Accept necessary only", "", "reject"),
    ("Do not accept", "", "reject"),
    ("I disagree", "", "reject"),
    ("Manage preferences", "", "settings"),
    ("Cookie settings", "", "settings"),
    ("×", "", "close"),
    ("", "Close", "close"),
    ("Learn more", "", None),
    ("", "", None),
])
def test_classify_control(text, aria, expected):
    assert classify_control(text, aria) == expected


def box(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def test_bottom_bar_fails_r4():
    g = classify_geometry(box(0, 712, 1366, 56), VIEWPORT)
    assert g["position"] == "bottom" and g["bottom_row_only"] and not g["passes_r4"]


def test_centre_modal_passes_r4():
    g = classify_geometry(box(383, 184, 600, 400), VIEWPORT)
    assert g["position"] == "centre_modal" and g["passes_r4"] and g["coverage"] > 0.2


def test_thin_top_bar_is_top_and_too_small():
    g = classify_geometry(box(0, 0, 1366, 56), VIEWPORT)
    assert g["position"] == "top" and not g["passes_r4"]


def test_big_top_bar_passes_coverage():
    g = classify_geometry(box(0, 0, 1366, 200), VIEWPORT)
    assert g["position"] == "top" and g["passes_r4"]


def test_left_card_and_full_screen():
    assert classify_geometry(box(0, 100, 300, 400), VIEWPORT)["position"] == "left"
    assert classify_geometry(box(0, 0, 1366, 768), VIEWPORT)["position"] == "full_screen"


def test_banner_crossing_the_bottom_line_is_not_bottom_row_only():
    g = classify_geometry(box(0, 400, 1366, 368), VIEWPORT)
    assert not g["bottom_row_only"] and g["passes_r4"]


def controls(*labels):
    return [{"key": None, "text": t, "aria": a, "tag": "button", "box": box(0, 0, 10, 10)} for t, a in labels]


def test_roles_keeps_first_of_each_kind():
    found = roles(controls(("Accept all", ""), ("Accept", ""), ("Reject all", ""), ("×", "Close")))
    assert found["accept"]["text"] == "Accept all"
    assert set(found) == {"accept", "reject", "close"}


def test_describe_first_layer_without_banner():
    obs = describe_first_layer(None, None)
    assert obs.banner_found is False and obs.action == "none" and obs.reject_control is None


def test_describe_first_layer_with_banner():
    banner = {"via": "generic", "bbox": box(0, 712, 1366, 56), "viewport": VIEWPORT, "text": "We use cookies",
              "controls": controls(("Accept all", ""), ("Manage preferences", ""))}
    obs = describe_first_layer(banner, 420)
    assert obs.banner_found and obs.banner_first_seen_ms == 420 and obs.banner_geometry["position"] == "bottom"
    assert obs.accept_control == {"text": "Accept all", "reached_via": "banner"}
    assert obs.reject_control is None and obs.settings_control["text"] == "Manage preferences"
