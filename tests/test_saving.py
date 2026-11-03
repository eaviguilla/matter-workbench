"""Saving a transcript: it is all or nothing, it survives the server being stopped and started again (including a
kill), an open page still saves after a restart, and a repeated paste is recognised however the spacing differs."""
import html
import http.cookiejar
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import workflow as wf
from app.store import Busy, Store
from app.scrub.ner import NerModel
from app.web import create_app, security
from tests.fake_ner import FakeBackend
from tests.webhelp import BASE, Session, make_app, review_form, saved_tx

ROOT = Path(__file__).resolve().parent.parent
CALL = "Ahmed Khan: Hello.\nPat Nguyen: This is Pat Nguyen, write to pat.nguyen@example.com.\n"


def ner():
    return NerModel(backend_factory=lambda: FakeBackend({}))


def start(web, text=CALL, day="2026-03-10", cid=None):
    """The review page for a pasted call, for a new client when cid is None."""
    return web.post(f"/clients/{cid}/intake" if cid else "/intake", {"text": text, "call_date": day})


def save(web, text=CALL, day="2026-03-10", cid=None):
    """Paste, review (scrub every flag) and save. Returns (client id, transcript id)."""
    r = start(web, text, day, cid)
    action = re.search(r'action="(/clients/([^/"]+))/intake/save"', r.text)
    r = web.post(action.group(1) + "/intake/save", review_form(r.text), follow_redirects=False)
    return action.group(2), saved_tx(r)


def new_client(web, name="Pat"):
    return web.post("/clients", {"first_name": name}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]


def reopen(tmp_path) -> Store:
    return Store.open(tmp_path / "data", env={}, home=tmp_path / "home")


# ---- all or nothing -------------------------------------------------------------------------------

def test_a_failed_save_leaves_no_half_saved_call(tmp_path, monkeypatch):
    s = reopen_new(tmp_path)
    cid = s.create_client("Pat", pending=True)
    decisions = flag_decisions(s, cid)

    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(s, "save_registry", boom)
    with pytest.raises(RuntimeError):
        wf.save_transcript(s, cid, CALL, date(2026, 3, 10), ner(), wf.Settings(), decisions)
    monkeypatch.undo()
    assert s.list_transcripts(cid) == []                        # no draft call without its registry
    assert s.get_client(cid)["pending"] == 1                    # still cleaned up as an abandoned review
    tx = wf.save_transcript(s, cid, CALL, date(2026, 3, 10), ner(), wf.Settings(), decisions)   # the retry works
    assert s.get_transcript(tx)["status"] == "reviewed"
    assert s.load_registry(cid).entities
    assert [c["id"] for c in s.list_clients()] == [cid]


def test_a_failed_copy_records_no_message(tmp_path, monkeypatch):
    s = reopen_new(tmp_path)
    cid = s.create_client("Pat")
    tx = wf.save_transcript(s, cid, CALL, date(2026, 3, 10), ner(), wf.Settings(), flag_decisions(s, cid))

    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(s, "set_transcript_status", boom)
    with pytest.raises(RuntimeError):
        wf.copy_for_claude(s, cid, tx, ["clio-note"])
    monkeypatch.undo()
    assert s.list_messages(cid) == [] and s.get_transcript(tx)["status"] == "reviewed"


def test_a_save_does_not_hold_the_write_lock_while_it_scrubs(tmp_path, monkeypatch):
    """Scrubbing a long paste takes many seconds. The connector is another process and must not be refused meanwhile."""
    s = reopen_new(tmp_path)
    cid = s.create_client("Pat")
    decisions = flag_decisions(s, cid)
    real = wf.run_intake
    seen = []

    def spy(*a, **k):
        out = real(*a, **k)
        other = Store.open(tmp_path / "data", env={}, home=tmp_path / "home", lock_timeout=0)
        try:
            with other.transaction():
                seen.append("free")
        except Busy:
            seen.append("locked")
        return out
    monkeypatch.setattr(wf, "run_intake", spy)
    wf.save_transcript(s, cid, CALL, date(2026, 3, 10), ner(), wf.Settings(), decisions)
    assert seen == ["free"]


def test_a_registry_change_made_during_a_save_is_not_overwritten(tmp_path, monkeypatch):
    """Another copy of the app writes the registry while this save is scrubbing. Both changes must survive."""
    s = reopen_new(tmp_path)
    cid = s.create_client("Pat")
    decisions = flag_decisions(s, cid)
    real, calls = wf.run_intake, []

    def spy(*a, **k):
        out = real(*a, **k)
        calls.append(1)
        if len(calls) == 1:
            with reopen(tmp_path) as other:
                reg = other.load_registry(cid)
                reg.add_value("PERSON", "Zed Quill")
                other.save_registry(cid, reg)
        return out
    monkeypatch.setattr(wf, "run_intake", spy)
    tx = wf.save_transcript(s, cid, CALL, date(2026, 3, 10), ner(), wf.Settings(), decisions)
    assert len(calls) == 2                                      # scrubbed again against the changed registry
    values = {v for e in s.load_registry(cid).entities for v in e.forms.values()}
    assert "Zed Quill" in values and "Pat Nguyen" in values
    assert s.get_transcript(tx)["status"] == "reviewed"


def test_the_registry_fingerprint_changes_only_when_the_registry_is_written(tmp_path):
    s = reopen_new(tmp_path)
    cid, other = s.create_client("Pat"), s.create_client("Lena")
    empty = s.registry_fingerprint(cid)
    assert s.registry_fingerprint(cid) == empty
    reg = s.load_registry(cid)
    reg.add_value("PERSON", "Zed Quill")
    s.save_registry(cid, reg)
    assert s.registry_fingerprint(cid) != empty
    assert s.registry_fingerprint(other) == empty               # another client's registry is not part of it


def test_a_nested_transaction_that_fails_rolls_everything_back(tmp_path):
    s = reopen_new(tmp_path)
    with pytest.raises(ValueError):
        with s.transaction():
            cid = s.create_client("Pat")
            with s.transaction():
                s.add_transcript(cid, "text", date(2026, 3, 10))
            raise ValueError
    assert s.list_clients(include_archived=True) == [] and s._tx_ids() == []
    cid = s.create_client("Pat")                                # the store is usable again
    assert s.get_client(cid)


# ---- repeated and reordered calls -----------------------------------------------------------------

@pytest.mark.parametrize("variant", [CALL.replace("\n", "\r\n"), CALL + "\n\n", "\n" + CALL,
                                     CALL.replace("Hello.", "Hello.   ")], ids=["crlf", "trailing", "leading", "spaces"])
def test_the_same_call_pasted_again_with_other_spacing_is_one_call(tmp_path, variant):
    web = Session(make_app(tmp_path))
    cid, tx = save(web)
    assert save(web, variant, cid=cid) == (cid, tx)
    with reopen(tmp_path) as s:
        assert len(s.list_transcripts(cid)) == 1


def test_stored_text_uses_plain_line_breaks(tmp_path):
    web = Session(make_app(tmp_path))
    cid, tx = save(web, CALL.replace("\n", "\r\n"))
    with reopen(tmp_path) as s:
        assert "\r" not in s.get_transcript(tx)["scrubbed_text"]


def test_a_call_on_another_day_is_not_a_duplicate(tmp_path):
    web = Session(make_app(tmp_path))
    cid, tx = save(web)
    assert save(web, day="2026-03-11", cid=cid)[1] != tx


def test_same_day_calls_list_newest_first_past_nine(tmp_path):
    web = Session(make_app(tmp_path))
    cid, _ = save(web)
    for i in range(11):
        save(web, CALL + f"Ahmed Khan: Point {i}.\n", cid=cid)
    with reopen(tmp_path) as s:
        assert [t["id"][-2:].lstrip("-") for t in s.list_transcripts(cid)] == [str(n) for n in range(12, 0, -1)]


def test_saving_a_call_for_an_archived_client_brings_them_back(tmp_path):
    web = Session(make_app(tmp_path))
    cid, _ = save(web)
    web.post(f"/clients/{cid}/archive")
    with reopen(tmp_path) as s:
        assert [c["id"] for c in s.list_clients()] == []
    save(web, day="2026-03-12", cid=cid)
    with reopen(tmp_path) as s:
        assert [c["id"] for c in s.list_clients()] == [cid]


def test_pasting_a_saved_call_again_for_an_archived_client_still_brings_them_back(tmp_path):
    web = Session(make_app(tmp_path))
    cid, tx = save(web)
    web.post(f"/clients/{cid}/archive")
    assert save(web, cid=cid) == (cid, tx)
    with reopen(tmp_path) as s:
        assert [c["id"] for c in s.list_clients()] == [cid]


def test_a_long_paste_in_a_wide_script_is_not_refused_by_the_body_cap(tmp_path):
    """A paste the app accepts can post as far more bytes than characters. Under the old 1 MB cap this was a 413."""
    text = "Ahmed Khan: Hi.\nPat Nguyen: " + "これは長い通話の記録です。" * 10000 + "\n"
    assert len(text) < wf.MAX_PASTE and len(urllib.parse.urlencode({"text": text})) > 1_000_000
    web = Session(make_app(tmp_path))
    r = start(web, text, cid=new_client(web))
    assert r.status_code == 200 and "intake/save" in r.text


def test_the_body_cap_covers_the_largest_paste_the_app_accepts():
    assert security.MAX_BODY >= wf.MAX_PASTE * 12            # four-byte characters, each posted as 12 bytes


def test_a_call_with_hundreds_of_flagged_words_saves(tmp_path):
    """The review form posts three fields per flag. Starlette's default of 1000 fields refused it past about 330."""
    web = Session(make_app(tmp_path))
    cid = new_client(web)
    words = [f"Zq{chr(97 + i // 26 ** 2 % 26)}{chr(97 + i // 26 % 26)}{chr(97 + i % 26)}x" for i in range(450)]
    text = "Ahmed Khan: Hi.\nPat Nguyen: " + " ".join(f"We met {w} today." for w in words) + "\n"
    r = start(web, text, cid=cid)
    form = review_form(r.text)
    assert int(form["n_flags"]) > 340
    resp = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    assert resp.status_code == 303, resp.text[:200]
    with reopen(tmp_path) as s:
        assert len(s.list_review_decisions(saved_tx(resp))) > 340


# ---- the CSRF secret ------------------------------------------------------------------------------

def test_the_form_secret_survives_a_restart(tmp_path):
    s = reopen_new(tmp_path)
    assert s.form_secret() == reopen(tmp_path).form_secret() and len(s.form_secret()) == 32


# ---- restart, in process --------------------------------------------------------------------------

def restart(tmp_path, old: Session) -> Session:
    """A second app on the same folder, the same browser tab (cookies and page token kept)."""
    app = create_app(tmp_path / "data", env={}, home=tmp_path / "home", ner=ner())
    web = Session(app)
    web.c.cookies.clear()
    for cookie in old.c.cookies.jar:
        web.c.cookies.set(cookie.name, cookie.value)
    return web


def test_a_review_page_left_open_still_saves_after_a_restart(tmp_path):
    web = Session(make_app(tmp_path))
    r = start(web)                                              # a new client, pending until this is saved
    action = re.search(r'action="(/clients/[^/"]+)/intake/save"', r.text).group(1)
    form, token = review_form(r.text), web.token
    again = restart(tmp_path, web)
    again.token = token                                         # the old page still carries its old token
    resp = again.post(action + "/intake/save", form, follow_redirects=False)
    assert resp.status_code == 303, resp.text[:200]
    with reopen(tmp_path) as s:
        assert len(s.list_transcripts(action.split("/")[-1])) == 1
        assert [c["id"] for c in s.list_clients()] == [action.split("/")[-1]]


def test_everything_the_user_saved_is_there_after_a_restart(tmp_path):
    web = Session(make_app(tmp_path))
    cid, tx1 = save(web)
    _, tx2 = save(web, "Ahmed Khan: Again.\nPat Nguyen: Add Lena Ortiz, 9 Birch Lane, Dayton.\n", "2026-03-11", cid)
    web.post_json(f"/transcripts/{tx2}/copy", {"outputs": ["clio-note"]})
    web.post(f"/clients/{cid}/import/save", {"content": "Hello [PERSON_3], we have [EMAIL_1].", "tx_id": tx2, "output": "clio-note"})
    web.post(f"/clients/{cid}/import/save", {"content": "Second reply for [PERSON_3].", "tx_id": tx2, "output": "clio-note"})
    web.post(f"/clients/{cid}/import/save", {"content": "Running summary of [PERSON_3].", "kind": "summary"})
    web.post(f"/clients/{cid}/rename", {"first_name": "Patricia"})
    web.post(f"/clients/{cid}/options", {"types": ["PERSON", "EMAIL"], "first_names": "keep"})
    web.post("/settings", {"threshold": "0.4", "idle_minutes": "7"})
    web.post(f"/clients/{cid}/registry/add", {"type": "PERSON", "value": "Zed Quill"})
    before = snapshot(tmp_path, web)

    again = restart(tmp_path, web)
    again.get("/settings")
    assert snapshot(tmp_path, again) == before
    assert before["transcripts"] == [(tx2, "copied"), (tx1, "reviewed")]
    assert before["settings"] == ("0.4", "7", "PERSON,EMAIL", "keep")     # so a failed POST cannot pass as "unchanged"
    assert [o[0] for o in before["outputs"]] == [1, 2] and before["messages"] == ["transcript", "summary"]
    assert "Patricia" in again.get(f"/clients/{cid}").text
    page = again.get(f"/transcripts/{tx2}?clio-note=1").text
    assert "pat.nguyen@example.com" in page                     # the reply is rehydrated from the stored registry
    assert "Zed Quill" in again.get(f"/clients/{cid}/registry").text
    assert 'value="7"' in again.get("/settings").text


def snapshot(tmp_path, web):
    with reopen(tmp_path) as s:
        cid = s.list_clients(include_archived=True)[0]["id"]
        return {
            "client": (cid, s.get_client(cid)["first_name"], s.get_client(cid)["pending"]),
            "transcripts": [(t["id"], t["status"]) for t in s.list_transcripts(cid)],
            "texts": [t["scrubbed_text"] for t in s.list_transcripts(cid)],
            "outputs": [(o["version"], o["content"]) for t in s.list_transcripts(cid) for o in s.list_outputs(t["id"], "clio-note")],
            "messages": [m["kind"] for m in s.list_messages(cid)],
            "registry": sorted((e.type, e.n, tuple(e.forms.items())) for e in s.load_registry(cid).entities),
            "settings": (s.get_setting("threshold"), s.get_setting("idle_minutes"),
                         s.get_setting(f"client.{cid}.types"), s.get_setting(f"client.{cid}.first_names")),
        }


# ---- restart, a real server process ---------------------------------------------------------------

SERVER = """
import sys
from pathlib import Path
sys.path.insert(0, {root!r})
from app.__main__ import serve
from app.scrub.ner import NerModel
from app.web import create_app
from tests.fake_ner import FakeBackend
folder, port = Path(sys.argv[1]), int(sys.argv[2])
(folder / "home").mkdir(exist_ok=True)
app = create_app(folder / "data", env={{}}, home=folder / "home",
                 ner=NerModel(backend_factory=lambda: FakeBackend({{}})))
sys.exit(serve(app, port))
"""


class Browser:
    """A tiny HTTP client that keeps cookies and the page token, like a tab that stays open."""

    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.jar = http.cookiejar.CookieJar()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)
        self.token = None

    def go(self, path, data=None):
        if data is not None:
            body = urllib.parse.urlencode({"csrf": self.token, **data}).encode()
        else:
            body = None
        try:
            resp = self.opener.open(urllib.request.Request(self.base + path, data=body, headers={"Accept": "text/html"}))
        except urllib.error.HTTPError as e:
            resp = e
        text = resp.read().decode("utf-8")
        m = re.search(r'name="csrf" content="([0-9a-f]+)"', text)
        self.token = m.group(1) if m else self.token
        return resp.status, resp.headers.get("location"), text


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_server(folder, port):
    proc = subprocess.Popen([sys.executable, "-c", SERVER.format(root=str(ROOT)), str(folder), str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc
        except OSError:
            if proc.poll() is not None:
                raise AssertionError(proc.stderr.read())
            time.sleep(0.1)
    proc.kill()
    raise AssertionError("the server did not start")


def review_fields(page):
    """What a browser would post from a review page, with every flag scrubbed."""
    form = {k: html.unescape(v) for k, v in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', page)
            if k != "csrf"}
    form["text"] = html.unescape(re.search(r'<textarea name="text"[^>]*>(.*?)</textarea>', page, re.S).group(1))
    for k in [k for k in form if re.fullmatch(r"w\d+", k)]:
        form["d" + k[1:]] = "scrub"
    return re.search(r'action="(/clients/([^/"]+))/intake/save"', page).groups(), form


@pytest.mark.parametrize("how", ["stopped", "killed"])
@pytest.mark.skipif(os.name != "posix", reason="signals are tested on macOS and Linux")
def test_a_real_server_keeps_a_saved_call_after_it_stops_and_starts_again(tmp_path, how):
    stop = signal.SIGINT if how == "stopped" else signal.SIGKILL      # SIGKILL does not exist on Windows
    folder = tmp_path / "run"
    folder.mkdir()
    port = free_port()
    proc = run_server(folder, port)
    try:
        b = Browser(port)
        b.go("/settings")
        (action, cid), form = review_fields(b.go("/intake", {"text": CALL, "call_date": "2026-03-10"})[2])
        # a second review page stays open across the restart
        (open_action, _), open_form = review_fields(
            b.go("/intake", {"text": CALL.replace("Hello.", "this one stayed open."), "call_date": "2026-03-11"})[2])
        open_token = b.token
        status, loc, _ = b.go(action + "/intake/save", form)
        assert status == 303
        tx = loc.split("saved=")[1]
        assert b.go(f"/transcripts/{tx}/copy", {"output": "clio-note"})[0] == 200
    finally:
        proc.send_signal(stop)
        proc.wait(timeout=20)

    proc = run_server(folder, port)
    try:
        after = Browser(port)
        after.go("/settings")
        status, _, page = after.go(f"/clients/{cid}?tx={tx}&view=transcript")
        assert status == 200 and '<mark class="tag tag-email">pat.nguyen@example.com</mark>' in page
        assert "Copied, waiting for Claude" in after.go(f"/clients/{cid}")[2]
        assert "pat.nguyen@example.com" in after.go(f"/clients/{cid}/registry")[2]
        for cookie in b.jar:                                    # the tab that was open before the restart
            after.jar.set_cookie(cookie)
        after.token = open_token
        status, loc, body = after.go(open_action + "/intake/save", open_form)
        assert status == 303, body[:300]
        assert "this one stayed open" in after.go(loc)[2]
    finally:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=20)


# ---- helpers --------------------------------------------------------------------------------------

def reopen_new(tmp_path) -> Store:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return Store.open(tmp_path / "data", env={}, home=home)


def flag_decisions(store, cid):
    """A decision for every flag the call raises, so the review is complete."""
    groups = wf.run_intake(store, cid, CALL, ner(), wf.Settings()).groups
    return [{"text": g.text, "decision": "scrub", "spans": []} for g in groups]


# ---- dates are the user's own ---------------------------------------------------------------------

@pytest.fixture
def auckland(monkeypatch):
    """A clock zone far ahead of UTC, so the local date and the UTC date differ."""
    import time
    if not hasattr(time, "tzset"):
        pytest.skip("needs time.tzset")
    monkeypatch.setenv("TZ", "Pacific/Auckland")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_client_ids_and_the_sidebar_use_the_local_date(tmp_path, auckland):
    from datetime import datetime, timezone
    late_utc = datetime(2026, 11, 2, 21, 52, tzinfo=timezone.utc)               # already the 3rd in Auckland
    home = tmp_path / "home"
    home.mkdir()
    s = Store.open(tmp_path / "data", env={}, home=home, clock=lambda: late_utc)
    cid = s.create_client("Pat")
    assert cid == "Pat-20261103-1"
    assert wf.local_day("2026-11-02T21:52:18+00:00") == "2026-11-03"
    assert wf.local_time("2026-11-02T21:52:18+00:00") == "2026-11-03 10:52"
    assert wf.local_time("not a time") == "not a time" and wf.local_day("") == ""
    s.close()
