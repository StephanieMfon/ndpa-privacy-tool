import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SITE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "site"


class _Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        if self.path.startswith("/server_cookie"):
            self.send_header("Set-Cookie", "srv_id=xyz; Path=/")
        super().end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def site():
    """Base URL of a local fixture website (http://127.0.0.1:<port>)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Handler, directory=str(SITE_DIR)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
