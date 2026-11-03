"""Host check, CSRF, CSP, escaping, logging and the no-network rule."""
import logging
import re
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.scrub.evaluate import load_annotated
from app.web import security
from tests.webhelp import BASE, FIXTURES, Session, fixture_text, make_app, review_form, saved_tx

APP_DIR = Path(__file__).resolve().parent.parent / "app"


@pytest.fixture
def web(tmp_path):
    return Session(make_app(tmp_path))


def seeded(web):
    cid = web.post("/clients", {"first_name": "Maria"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    r = web.post(f"/clients/{cid}/intake", {"text": fixture_text(1), "call_date": "2026-11-02"})
    r = web.post(f"/clients/{cid}/intake/save", review_form(r.text), follow_redirects=False)
    return cid, saved_tx(r)


# ---- host header ----------------------------------------------------------------------------

@pytest.mark.parametrize("host,ok", [("127.0.0.1:8765", True), ("localhost:8765", True), ("localhost", True),
                                     ("[::1]:8765", True), ("evil.example", False), ("127.0.0.1.evil.example", False),
                                     ("localhost.evil.example:8765", False), ("192.168.1.5:8765", False)])
def test_host_header(tmp_path, host, ok):
    c = TestClient(make_app(tmp_path), base_url="http://127.0.0.1:8765")
    r = c.get("/settings", headers={"Host": host})
    assert (r.status_code == 200) is ok
    assert ok or r.status_code == 403


def test_the_server_binds_to_loopback_only():
    src = (APP_DIR / "__main__.py").read_text()
    assert 'HOST = "127.0.0.1"' in src and "host=HOST" in src and "0.0.0.0" not in src


# ---- csrf -----------------------------------------------------------------------------------

def sample_path(path, cid, tx):
    return (path.replace("{cid}", cid).replace("{tx_id}", tx).replace("{action}", "edit"))


def test_every_state_changing_route_rejects_a_missing_or_wrong_token(web, tmp_path):
    cid, tx = seeded(web)
    posts = [r for r in web.c.app.state.api_router.routes if "POST" in getattr(r, "methods", ())]
    assert len(posts) >= 12
    other = Session(make_app(tmp_path / "other"))
    for route in posts:
        url = sample_path(route.path, cid, tx)
        assert web.c.post(url, data={}).status_code == 403, route.path
        assert web.c.post(url, data={"csrf": "0" * 64}).status_code == 403, route.path
        assert web.c.post(url, json={}, headers={"X-CSRF-Token": other.token}).status_code == 403, route.path


def test_a_token_from_another_session_is_rejected(web, tmp_path):
    a, b = web, Session(make_app(tmp_path / "b"))
    r = a.c.post("/clients", data={"first_name": "Zed", "csrf": b.token})
    assert r.status_code == 403
    assert web.post("/clients", {"first_name": "Zed"}, follow_redirects=False).status_code == 303


def _audit(web):
    from app.store import Store
    app = web.c.app
    with Store.open(app.state.data_dir, env={}, home=app.state.home) as s:
        return [tuple(r) for r in s.list_audit()], len(s.list_messages(next(iter(s.list_clients()))["id"]))


def test_get_requests_change_nothing(web):
    cid, tx = seeded(web)
    before = _audit(web)
    for url in ("/", f"/clients/{cid}", f"/clients/{cid}/registry", f"/transcripts/{tx}", "/settings",
                f"/clients/{cid}/outgoing", f"/clients/{cid}/import", f"/clients/{cid}/intake"):
        assert web.get(url).status_code == 200
    assert _audit(web) == before


def test_cookie_flags(tmp_path):
    c = TestClient(make_app(tmp_path), base_url=BASE)
    cookie = c.get("/settings").headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


# ---- headers, inline code, escaping ---------------------------------------------------------

def test_security_headers_on_pages_and_static_files(web):
    for url in ("/settings", "/static/app.js", "/static/style.css"):
        h = web.get(url).headers
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp and "script-src 'self'" in csp and "unsafe" not in csp
        assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"
        assert h["cache-control"] == "no-store" and h["x-frame-options"] == "DENY"


def test_no_inline_scripts_styles_or_handlers_in_templates():
    for f in (APP_DIR / "web" / "templates").glob("*.html"):
        src = f.read_text()
        assert not re.search(r"<script(?![^>]*\bsrc=)", src), f.name
        assert not re.search(r"\sstyle\s*=", src), f.name
        assert not re.search(r"\son[a-z]+\s*=", src), f"{f.name}: inline handler"
        assert "javascript:" not in src and "<style" not in src and "|safe" not in src and "autoescape false" not in src, f.name


def test_user_text_is_escaped_everywhere(web):
    evil = "<img src=x onerror=alert(1)>"
    cid = web.post("/clients", {"first_name": evil}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    assert cid.startswith("Imgsrcxonerroralert-") or "<" not in cid
    for url in ("/", f"/clients/{cid}", f"/clients/{cid}/registry", "/settings"):
        assert "<img src=x" not in web.get(url).text, url
    web.post(f"/clients/{cid}/registry/add", {"type": "PERSON", "value": "<script>alert(1)</script>"})
    page = web.get(f"/clients/{cid}/registry").text
    assert "<script>alert" not in page and "&lt;script&gt;alert" in page


def test_a_real_value_with_markup_is_shown_as_text_in_rehydrated_output(web):
    cid, tx = seeded(web)
    web.post(f"/clients/{cid}/registry/add", {"type": "ADDRESS", "value": "1 <b>Bold</b> Street"})
    reg = web.get(f"/clients/{cid}/registry").text
    n = max(int(x) for x in re.findall(r"\[ADDRESS_(\d+)\]", reg))
    chk = web.post(f"/clients/{cid}/import", {"text": f"[CLIENT: {cid} | TX: {tx}]\nGo to [ADDRESS_{n}]."})
    assert "<b>Bold</b>" not in chk.text and "&lt;b&gt;Bold&lt;/b&gt;" in chk.text


def test_no_docs_or_schema_endpoints(web):
    for url in ("/docs", "/redoc", "/openapi.json"):
        assert web.get(url).status_code == 404


def test_large_requests_are_refused(web):
    r = web.c.post("/clients", content=b"x" * (security.MAX_BODY + 1), headers={"content-type": "text/plain", "X-CSRF-Token": web.token})
    assert r.status_code == 413


# ---- logs, errors, network ------------------------------------------------------------------

def real_values():
    p = sorted(FIXTURES.glob("*.ann.txt"))[0]
    ann = load_annotated(p.stem, p.read_text(encoding="utf-8"))
    vals = {ann.text[s:e] for s, e, t, _ in ann.spans if t in ("PERSON", "EMAIL", "ADDRESS") and len(ann.text[s:e]) > 3}
    return (vals | {"Maria Lopez", "Whitaker"}) - {"Maria"}      # the client's first name is in the client ID by design


def run_everything(web):
    cid, tx = seeded(web)
    web.post_json(f"/transcripts/{tx}/copy", {"outputs": ["clio-note", "clio-form-note"]})
    web.post(f"/clients/{cid}/import", {"text": f"[CLIENT: {cid} | TX: {tx}]\nHello [PERSON_1] and Maria Lopez"})
    web.post_json(f"/clients/{cid}/outgoing/copy", {"text": "Maria Lopez moved to 9 Elm Road", "kind": "comment",
                                                     "tx_id": tx, "confirm": "1"})
    web.post(f"/clients/{cid}/export")
    return cid, tx


def test_logs_hold_no_transcript_text_or_real_values(web, caplog):
    caplog.set_level(logging.DEBUG)
    cid, tx = run_everything(web)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "matterworkbench" in {r.name for r in caplog.records}, "the app should log something"
    for v in real_values():
        assert v not in text, v


def test_an_unexpected_error_logs_only_its_type(tmp_path, caplog, monkeypatch):
    web = Session(make_app(tmp_path))
    cid, tx = seeded(web)
    from app import workflow
    def boom(*a, **k):
        raise ValueError("secret value Maria Lopez 12 Oak Street")
    monkeypatch.setattr(workflow, "check_import", boom)
    caplog.set_level(logging.DEBUG)
    r = web.post(f"/clients/{cid}/import", {"text": "x"})
    assert r.status_code == 500 and "Maria" not in r.text
    log = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "ValueError" in log and "secret value" not in log and "Oak Street" not in log and "Lopez" not in log


def test_the_app_works_with_the_network_blocked(tmp_path, monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("network access attempted")
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    run_everything(Session(make_app(tmp_path)))


def test_app_code_has_no_network_libraries_and_no_remote_assets():
    banned = re.compile(r"^\s*(?:import|from)\s+(requests|urllib\.request|urllib3|http\.client|httpx|aiohttp|socket|"
                        r"smtplib|ftplib|websockets?)\b", re.M)
    for f in APP_DIR.rglob("*.py"):
        assert not banned.search(f.read_text()), f
    for f in [*(APP_DIR / "web").rglob("*.html"), *(APP_DIR / "web").rglob("*.css"), *(APP_DIR / "web").rglob("*.js"),
              *(APP_DIR / "web").rglob("*.svg")]:
        urls = [u for u in re.findall(r"(?:https?:)?//[A-Za-z0-9.-]+\.[a-z]{2,}", f.read_text())
                if "w3.org" not in u]
        assert urls == [], (f, urls)


def test_demo_mode_uses_a_temp_folder(tmp_path):
    from app.demo import create_demo_app
    app = create_demo_app(model_dir=tmp_path / "no-model")
    c = TestClient(app, base_url=BASE)
    assert c.get("/").status_code == 200 and "Maria" in c.get("/").text
    assert "matter-workbench-demo-" in str(app.state.data_dir)


def test_cross_site_requests_are_refused_even_with_a_valid_host_and_cookie(web):
    cid, tx = seeded(web)
    for site in ("cross-site", "same-site"):
        assert web.c.get("/", headers={"Sec-Fetch-Site": site}).status_code == 403
        assert web.c.post(f"/clients/{cid}/export", data={"csrf": web.token}, headers={"Sec-Fetch-Site": site}).status_code == 403
    for site in ("same-origin", "none"):
        assert web.c.get("/settings", headers={"Sec-Fetch-Site": site}).status_code == 200
    assert web.get(f"/clients/{cid}/export.md").status_code in (404, 405)       # no GET route can export
    assert web.get(f"/clients/{cid}/export").status_code == 405
