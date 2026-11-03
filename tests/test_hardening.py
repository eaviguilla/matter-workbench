"""Bugs found by breaking the app: damaged form data, text with invisible characters,
registry numbers reused after a delete, and screens that said nothing when an action was refused."""
import random
import socket
from datetime import date

import pytest

from app import workflow as wf
from app.__main__ import serve
from app.store import Store
from app.scrub.pipeline import ScrubConfig, _merge, scrub_transcript
from app.scrub.registry import Registry
from app.scrub.spans import Span
from app.web import create_app
from tests.webhelp import Session, make_app, review_form, saved_tx

CALL = "• Rosa Delgado 0:01\nHello, this is Rosa Delgado.\n• Pat Office 0:05\nHi Rosa.\n"


@pytest.fixture
def web(tmp_path):
    return Session(make_app(tmp_path))


def new_client(web, name="Rosa"):
    r = web.post("/clients", {"first_name": name}, follow_redirects=False)
    return r.headers["location"].rsplit("/", 1)[1]


def saved(web, cid, text=CALL, day="2026-11-01"):
    r = web.post(f"/clients/{cid}/intake", {"text": text, "call_date": day})
    r = web.post(f"/clients/{cid}/intake/save", review_form(r.text), follow_redirects=False)
    return saved_tx(r)



# ---- damaged form and JSON bodies are refused with a page, never a 500 -------------------------

@pytest.mark.parametrize("fields", [
    {"n_flags": "abc"},
    {"n_flags": "-3"},
    {"n_flags": "1", "d0": "scrub", "s0": "a:b", "w0": "X"},
    {"n_flags": "1", "d0": "scrub", "s0": "1:2:3", "w0": "X"},
])
def test_damaged_review_fields_get_a_400_page(web, fields):
    cid = new_client(web)
    for route in ("save", "rescan"):
        r = web.post(f"/clients/{cid}/intake/{route}", {"text": CALL, "call_date": "2026-11-01", **fields},
                     headers={"accept": "text/html"})
        assert r.status_code == 400 and "Something went wrong" in r.text


@pytest.mark.parametrize("carry", ["[1, 2]", "3", "null", '{"decisions": 3}', '{"decisions": [{"decision": "scrub"}]}',
                                   '{"decisions": [{"decision": "scrub", "text": "A", "spans": 5}]}',
                                   '{"extras": [["PERSON"], "xy", 7], "decisions": [null]}'])
def test_damaged_carry_value_is_ignored(web, carry):
    cid = new_client(web)
    r = web.post(f"/clients/{cid}/intake/save", {"text": CALL, "call_date": "2026-11-01", "carry": carry},
                 follow_redirects=False)
    assert r.status_code in (200, 303)


def test_outgoing_bodies_that_are_not_json_objects_are_refused(web):
    cid = new_client(web)
    h = {"X-CSRF-Token": web.token}
    r = web.c.post(f"/clients/{cid}/outgoing/preview", content="not json", headers={**h, "content-type": "application/json"})
    assert r.status_code == 400
    assert web.c.post(f"/clients/{cid}/outgoing/preview", json=[1, 2], headers=h).status_code == 400
    assert web.c.post(f"/clients/{cid}/outgoing/copy", json="text", headers=h).status_code == 400


def test_an_empty_message_is_not_copied_or_stored(web, tmp_path):
    cid = new_client(web)
    for text in ("", "   \n "):
        r = web.post_json(f"/clients/{cid}/outgoing/copy", {"text": text, "kind": "comment"})
        assert r.status_code == 400 and "message" in r.json()["error"].lower()
    with Store.open(tmp_path / "data", env={}, home=tmp_path / "home") as s:
        assert s.list_messages(cid) == []


def test_a_huge_message_is_refused_before_scrubbing(web):
    cid = new_client(web)
    r = web.post_json(f"/clients/{cid}/outgoing/preview", {"text": "a " * (wf.MAX_PASTE // 2 + 5), "kind": "comment"})
    assert "over" in r.json()["error"]


# ---- exports, dates, query strings ------------------------------------------------------------

def test_export_works_for_a_name_in_any_script(web):
    cid = new_client(web, "Мария")
    r = web.post(f"/clients/{cid}/export")
    assert r.status_code == 200
    disposition = r.headers["content-disposition"]
    disposition.encode("latin-1")
    assert "filename*=UTF-8''" in disposition and ".md" in disposition


def test_a_call_date_before_1990_is_refused(web):
    cid = new_client(web)
    for day in ("0001-01-01", "0999-05-05", "1989-12-31"):
        r = web.post(f"/clients/{cid}/intake", {"text": CALL, "call_date": day})
        assert "Review before saving" not in r.text and "not before 1990" in r.text
    assert "Review before saving" in web.post(f"/clients/{cid}/intake", {"text": CALL, "call_date": "1990-01-01"}).text


def test_bad_query_numbers_show_the_page(web):
    cid = new_client(web)
    tx = saved(web, cid)
    h = {"accept": "text/html"}
    assert web.get(f"/transcripts/{tx}?clio-note=abc&cmp-clio-note=x", headers=h).status_code == 200
    assert web.get("/settings?saved=abc", headers=h).status_code == 200


def test_demo_never_holds_a_future_call(tmp_path):
    from app.demo import create_demo_app
    app = create_demo_app(model_dir=tmp_path / "no-model")
    with Store.open(app.state.data_dir, env={}, home=app.state.home) as s:
        dates = [t["call_date"] for c in s.list_clients(True) for t in s.list_transcripts(c["id"])]
    assert dates and max(dates) <= date.today().isoformat()


# ---- refused actions say so ---------------------------------------------------------------

def test_rename_to_nothing_says_why(web):
    cid = new_client(web)
    r = web.post(f"/clients/{cid}/rename", {"first_name": "  "}, follow_redirects=False)
    assert r.status_code == 200 and "Enter a first name" in r.text


def test_saving_options_confirms(web):
    cid = new_client(web)
    r = web.post(f"/clients/{cid}/options", {"types": ["PERSON"], "first_names": "scrub", "back": "intake"}, follow_redirects=True)
    assert "Saved." in r.text


def test_deleting_a_client_that_holds_a_summary_asks_first_then_removes_it(web):
    cid = new_client(web)
    web.post(f"/clients/{cid}/import", {"text": "Summary text", "kind": "summary", "tx_id": ""})
    web.post(f"/clients/{cid}/import/save", {"content": "Summary text", "kind": "summary", "tx_id": ""})
    page = web.get(f"/clients/{cid}/delete")
    assert page.status_code == 200 and "There is no undo" in page.text and "Cancel, keep it" in page.text
    assert web.get(f"/clients/{cid}").status_code == 200            # asking changed nothing
    assert web.post(f"/clients/{cid}/delete", {}, follow_redirects=False).status_code == 303
    assert web.get(f"/clients/{cid}").status_code == 404


def test_settings_error_page_keeps_the_connector_command(web):
    r = web.post("/settings", {"threshold": "nan", "idle_minutes": "10"})
    assert "-m mcp_server" in r.text and "threshold" in r.text.lower()


def test_deleting_an_empty_client_removes_its_settings(tmp_path):
    from tests.test_pending_and_options import store
    with store(tmp_path) as s:
        cid = s.create_client("Tomas")
        wf.save_client_options(s, cid, wf.ClientOptions(frozenset({"PERSON"}), "keep"))
        s.save_registry(cid, Registry())
        assert s.delete_empty_client(cid)
        assert s.get_client(cid) is None and s.get_setting(f"client.{cid}.types") is None
        assert not s._client_dir(cid).exists()


# ---- registry numbers are never reused ----------------------------------------------------

def test_a_deleted_number_is_not_given_to_someone_else():
    reg = Registry()
    reg.add_value("PERSON", "Anna Lee")
    gone = reg.add_value("PERSON", "Bo Chan")[0]
    reg.remove(gone)
    assert reg.add_value("PERSON", "Cy Dunn")[0].n == gone.n + 1


def test_the_high_number_survives_a_save_and_load(tmp_path):
    from tests.test_pending_and_options import store
    with store(tmp_path) as s:
        cid = s.create_client("Anna")
        reg = Registry()
        reg.add_value("PERSON", "Anna Lee")
        only = reg.add_value("PERSON", "Bo Chan")[0]
        reg.remove(only)
        s.save_registry(cid, reg)
        again = s.load_registry(cid)
        assert again.add_value("PERSON", "Cy Dunn")[0].n == only.n + 1
        reg2 = Registry()
        gone = reg2.add_value("PERSON", "Solo Person")[0]
        reg2.remove(gone)                                   # every entry deleted: nothing left to count from
        s.save_registry(cid, reg2)
        assert s.load_registry(cid).add_value("PERSON", "Next One")[0].n == gone.n + 1


def test_registry_edit_refuses_a_form_the_entry_does_not_have(web):
    cid = new_client(web)
    saved(web, cid)
    r = web.post(f"/clients/{cid}/registry/edit", {"type": "PERSON", "n": "1", "part": "nick", "value": "Ro"})
    assert r.status_code == 200 and "no such form" in r.text
    r = web.post(f"/clients/{cid}/registry/edit", {"type": "PERSON", "n": "1", "part": "weird", "value": "Zed"})
    assert "no such form" in r.text and "weird" not in web.get(f"/clients/{cid}/registry").text


# ---- text the scrubber must read the way a person does -----------------------------------

CFG = ScrubConfig()


def scrub(text, registry=None):
    return scrub_transcript(text, registry or Registry(), CFG, None).text


def test_po_box_is_an_address():
    out = scrub("• Pat Office 0:01\nSend it to PO Box 4421, Dallas TX 75201 please.\n")
    assert "4421" not in out and "[ADDRESS_1]" in out
    assert "4421" not in scrub("• Pat Office 0:01\nMail goes to P.O. Box 77.\n")


def test_cjk_names_are_replaced_inside_a_sentence():
    out = scrub("• 王小明 0:01\n我是王小明，我住在这里。\n")
    assert "王小明" not in out


def test_clean_text_drops_invisible_characters_and_composes_accents():
    assert wf.clean_text("﻿Ro​sa Del‍gado") == "Rosa Delgado"
    assert wf.clean_text("José") == "José"


def test_names_split_by_zero_width_characters_are_still_scrubbed(web):
    cid = new_client(web)
    text = "• Rosa Delgado 0:01\nHi, this is Ro​sa Del​gado.\n• Pat Office 0:05\nHello.\n"
    tx = saved(web, cid, text)
    assert "Delgado" not in web.stored_text(tx)


def test_a_byte_order_mark_does_not_hide_the_first_speaker():
    from app.scrub.parse import parse_lenient
    text = wf.clean_text("﻿• Rosa Delgado 0:01\nHi.\n• Pat Office 0:05\nHello.\n")
    assert [t.speaker for t in parse_lenient(text).turns] == ["Rosa Delgado", "Pat Office"]


def test_composed_and_decomposed_accents_are_one_person(web):
    cid = new_client(web, "Jose")
    text = "• José Peña 0:01\nHola, José Peña aqui.\n• Pat Office 0:05\nHola.\n"
    tx = saved(web, cid, text)
    body = web.stored_text(tx)
    assert "Pe" not in body.replace("Pat", "")
    assert body.count("[PERSON_1]") == 2           # the speaker line and the decomposed spelling in the body


# ---- speed ------------------------------------------------------------------------------

def test_merge_matches_the_simple_version_and_is_fast():
    rnd = random.Random(7)
    spans = []
    for _ in range(400):
        s = rnd.randrange(0, 300)
        spans.append(Span(s, s + rnd.randrange(1, 12), "PERSON", rnd.choice(["regex", "ner", "registry"]), "x"))

    def naive(spans):
        chosen = []
        for sp in sorted(spans, key=lambda s: (-s.length, {"regex": 1, "ner": 1.5, "registry": 3}.get(s.source, 9), s.start)):
            if all(sp.end <= c.start or sp.start >= c.end for c in chosen):
                chosen.append(sp)
        return sorted(chosen, key=lambda s: s.start)

    assert _merge(spans) == naive(spans)
    import time
    many = [Span(i * 10, i * 10 + 5, "PERSON", "registry", "x") for i in range(60_000)]
    t = time.time()
    assert len(_merge(many)) == 60_000
    assert time.time() - t < 3


def test_a_long_repetitive_transcript_scrubs_quickly():
    import time
    reg = Registry()
    reg.add_person("Rosa Delgado")
    text = "• Rosa Delgado 0:01\n" + "Rosa Delgado said Rosa called Delgado again. " * 6000
    t = time.time()
    res = scrub_transcript(text, reg, CFG, None)
    assert "Delgado" not in res.text and time.time() - t < 15
