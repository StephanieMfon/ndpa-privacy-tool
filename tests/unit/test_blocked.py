from ndpa.capture.blocked import detect_block, main_document

NORMAL = ("<html><head><title>Ministry</title></head><body>"
          + "<p>Welcome to the Federal Ministry of Example.</p>" * 4 + "</body></html>")

IMPERVA = ("<html><body><p>Access denied</p><h1>Error 15</h1><p>gtbank.com</p>"
           "<p>2026-10-23 08:45:29 UTC</p><h2>What happened?</h2>"
           "<p>This request was blocked by our security service</p>"
           "<p>Your IP: 102.90.79.95</p><p>Incident ID: 572000410413841898</p>"
           "<p>Powered by Imperva</p></body></html>")

CLOUDFLARE = ("<html><head><title>www.jumia.com.ng</title></head><body>"
              "<h1>www.jumia.com.ng</h1><h2>Performing security verification</h2>"
              "<p>This website uses a security service to protect against malicious bots. "
              "This page is displayed while the website verifies you are not a bot.</p>"
              "<p>Verify you are human</p><p>Ray ID: a4de638cd8922409</p></body></html>")


def _entry(status, headers=None):
    return {"response": {"status": status,
                         "headers": [{"name": k, "value": v} for k, v in (headers or {}).items()]}}


def test_imperva_page_is_blocked():
    v = detect_block(200, {}, IMPERVA)
    assert v.blocked and any(r.startswith("marker") for r in v.reasons)


def test_cloudflare_challenge_is_blocked():
    v = detect_block(200, {}, CLOUDFLARE)
    assert v.blocked and "marker: performing security verification" in v.reasons


def test_http_403_is_blocked():
    assert detect_block(403, {}, NORMAL).reasons == ["http_403"]


def test_http_429_is_blocked():
    assert detect_block(429, {}, NORMAL).blocked


def test_cloudflare_header_is_blocked():
    assert detect_block(200, {"CF-Mitigated": "challenge"}, NORMAL).blocked


def test_normal_page_is_not_blocked():
    v = detect_block(200, {"server": "nginx"}, NORMAL)
    assert not v.blocked and v.reasons == []


def test_marker_in_large_page_is_ignored():
    big = ("<html><body>" + "<p>Welcome to our bank and its services.</p>" * 200
           + "<p>Access denied for unauthorised users.</p></body></html>")
    assert not detect_block(200, {}, big).blocked


def test_marker_only_inside_script_is_ignored():
    page = ("<html><body><script>var s='performing security verification';</script>"
            + "<p>Welcome to the Federal Ministry of Example.</p>" * 4 + "</body></html>")
    assert not detect_block(200, {}, page).blocked


def test_empty_page_is_blocked():
    assert detect_block(200, {}, "<html><body></body></html>").reasons == ["empty_page"]


def test_main_document_skips_redirects():
    har = {"log": {"entries": [_entry(301), _entry(403, {"Server": "cloudflare"})]}}
    assert main_document(har) == (403, {"server": "cloudflare"})


def test_main_document_empty_har():
    assert main_document({"log": {"entries": []}}) == (None, {})
