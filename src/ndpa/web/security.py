"""Thin security for a tool that opens addresses typed by a user (decision D-23).

The scanner must not be usable to reach internal networks, and a web page the visitor happens to have open must not
be able to start scans on their behalf.
"""
import ipaddress
import socket
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048
BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa")
NOT_PUBLIC = "That address points to a private or local network, which this tool does not scan."


def normalise_url(raw: str) -> str:
    raw = (raw or "").strip()
    return f"https://{raw}" if raw and "://" not in raw else raw


def check_target(url: str, allow_private: bool = False, resolver=socket.getaddrinfo) -> str | None:
    """None if the address may be scanned, otherwise a message for the visitor."""
    if not url or len(url) > MAX_URL_LENGTH:
        return "Enter the address of a website, for example https://www.example.com.ng"
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        return "That address does not look valid."
    if parts.scheme not in ("http", "https"):
        return "Only http:// and https:// addresses can be scanned."
    if not host:
        return "That address does not look valid."
    if parts.username or parts.password:
        return "Addresses that contain a user name or password are not accepted."
    if allow_private:
        return None
    host = host.lower().rstrip(".")
    if host == "localhost" or host.endswith(BLOCKED_SUFFIXES):
        return NOT_PUBLIC
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        if "." not in host:
            return "Enter a full website address such as www.example.com.ng"
        try:
            infos = resolver(host, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError:
            return "That website could not be found. Check the spelling and try again."
        addresses = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    for address in addresses:
        address = getattr(address, "ipv4_mapped", None) or address
        if not address.is_global:
            return NOT_PUBLIC
    return None


def same_origin(origin: str | None, host: str | None, fetch_site: str | None = None) -> bool:
    """A form post must come from this site's own pages.

    Browsers state where a request came from in the Sec-Fetch-Site header, which a web page cannot forge, so it is
    trusted when present. Otherwise the Origin header is compared with the Host header. An Origin of "null" is never
    accepted on its own. Requests without either header are not from a browser (scripts, tests).
    """
    if fetch_site:
        return fetch_site in ("same-origin", "none")
    return origin is None or (host is not None and urlsplit(origin).netloc == host)
