import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "office"))
import pytest

FORM = """<html><body><h1>Apply: ML Engineer</h1><form>
<label for="fn">First name</label><input id="fn" name="first_name" required>
<label for="em">Email</label><input id="em" type="email" name="email">
<label>Why us?<textarea name="why"></textarea></label>
<label for="loc">Location</label><select id="loc" name="location"><option>London</option><option>Remote</option></select>
<label for="cv">CV</label><input id="cv" type="file" name="resume">
<button type="submit">Submit application</button></form></body></html>"""


def test_host_policy():
    import browser
    assert browser.host_ok("https://boards.greenhouse.io/acme/jobs/1")
    assert browser.host_ok("https://acme.com/careers")
    assert not browser.host_ok("https://www.linkedin.com/jobs/view/1") and not browser.host_ok("https://uk.indeed.com/x")


def test_read_page_reports_text_and_fields(tmp_path):
    import browser
    f = tmp_path / "form.html"; f.write_text(FORM)
    r = browser.read_page(f.as_uri(), 2000)
    assert "Apply: ML Engineer" in r["text"]
    names = {x["name"]: x for x in r["fields"]}
    assert {"first_name", "email", "why", "location", "resume"} <= set(names)
    assert names["first_name"]["required"] and names["first_name"]["label"] == "First name"
    assert names["location"]["options"] == ["London", "Remote"] and names["resume"]["type"] == "file"


def test_prefill_fills_without_submitting(tmp_path, monkeypatch):
    """Headless stand-in for the visible browser: same fill logic, screenshot, nothing clicked."""
    import browser
    from playwright.sync_api import sync_playwright
    f = tmp_path / "form.html"; f.write_text(FORM); cv = tmp_path / "cv.pdf"; cv.write_bytes(b"%PDF-1.4 test")
    submitted = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        monkeypatch.setattr(browser, "ensure_visible_browser", lambda: "unused")
        class FakePW:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            class chromium:
                @staticmethod
                def connect_over_cdp(endpoint): return b
        monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: FakePW())
        monkeypatch.setattr(browser, "WORKSPACE", tmp_path)
        ctx = b.new_context(); b.contexts  # ensure a context exists
        r = browser.prefill(f.as_uri(), {"First name": "Pribin", "email": "p@example.com", "Why us?": "I built an agent office.", "Location": "London",
                                         "CV": "attach", "Submit application": "x"}, tmp_path / "shots" / "form.png", cv)
    assert (tmp_path / "shots" / "form.png").exists()
    assert any(x.startswith("First name: Pribin") for x in r["filled"]) and any(x.startswith("email:") for x in r["filled"])
    assert any(x.startswith("Location: London") for x in r["filled"]) and any("cv.pdf" in x for x in r["filled"])
    assert any("refused (submit-like control)" in m for m in r["missed"]) and "Nothing was submitted" in r["note"]
