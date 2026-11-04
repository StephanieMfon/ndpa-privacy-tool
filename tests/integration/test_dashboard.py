"""The dashboard end to end: a scan started from the web form runs in its own process with a real browser. Needs Chrome."""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ndpa.evidence import chain
from ndpa.storage import db
from ndpa.web.app import create_app
from ndpa.web.jobs import ScanManager, Settings

pytestmark = pytest.mark.browser


def wait_until_final(client, scan_id, timeout=300):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status = client.get(f"/api/scans/{scan_id}").json()["scan"]["status"]
        if status in db.FINAL_STATUSES:
            return status
        time.sleep(1)
    raise AssertionError("the scan did not finish in time")


def test_a_scan_started_from_the_form_runs_finishes_and_can_be_compared(site, tmp_path):
    settings = Settings(db_path=tmp_path / "t.db", evidence_root=tmp_path / "ev", log_dir=tmp_path / "logs", vantage="test lab",
                        headless=True, bundled_chromium=True, observe_s=1, allow_private_targets=True)
    with TestClient(create_app(settings, ScanManager(settings))) as client:
        url = f"{site}/banner_fake_reject.html"
        first = client.post("/scans", data={"url": url}, headers={"origin": "http://testserver"}, follow_redirects=False)
        assert first.status_code == 303 and first.headers["location"] == "/scans/1"
        assert wait_until_final(client, 1) == "done"

        api = client.get("/api/scans/1").json()
        assert api["score"]["weighted"] is not None and len(api["findings"]) == 17 and api["scan"]["vantage"] == "test lab"
        outcomes = {f["rule_id"]: f["outcome"] for f in api["findings"]}
        assert outcomes["CN-02"] == "non_compliant" and outcomes["CN-03"] == "compliant"  # the fake Reject still sets a cookie

        page = client.get("/scans/1").text
        assert "Fix first" in page and "In plain words" in page and "What a visitor sees" in page
        assert client.get("/scans/1/file/no_action/screenshot.png").headers["content-type"] == "image/png"
        timeline = client.get("/scans/1/timeline").text
        assert "Visit, then click Reject" in timeline and "tl-click" in timeline
        evidence = client.get("/scans/1/evidence").text
        folder = db.get_scan(db.connect(settings.db_path), 1)["folder"]
        assert "verify.py" in evidence and api["scan"]["manifest_hash"] in evidence
        assert chain.verify(Path(folder), expect=api["scan"]["manifest_hash"])[0] == []

        again = client.post("/scans", data={"url": url}, headers={"origin": "http://testserver"}, follow_redirects=False)
        assert again.headers["location"] == "/scans/2" and wait_until_final(client, 2) == "done"
        host = api["scan"]["host"]
        assert client.get(f"/history/{host}").text.count('name="pick"') == 2
        compare = client.get("/compare?a=1&b=2")
        assert compare.status_code == 200 and "Did the fixes work?" in compare.text
