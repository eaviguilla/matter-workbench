"""Clients made for an unsaved review stay hidden, and each client has its own scrub options."""
import re
from datetime import datetime, timezone

import pytest

from app import workflow as wf
from app.store import Store
from tests.webhelp import Session, fixture_text, make_app, review_form, saved_tx


@pytest.fixture
def web(tmp_path):
    return Session(make_app(tmp_path))


def store(tmp_path, **kw):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return Store.open(tmp_path / "data", env={}, home=home, **kw)


# ---- pending clients -------------------------------------------------------------------------

def test_a_pending_client_is_hidden_until_activated(tmp_path):
    with store(tmp_path) as s:
        cid = s.create_client("Tomas", pending=True)
        assert s.get_client(cid) is not None and s.list_clients() == []
        s.activate_client(cid)
        assert [c["id"] for c in s.list_clients()] == [cid]


def test_purge_removes_only_pending_clients_with_no_transcript(tmp_path):
    with store(tmp_path) as s:
        gone = s.create_client("Tomas", pending=True)
        kept = s.create_client("Maria", pending=True)
        s.add_transcript(kept, "text")
        visible = s.create_client("Zed")
        assert s.purge_pending() == 1
        assert s.get_client(gone) is None and s.get_client(kept) is not None and s.get_client(visible) is not None


def test_purge_leaves_a_recent_pending_client_alone(tmp_path):
    with store(tmp_path) as s:
        cid = s.create_client("Tomas", pending=True)
        assert s.purge_pending(older_than_minutes=60) == 0 and s.get_client(cid) is not None


def test_starting_the_app_removes_abandoned_clients(tmp_path):
    from app.web import create_app
    w = Session(make_app(tmp_path))
    w.post("/intake", {"text": fixture_text(1), "call_date": "2026-11-02"})
    ner = w.c.app.state.ner
    with Store.open(tmp_path / "data", env={}, home=tmp_path / "home") as s:
        cid = s._client_ids()[0]
        with s.transaction():
            s._edit(cid)["created_at"] = "2020-01-01T00:00:00+00:00"                        # abandoned long ago
    create_app(tmp_path / "data", env={}, home=tmp_path / "home", ner=ner)      # a restart
    with Store.open(tmp_path / "data", env={}, home=tmp_path / "home") as s:
        assert s._client_ids() == []



# ---- per-client scrub options ----------------------------------------------------------------

TEXT = "•\nDana Whitaker\n0:01\nHello.\n•\nTomas Beltran\n0:06\nMy email is tomas@example.com and I am Tomas Beltran.\n"


def make_client(web, name="Tomas"):
    return web.post("/clients", {"first_name": name}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]


def save(web, cid, text=TEXT):
    r = web.post(f"/clients/{cid}/intake", {"text": text, "call_date": "2026-11-02"})
    assert "Review before saving" in r.text, r.text[:300]
    r = web.post(f"/clients/{cid}/intake/save", review_form(r.text), follow_redirects=False)
    assert r.status_code == 303
    return saved_tx(r)


def scrubbed(web, tx):
    return web.stored_text(tx)


def test_every_client_log_shows_its_scrub_options(web):
    a, b = make_client(web, "Tomas"), make_client(web, "Maria")
    for cid in (a, b):
        page = web.get(f"/clients/{cid}/intake").text
        assert "Hide from Claude" in page
        assert page.count('name="types"') == 2 and 'name="first_hide"' in page and 'name="last_hide"' in page and page.count("checked") >= 5


def test_everything_is_scrubbed_by_default(web):
    cid = make_client(web)
    view = scrubbed(web, save(web, cid))
    assert "tomas@example.com" not in view and "[EMAIL_1]" in view and "Beltran" not in view


def test_switching_a_type_off_leaves_it_as_written_for_that_client_only(web):
    a, b = make_client(web, "Tomas"), make_client(web, "Maria")
    r = web.post(f"/clients/{a}/options", {"types": ["PERSON", "ADDRESS"], "first_names": "inherit"}, follow_redirects=False)
    assert r.status_code == 303
    page = web.get(f"/clients/{a}/intake").text
    assert re.search(r'value="EMAIL"(?![^>]*checked)', page) and re.search(r'name="first_hide"[^>]*checked', page)
    view_a, view_b = scrubbed(web, save(web, a)), scrubbed(web, save(web, b))
    assert "tomas@example.com" in view_a and "[EMAIL_" not in view_a and "Beltran" not in view_a
    assert "tomas@example.com" not in view_b and "[EMAIL_1]" in view_b


def test_names_off_leaves_names_and_stops_flagging_capitalized_words(web):
    cid = make_client(web)
    web.post(f"/clients/{cid}/options", {"types": ["EMAIL", "ADDRESS"], "first_names": "inherit"})
    r = web.post(f"/clients/{cid}/intake", {"text": TEXT, "call_date": "2026-11-02"})
    assert 'name="n_flags" value="0"' in r.text
    view = scrubbed(web, saved_tx(web.post(f"/clients/{cid}/intake/save", review_form(r.text), follow_redirects=False)))
    assert "Beltran" in view and "tomas@example.com" not in view


def test_at_least_one_type_must_stay_on(web):
    cid = make_client(web)
    r = web.post(f"/clients/{cid}/options", {"first_names": "inherit", "back": "intake"}, follow_redirects=False)
    assert r.status_code == 200 and "Choose at least one" in r.text
    assert page_has_all_checked(web.get(f"/clients/{cid}/intake").text)


def page_has_all_checked(page):
    return (all(re.search(rf'value="{t}"[^>]*checked', page) for t in ("EMAIL", "ADDRESS"))
            and all(re.search(rf'name="{n}"[^>]*checked', page) for n in ("first_hide", "last_hide")))


def test_first_name_option_is_per_client(web):
    cid = make_client(web)
    web.post(f"/clients/{cid}/options", {"types": ["PERSON", "EMAIL", "ADDRESS"], "first_names": "keep"})
    assert 'name="first_hide" value="1" checked' not in web.get(f"/clients/{cid}/intake").text
    view = scrubbed(web, save(web, cid, TEXT.replace("Tomas Beltran", "Tomas Beltran").replace("I am Tomas Beltran", "I am Tomas Beltran")))
    assert "Beltran" not in view


def test_the_options_apply_to_messages_to_claude(web):
    cid = make_client(web)
    save(web, cid)
    web.post(f"/clients/{cid}/options", {"types": ["PERSON", "ADDRESS"], "first_names": "inherit"})
    r = web.post(f"/clients/{cid}/outgoing/preview", {"text": "Her email is tomas@example.com", "kind": "comment", "tx_id": ""})
    assert "tomas@example.com" in r.text


def test_bad_option_values_are_ignored_safely(web):
    cid = make_client(web)
    r = web.post(f"/clients/{cid}/options", {"types": ["PERSON", "SSN", "<script>"], "first_names": "bogus", "back": "intake"}, follow_redirects=False)
    assert r.status_code == 200 and "Unknown scrub option" in r.text
    assert page_has_all_checked(web.get(f"/clients/{cid}/intake").text)


def test_double_submitting_save_stores_the_call_once(web):
    cid = make_client(web)
    r = web.post(f"/clients/{cid}/intake", {"text": TEXT, "call_date": "2026-11-02"})
    form = review_form(r.text)
    a = saved_tx(web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False))
    b = saved_tx(web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False))
    assert a == b
    assert web.get(f"/clients/{cid}").text.count(a) >= 1
    assert save(web, cid) == a          # pasting the same call again also adds nothing


def test_a_returning_call_matches_an_archived_client_and_restores_them(web):
    cid = make_client(web)
    save(web, cid)
    web.post(f"/clients/{cid}/archive", {}, follow_redirects=False)
    r = web.post("/intake", {"text": TEXT, "call_date": "2026-11-02"})
    assert "This looks like an existing client" in r.text and cid in r.text and "archived" in r.text
    r = web.post("/intake/start", {"text": TEXT, "call_date": "2026-11-02", "client": cid, "first_name": ""})
    assert "Review before saving" in r.text
    assert f'href="/clients/{cid}"' in web.get("/").text.split("Archived")[0]     # back in the active list


def test_a_future_call_date_is_refused(web):
    r = web.post("/intake", {"text": TEXT, "call_date": "2999-01-01"})
    assert "not in the future" in r.text and "Review before saving" not in r.text
    cid = make_client(web)
    r = web.post(f"/clients/{cid}/intake", {"text": TEXT, "call_date": "2999-01-01"})
    assert "not in the future" in r.text


def test_errors_show_a_page_with_a_way_back_but_scripts_still_get_json(web):
    page = web.c.post("/intake", data={"text": "x", "call_date": "2026-11-02", "csrf": "stale"},
                           headers={"accept": "text/html"})
    assert page.status_code == 403 and "Go to clients" in page.text and "expired" in page.text
    assert web.c.get("/clients/nope", headers={"accept": "text/html"}).status_code == 404
    js = web.c.post("/intake", json={}, headers={"X-CSRF-Token": "stale"})
    assert js.status_code == 403 and js.json()["detail"]
