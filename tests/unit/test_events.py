import pytest

from ndpa.capture.events import (
    EventLog,
    clean_url,
    parse_cookie_assignment,
    set_cookie_names,
    value_hash,
)


def test_clock_counts_milliseconds_from_start():
    now = [100.0]
    log = EventLog(clock=lambda: now[0])
    log.start()
    now[0] = 100.25
    assert log.add("request").t_ms == 250
    now[0] = 101.0
    assert log.add("response").t_ms == 1000
    assert [e.kind for e in log.events] == ["request", "response"]


def test_clock_must_be_started():
    with pytest.raises(RuntimeError):
        EventLog().add("request")


def test_clean_url_drops_values_keeps_key_names():
    url, keys = clean_url("https://t.example/collect?uid=secret&page=home&uid=again#frag")
    assert url == "https://t.example/collect"
    assert keys == ["page", "uid"]


def test_clean_url_data_urls_are_not_stored():
    assert clean_url("data:image/png;base64,AAAA") == ("data:", [])


def test_set_cookie_names_handles_several_cookies():
    raw = "a=1; Path=/; Secure\nb=2; HttpOnly\n"
    assert set_cookie_names(raw) == ["a", "b"]
    assert set_cookie_names(None) == []


def test_parse_cookie_assignment():
    assert parse_cookie_assignment("_ga=GA1.2.3; path=/; max-age=63072000") == ("_ga", "GA1.2.3")
    assert parse_cookie_assignment("flag") == ("flag", "")


def test_value_hash_is_short_and_stable():
    assert value_hash("abc") == value_hash("abc") and len(value_hash("abc")) == 12
    assert value_hash("abc") != value_hash("abd")
