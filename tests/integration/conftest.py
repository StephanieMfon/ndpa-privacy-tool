import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SITE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "site"
BLOCK_PAGE = (b"<html><body><h1>Access denied</h1>"
              b"<p>This request was blocked by our security service. Incident ID: 123</p></body></html>")


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/blocked"):
            self.send_response(403)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(BLOCK_PAGE)))
            self.end_headers()
            self.wfile.write(BLOCK_PAGE)
            return
        super().do_GET()

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


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class _BlockAll(_Quiet):
    def do_GET(self):
        self.send_response(403)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(BLOCK_PAGE)))
        self.end_headers()
        self.wfile.write(BLOCK_PAGE)


@pytest.fixture
def make_site(tmp_path_factory):
    """Factory: make_site({"index.html": "<html>...", "privacy/index.html": "..."}) -> base URL."""
    servers = []

    def make(files: dict, block: bool = False) -> str:
        root = tmp_path_factory.mktemp("site")
        for rel, html in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html, encoding="utf-8")
        handler = _BlockAll if block else _Quiet
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(root)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield make
    for server in servers:
        server.shutdown()
