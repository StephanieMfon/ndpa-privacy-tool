import re
import xml.etree.ElementTree as ET

from ndpa.web import charts

AXES = [{"key": "a", "label": "Cookies", "value": 30, "empty": False}, {"key": "b", "label": "Consent", "value": 60, "empty": False},
        {"key": "c", "label": "Trackers <b>", "value": 100, "empty": True}, {"key": "d", "label": "Scripts", "value": 0, "empty": False},
        {"key": "e", "label": "Policy", "value": 90, "empty": False}]


def parse(svg):
    return ET.fromstring(str(svg))


def test_every_chart_is_well_formed_xml_without_inline_styles():
    outputs = [charts.gauge_svg(58.5, "high"), charts.gauge_svg(None, None), charts.bar_svg(72, 40), charts.bar_svg(150),
               charts.radar_svg(AXES, {"a": 50}), charts.sparkline_svg([40, None, 55]),
               charts.timeline_svg([{"lane": "tracker", "t_ms": 1000, "label": "x", "flag": True}], 5000, 3000, "You click Reject", 800)]
    for svg in outputs:
        parse(svg)
        assert " style=" not in str(svg)  # inline styles would break the strict Content-Security-Policy


def test_gauge_arc_is_proportional_to_the_score():
    def arc(score):
        dash = re.search(r'stroke-dasharray="([\d.]+) ([\d.]+)"', str(charts.gauge_svg(score, "low")))
        return float(dash.group(1)) / float(dash.group(2))
    assert abs(arc(50) - 0.5) < 0.01 and abs(arc(100) - 1.0) < 0.01
    assert "gauge-arc" not in str(charts.gauge_svg(None, None)) and "No score" in str(charts.gauge_svg(None, None))


def test_bar_is_clamped_and_can_show_an_earlier_value():
    assert 'width="100.0"' in str(charts.bar_svg(150)) and 'width="0.0"' in str(charts.bar_svg(-5))
    assert "bar-prev" in str(charts.bar_svg(50, 20)) and "bar-prev" not in str(charts.bar_svg(50))


def test_radar_has_one_label_per_axis_marks_empty_axes_and_escapes_text():
    svg = str(charts.radar_svg(AXES))
    assert svg.count('class="radar-label"') == 5 and svg.count("radar-dot-empty") == 1 and "Nothing to assess" in svg
    assert "<b>" not in svg and "&lt;b&gt;" in svg
    assert "radar-prev" not in svg and "radar-prev" in str(charts.radar_svg(AXES, {"a": 10}))
    assert "Cookies 30 percent" in svg


def test_sparkline_skips_scans_without_a_score():
    svg = parse(charts.sparkline_svg([40, None, 70]))
    assert len(svg.findall(".//circle")) == 2
    assert str(charts.sparkline_svg([None])) == ""


def test_timeline_places_marks_in_their_lanes_and_shows_the_click():
    marks = [{"lane": "tracker", "t_ms": 500, "label": "A", "flag": True}, {"lane": "script_cookie", "t_ms": 900, "label": "<script>", "flag": True},
             {"lane": "storage", "t_ms": 1500, "label": "k", "flag": False}]
    svg = str(charts.timeline_svg(marks, 4000, 2000, "You click Accept", 700))
    assert svg.count("<title>") == 3 and "tl-click" in svg and "You click Accept" in svg and "page loaded" in svg
    assert "<script>" not in svg and "&lt;script&gt;" in svg
    assert "tl-click" not in str(charts.timeline_svg(marks, 4000, None, "", None))
    assert "Tracker requests: 1" in svg
