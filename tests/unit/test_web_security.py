import socket

import pytest

from ndpa.web.security import check_target, normalise_url, same_origin


def resolver(*addresses):
    def resolve(host, port, type=None):  # noqa: A002
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]
    return resolve


def broken(host, port, type=None):  # noqa: A002
    raise socket.gaierror("no such host")


def test_a_missing_scheme_is_added_and_existing_ones_are_kept():
    assert normalise_url("  www.example.com.ng ") == "https://www.example.com.ng"
    assert normalise_url("http://example.ng/a") == "http://example.ng/a"
    assert normalise_url("") == ""


def test_a_public_site_is_allowed():
    assert check_target("https://www.example.com.ng/", resolver=resolver("93.184.216.34")) is None
    assert check_target("http://93.184.216.34/") is None


@pytest.mark.parametrize("url", [
    "https://localhost/", "http://127.0.0.1:8000/", "http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.0.9/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://0.0.0.0/",
    "https://printer.local/", "https://intranet.internal/", "https://x.localhost/",
])
def test_private_and_local_addresses_are_refused(url):
    assert "private or local" in check_target(url, resolver=resolver("93.184.216.34"))


def test_a_name_that_resolves_to_a_private_address_is_refused_even_if_one_address_is_public():
    assert "private or local" in check_target("https://sneaky.example/", resolver=resolver("93.184.216.34", "10.1.2.3"))


@pytest.mark.parametrize("url,fragment", [
    ("", "address of a website"), ("ftp://example.ng/", "http://"), ("https://user:pass@example.ng/", "user name"),
    ("https:///path", "valid"), ("https://" + "a" * 2100 + ".ng", "address of a website"),
    ("https://intranet/", "full website address"),
])
def test_malformed_addresses_get_a_helpful_message(url, fragment):
    assert fragment in check_target(url, resolver=resolver("93.184.216.34"))


def test_an_unknown_website_says_so():
    assert "could not be found" in check_target("https://no-such-site.ng/", resolver=broken)


def test_private_targets_can_be_allowed_for_tests_only():
    assert check_target("http://127.0.0.1:8000/", allow_private=True) is None
    assert check_target("ftp://127.0.0.1/", allow_private=True) is not None  # scheme is still checked


def test_same_origin():
    assert same_origin(None, "localhost:8000")
    assert same_origin("http://localhost:8000", "localhost:8000")
    assert not same_origin("https://evil.example", "localhost:8000")
    assert not same_origin("http://localhost:8000", None)
    assert not same_origin("null", "localhost:8000")  # "null" on its own proves nothing


def test_the_browsers_own_statement_of_where_a_request_came_from_is_trusted():
    assert same_origin("null", "localhost:8000", "same-origin")  # a browser that hides the Origin still says same-origin
    assert same_origin(None, "localhost:8000", "none")  # typed into the address bar
    assert not same_origin("http://localhost:8000", "localhost:8000", "cross-site")  # cannot be argued with
    assert not same_origin(None, "localhost:8000", "same-site")
