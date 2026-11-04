"""Small helpers for website addresses."""
import re
from urllib.parse import urlparse


def host_of(url: str) -> str:
    """The folder-safe host name used for evidence folders and scan history."""
    return re.sub(r"[^a-zA-Z0-9.\-]", "_", urlparse(url).netloc)
