"""Round 5: the Transcript tab shows real values with the hidden ones highlighted, scrubbing options hold when a call is
copied (also for calls saved earlier), delete a transcript or a client, and the standing instructions for Claude."""
import re
from datetime import date

import pytest

from app import workflow as wf
from app.scrub.registry import Registry
from app.store import Store
from tests.webhelp import Session, make_app

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
JS = (ROOT / "app/web/static/app.js").read_text()
NOTE = "clio-note"


@pytest.fixture
def web(tmp_path):
    return Session(make_app(tmp_path))


def store_of(web) -> Store:
    app = web.c.app
    return Store.open(app.state.data_dir, env={}, home=app.state.home)


def make_call(web, day=date(2026, 11, 2)):
    """A client with one call that holds a name, a first name alone, an email and an address, all as codes."""
    with store_of(web) as s:
        cid = s.create_client("Tomas")
        reg = Registry()
        person = reg.add_person("Tomas Beltran")[0]
        email = reg.add_value("EMAIL", "tomas@example.com")[0]
        addr = reg.add_value("ADDRESS", "12 Oak Street Springfield")[0]
        s.save_registry(cid, reg)
        text = (f"• {person.placeholder()} 0:01\nHi, I am {person.placeholder()}. Call me {person.placeholder('first')}, "
                f"write to {email.placeholder()}, I live at {addr.placeholder()}.\n")
        tx = s.add_transcript(cid, text, day)
        s.set_transcript_status(tx, "reviewed")
    return cid, tx, text


def copy(web, tx, outputs=(NOTE,)):
    return web.post_json(f"/transcripts/{tx}/copy", {"outputs": list(outputs)}).json()["text"]


def options(web, cid, types, first="inherit"):
    with store_of(web) as s:
        wf.save_client_options(s, cid, wf.ClientOptions(frozenset(types), first))


# ---- scrubbing options hold at copy time ----------------------------------------------------------

def test_a_copy_hides_everything_by_default(web):
    cid, tx, _ = make_call(web)
    text = copy(web, tx)
    assert "tomas@example.com" not in text and "Beltran" not in text and "[EMAIL_1]" in text


def test_unticking_a_kind_sends_it_as_real_text_for_a_call_saved_earlier(web):
    cid, tx, _ = make_call(web)
    options(web, cid, {"PERSON", "ADDRESS"})
    text = copy(web, tx)
    body = text.split("[CLIENT:", 1)[1]
    assert "tomas@example.com" in body and "[EMAIL_1]" not in body
    assert "Beltran" not in text and "12 Oak Street" not in text          # the kinds still ticked stay hidden


def test_the_saved_copy_record_keeps_the_hidden_form(web):
    cid, tx, _ = make_call(web)
    options(web, cid, {"PERSON", "ADDRESS"})
    copy(web, tx)
    with store_of(web) as s:
        saved = [m["scrubbed_text"] for m in s.list_messages(cid) if m["kind"] == "transcript"]
    assert saved and "tomas@example.com" not in saved[0] and "[EMAIL_1]" in saved[0]


def test_keeping_first_names_restores_only_the_first_name_codes(web):
    cid, tx, _ = make_call(web)
    options(web, cid, {"PERSON", "EMAIL", "ADDRESS"}, "keep")
    text = copy(web, tx)
    assert "Call me Tomas," in text and "Beltran" not in text and "Tomas [PERSON_1.last]" in text


def test_a_change_request_follows_the_options_too(web):
    cid, tx, _ = make_call(web)
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note for [PERSON_1] at [EMAIL_1].")
    options(web, cid, {"PERSON", "ADDRESS"})
    r = web.post_json(f"/transcripts/{tx}/outputs/{NOTE}/request-change", {"text": "Shorten it.", "version": 1, "latest": 1})
    sent = r.json()["text"]
    assert r.status_code == 200 and "Transcript:\n" in sent
    assert "tomas@example.com" in sent.split("Transcript:\n", 1)[1] and "Beltran" not in sent


def test_a_code_with_no_known_value_is_left_as_written(web):
    cid, tx, _ = make_call(web)
    with store_of(web) as s:
        assert wf.restore_switched_off(s, cid, "See [EMAIL_9] and [EMAIL_1].") == "See [EMAIL_9] and [EMAIL_1]."
    options(web, cid, {"PERSON", "ADDRESS"})
    with store_of(web) as s:
        assert wf.restore_switched_off(s, cid, "See [EMAIL_9] and [EMAIL_1].") == "See [EMAIL_9] and tomas@example.com."


# ---- the Transcript tab ---------------------------------------------------------------------------

def test_the_transcript_tab_shows_real_values_with_the_hidden_ones_marked(web):
    cid, tx, _ = make_call(web)
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert '<mark class="tag tag-email">tomas@example.com</mark>' in page
    assert '<mark class="tag tag-person">Tomas Beltran</mark>' in page and "[EMAIL_1]" not in page


def test_a_kind_that_goes_out_as_written_is_not_marked(web):
    cid, tx, _ = make_call(web)
    options(web, cid, {"PERSON", "ADDRESS"})
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert "tomas@example.com" in page and 'tag-email">tomas@example.com' not in page
    assert '<mark class="tag tag-person">Tomas Beltran</mark>' in page


def test_the_options_sit_under_the_transcript_not_in_the_dropdown(web):
    cid, tx, _ = make_call(web)
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert page.count('name="types"') == 2 and "Scrubbing options" not in page
    assert page.index('id="scrubbed-view"') < page.index('id="scrub-options"') < page.index("Copy for Claude")
    r = web.post(f"/clients/{cid}/options", {"types": ["PERSON"], "first_names": "inherit", "tx": tx}, follow_redirects=False)
    assert r.status_code == 303 and f"tx={tx}" in r.headers["location"] and "#" not in r.headers["location"]


def test_text_that_is_already_marked_gets_no_hide_button(web):
    assert 'querySelectorAll("mark.tag")' in JS and "intersectsNode" in JS


# ---- delete a transcript --------------------------------------------------------------------------

def two_calls(web):
    cid, tx1, text = make_call(web)
    with store_of(web) as s:
        tx2 = s.add_transcript(cid, "Second call with nobody named.", date(2026, 11, 3))
        s.add_output(cid, tx1, NOTE, "Note for [PERSON_1].")
        s.add_message(cid, "transcript", "copied text", tx1)
        s.add_message(cid, "transcript", "other copied text", tx2)
    return cid, tx1, tx2


def test_the_confirm_page_deletes_nothing(web):
    cid, tx1, _ = two_calls(web)
    page = web.get(f"/transcripts/{tx1}/delete")
    assert page.status_code == 200 and "There is no undo" in page.text and "Cancel, keep it" in page.text
    assert web.get(f"/clients/{cid}?tx={tx1}").status_code == 200
    assert web.get("/transcripts/TX-20200101-9/delete").status_code == 404


def test_deleting_a_transcript_removes_its_files_outputs_and_messages_only(web):
    cid, tx1, tx2 = two_calls(web)
    with store_of(web) as s:
        folder = s._tx_dir(cid, tx1)
        assert folder.is_dir()
    r = web.post(f"/transcripts/{tx1}/delete", follow_redirects=False)
    assert r.status_code == 303
    with store_of(web) as s:
        assert [t["id"] for t in s.list_transcripts(cid)] == [tx2] and not folder.exists()
        assert s.list_outputs(tx1, NOTE) == [] if s.get_transcript(tx1) else True
        assert [m["scrubbed_text"] for m in s.list_messages(cid)] == ["other copied text"]
    assert web.get(f"/clients/{cid}?tx={tx1}").status_code == 404
    assert "Transcript deleted." in web.get(r.headers["location"]).text


def test_a_name_hidden_for_that_call_only_goes_with_it_but_client_wide_names_stay(web):
    cid, tx1, text = make_call(web)
    with store_of(web) as s:
        reg = s.load_registry(cid)
        local = reg.add_local_person("May")
        s.save_registry(cid, reg)
        tx2 = s.add_transcript(cid, f"Rent from {local.placeholder()}.", date(2026, 11, 4))
        names = {e.forms.get(None) for e in reg.entities}
    assert {"May", "Tomas Beltran"} <= names
    web.post(f"/transcripts/{tx2}/delete", follow_redirects=False)
    with store_of(web) as s:
        left = {e.forms.get(None) for e in s.load_registry(cid).entities}
    assert "May" not in left and {"Tomas Beltran", "tomas@example.com"} <= left


def test_a_local_name_another_call_still_uses_is_kept(web):
    cid, tx1, _ = make_call(web)
    with store_of(web) as s:
        reg = s.load_registry(cid)
        local = reg.add_local_person("May")
        s.save_registry(cid, reg)
        a = s.add_transcript(cid, f"Rent from {local.placeholder()}.", date(2026, 11, 4))
        s.add_transcript(cid, f"Again {local.placeholder()}.", date(2026, 11, 5))
    web.post(f"/transcripts/{a}/delete", follow_redirects=False)
    with store_of(web) as s:
        assert "May" in {e.forms.get(None) for e in s.load_registry(cid).entities}


def test_deleting_a_transcript_is_audited_without_values(web):
    cid, tx1, _ = two_calls(web)
    web.post(f"/transcripts/{tx1}/delete", follow_redirects=False)
    with store_of(web) as s:
        log = (s.folder / "audit.jsonl").read_text()
    assert '"transcript_deleted"' in log and "Beltran" not in log and "tomas@example.com" not in log


# ---- delete a client ------------------------------------------------------------------------------

def test_the_client_header_has_a_delete_link_at_the_right(web):
    cid, tx, _ = make_call(web)
    page = web.get(f"/clients/{cid}").text
    assert f'<a class="deletelink" href="/clients/{cid}/delete">Delete client</a>' in page
    assert f'href="/transcripts/{tx}/delete">Delete transcript</a>' in page


def test_deleting_a_client_removes_every_file_it_had(web):
    cid, tx1, tx2 = two_calls(web)
    with store_of(web) as s:
        folder = s._client_dir(cid)
    page = web.get(f"/clients/{cid}/delete").text
    assert "2 transcripts" in page and "1 saved output version" in page and "There is no undo" in page
    assert folder.is_dir()
    assert web.post(f"/clients/{cid}/delete", follow_redirects=False).status_code == 303
    assert not folder.exists() and web.get(f"/clients/{cid}").status_code == 404


def test_delete_needs_the_form_token(web):
    cid, tx, _ = make_call(web)
    r = web.c.post(f"/clients/{cid}/delete", follow_redirects=False)
    assert r.status_code in (400, 403) and web.get(f"/clients/{cid}").status_code == 200
    r = web.c.post(f"/transcripts/{tx}/delete", follow_redirects=False)
    assert r.status_code in (400, 403) and web.get(f"/clients/{cid}?tx={tx}").status_code == 200


# ---- the standing instructions for Claude ---------------------------------------------------------

def test_settings_has_the_instructions_to_save_in_claude(web):
    page = web.get("/settings").text
    assert "Instructions to save in Claude" in page and "Copy instructions" in page
    shown = re.search(r'<pre id="claude-instructions"[^>]*>(.*?)</pre>', page, re.S).group(1)
    assert "[OUTPUT: clio-note]" in shown and "save_output" not in shown


def test_the_instructions_name_the_save_tool_only_while_the_connector_is_on(web):
    with store_of(web) as s:
        s.set_setting("mcp_enabled", "1")
    page = web.get("/settings").text
    shown = re.search(r'<pre id="claude-instructions"[^>]*>(.*?)</pre>', page, re.S).group(1)
    assert "save_output" in shown and "[OUTPUT: clio-note]" in shown
    assert "[PERSON_1]" in shown and "Change request" in shown and "[ANSWER: &lt;question number&gt;]" in shown


def test_the_instructions_use_the_wording_the_copy_uses(web):
    for on in (True, False):
        text = wf.project_instructions(on)
        assert "jordan-calendar-overview" in text and "clio-form-note" in text and "{saving}" not in text


# ---- First names is a checkbox in the options row --------------------------------------------------

def test_first_names_is_a_checkbox_in_the_row_ticked_while_they_are_hidden(web):
    cid, tx, _ = make_call(web)
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert page.count('name="first_hide" value="1" data-name-part checked') == 1 and 'name="first_names"' not in page


def test_unticking_first_names_keeps_them_visible_and_ticking_hides_them_again(web):
    cid, tx, _ = make_call(web)
    web.post(f"/clients/{cid}/options", {"parts": "1", "last_hide": "1", "types": ["EMAIL", "ADDRESS"], "tx": tx}, follow_redirects=False)
    assert 'name="first_hide" value="1" data-name-part checked' not in web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert "Call me Tomas," in copy(web, tx) and "Beltran" not in copy(web, tx)
    web.post(f"/clients/{cid}/options", {"parts": "1", "first_hide": "1", "last_hide": "1", "types": ["EMAIL", "ADDRESS"], "tx": tx}, follow_redirects=False)
    assert 'name="first_hide" value="1" data-name-part checked' in web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert "Call me [PERSON_1.first]" in copy(web, tx) and "Call me Tomas," not in copy(web, tx)


def test_an_old_global_keep_first_names_value_is_ignored_and_settings_has_no_such_box(web):
    cid, tx, _ = make_call(web)
    with store_of(web) as s:
        s.set_setting("keep_first_names", "1")                       # left behind by an older version
    assert 'name="first_hide" value="1" data-name-part checked' in web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert "Call me [PERSON_1.first]" in copy(web, tx)
    assert "keep_first_names" not in web.get("/settings").text


def test_a_one_word_name_counts_as_a_first_name_but_a_full_name_and_a_title_surname_do_not(web):
    with store_of(web) as s:
        cid = s.create_client("Tomas")
        reg = Registry()
        lone = reg.add_person("Anselmo")[0]
        full = reg.add_person("Tomas Beltran")[0]
        title = reg.add_person("Okafor")[0]
        title.surname_only = True
        s.save_registry(cid, reg)
    text = f"{lone.placeholder()} met {full.placeholder()} and {title.placeholder()} and {full.placeholder('first')}."
    options(web, cid, {"PERSON", "EMAIL", "ADDRESS"}, "keep")
    with store_of(web) as s:
        assert wf.restore_switched_off(s, cid, text) == f"Anselmo met Tomas {full.placeholder('last')} and {title.placeholder()} and Tomas."
        tags = dict((t, ty) for t, ty in wf.real_segments(s, cid, text) if t in ("Anselmo", "Tomas", "Tomas Beltran", "Okafor"))
    assert tags["Anselmo"] is None and tags["Tomas"] is None and tags["Okafor"] == "PERSON" and "Tomas Beltran" not in tags


def test_a_posted_form_keeps_the_place_on_the_page(web):
    assert 'document.addEventListener("submit", rememberScroll)' in JS and "window.scrollTo(0, saved.y)" in JS


# ---- Names, First names and Last names ------------------------------------------------------------

def long_name_call(web):
    with store_of(web) as s:
        cid = s.create_client("Maria")
        reg = Registry()
        full3 = reg.add_person("Maria Elena Lopez")[0]
        full2 = reg.add_person("Pat Nguyen")[0]
        s.save_registry(cid, reg)
        text = (f"{full3.placeholder()} said {full3.placeholder('first')} and Ms. {full3.placeholder('last')} agree. "
                f"{full2.placeholder()} also {full2.placeholder('last')}.")
        tx = s.add_transcript(cid, text, date(2026, 11, 2))
        s.set_transcript_status(tx, "reviewed")
    return cid, tx, full3.placeholder, full2.placeholder


def set_parts(web, cid, first, last, tx=None):
    form = {"parts": "1", "types": ["EMAIL", "ADDRESS"], "tx": tx or ""}
    if first:
        form["first_hide"] = "1"
    if last:
        form["last_hide"] = "1"
    return web.post(f"/clients/{cid}/options", form, follow_redirects=False)


def body_of(web, tx):
    return copy(web, tx).split("[CLIENT:", 1)[1].split("]\n", 1)[1].strip()


@pytest.mark.parametrize("first,last,expected", [
    (True, True, "[PERSON_1] said [PERSON_1.first] and Ms. [PERSON_1.last] agree. [PERSON_2] also [PERSON_2.last]."),
    (False, True, "Maria [PERSON_1.rest] said Maria and Ms. [PERSON_1.last] agree. Pat [PERSON_2.last] also [PERSON_2.last]."),
    (True, False, "[PERSON_1.first] Elena Lopez said [PERSON_1.first] and Ms. Lopez agree. [PERSON_2.first] Nguyen also Nguyen."),
    (False, False, "Maria Elena Lopez said Maria and Ms. Lopez agree. Pat Nguyen also Nguyen."),
])
def test_each_mix_of_first_and_last_names_gives_the_copied_text(web, first, last, expected):
    cid, tx, *_ = long_name_call(web)
    assert set_parts(web, cid, first, last, tx).status_code == 303
    assert body_of(web, tx) == expected


def test_a_three_word_name_comes_back_whole_from_the_new_rest_code(web):
    cid, tx, *_ = long_name_call(web)
    with store_of(web) as s:
        reg = s.load_registry(cid)
        res = wf.rehydrate("[PERSON_1.first] [PERSON_1.rest] and [PERSON_1.rest] and [PERSON_2.rest]", reg)
        assert res.text == "Maria Elena Lopez and Elena Lopez and Nguyen" and res.unknown == []
        assert reg.surface(reg.entity("PERSON", 1), "rest") == "Elena Lopez"


def test_the_transcript_tab_marks_only_the_hidden_parts_of_a_name(web):
    cid, tx, *_ = long_name_call(web)
    set_parts(web, cid, False, True, tx)                    # first names visible, last names hidden
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert 'Maria <mark class="tag tag-person">Elena Lopez</mark> said Maria and' in page
    set_parts(web, cid, True, False, tx)
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert '<mark class="tag tag-person">Maria</mark> Elena Lopez said' in page


def test_the_names_box_shows_ticked_only_while_both_parts_are(web):
    cid, tx, *_ = long_name_call(web)
    url = f"/clients/{cid}?tx={tx}&view=transcript"
    assert "data-name-all checked" in web.get(url).text
    set_parts(web, cid, True, False, tx)
    assert "data-name-all checked" not in web.get(url).text
    set_parts(web, cid, False, False, tx)
    page = web.get(url).text
    assert "data-name-all checked" not in page and 'name="first_hide" value="1" data-name-part checked' not in page
    assert "Maria Elena Lopez said Maria" in body_of(web, tx)


def test_both_name_boxes_unticked_is_the_same_as_names_off_and_one_thing_must_stay_on(web):
    cid, tx, *_ = long_name_call(web)
    set_parts(web, cid, False, False, tx)
    with store_of(web) as s:
        assert "PERSON" not in wf.load_client_options(s, cid).types
    r = web.post(f"/clients/{cid}/options", {"parts": "1", "back": "intake"}, follow_redirects=False)
    assert r.status_code == 200 and "Choose at least one" in r.text


def test_a_reply_with_a_visible_last_name_is_left_alone_and_a_hidden_one_is_masked(web):
    cid, tx, *_ = long_name_call(web)
    reply = f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {NOTE}]\n[PERSON_1.first] and Ms. Lopez met."
    with store_of(web) as s:
        hidden = wf.check_import(s, cid, reply, tx, False)
        assert hidden.masked == 1 and "Lopez" not in hidden.content           # a plain last name is put back as its code
    set_parts(web, cid, True, False, tx)
    with store_of(web) as s:
        check = wf.check_import(s, cid, reply, tx, False)
        assert check.possible_real == [] and check.masked == 0 and "Lopez" in check.content


def test_the_first_names_box_is_one_choice_for_the_whole_name_and_js_keeps_names_in_step(web):
    assert 'matches("[data-name-all]")' in JS and 'querySelectorAll("[data-name-part]")' in JS


def odd_names_call(web):
    """Entries the scrubber makes: a first name that later got a last name (None holds the first word), a surname that
    later got a first name (None holds the surname), a full name saved with no first form, and a lone first name."""
    with store_of(web) as s:
        cid = s.create_client("Maria")
        reg = Registry()
        a = reg.add_person("Larkspur")[0]
        reg.add_surname(a, "Terrace")
        b = reg.add_person("Okafor")[0]
        reg.add_firstname(b, "Desmond")
        c = reg.add_person("Rosa Maria Delgado")[0]
        del c.forms["first"], c.forms["last"]
        d = reg.add_person("Anselmo")[0]
        s.save_registry(cid, reg)
        text = f"{a.placeholder()} {a.placeholder('last')}; {b.placeholder('first')} {b.placeholder()}; {c.placeholder()}; {d.placeholder()}."
        tx = s.add_transcript(cid, text, date(2026, 11, 2))
        s.set_transcript_status(tx, "reviewed")
    return cid, tx


def hidden_words(web, cid):
    with store_of(web) as s:
        text = s.get_transcript(s.list_transcripts(cid)[0]["id"])["scrubbed_text"]
        return [t for t, ty in wf.real_segments(s, cid, text) if ty == "PERSON"]


def test_with_first_names_unticked_no_first_name_is_highlighted_however_the_name_is_stored(web):
    cid, tx = odd_names_call(web)
    set_parts(web, cid, False, True, tx)
    shown = hidden_words(web, cid)
    assert "Larkspur" not in shown and "Terrace" in shown                     # first word plain, last name marked
    assert "Desmond" not in shown and "Okafor" in shown                       # a lone surname stays marked
    assert "Rosa" not in "".join(shown) and "Maria Delgado" in shown          # split though no first form was saved
    assert "Anselmo" not in shown
    assert body_of(web, tx) == "Larkspur [PERSON_1.last]; Desmond [PERSON_2]; Rosa [PERSON_3.rest]; Anselmo."


def test_with_last_names_unticked_no_last_name_is_highlighted_however_the_name_is_stored(web):
    cid, tx = odd_names_call(web)
    set_parts(web, cid, True, False, tx)
    shown = hidden_words(web, cid)
    assert "Terrace" not in shown and "Larkspur" in shown
    assert "Okafor" not in shown and "Desmond" in shown
    assert "Rosa" in shown and "Maria Delgado" not in "".join(shown)
    assert "Anselmo" in shown
    assert body_of(web, tx) == "[PERSON_1] Terrace; [PERSON_2.first] Okafor; [PERSON_3.first] Maria Delgado; [PERSON_4]."


# ---- deleting a hidden name puts its real words back ----------------------------------------------

def test_deleting_a_hidden_name_puts_its_words_back_in_the_saved_text(web):
    cid, tx, _ = make_call(web)
    with store_of(web) as s:
        n = s.load_registry(cid).lookup("PERSON", "Tomas Beltran")[0].n
        s.add_output(cid, tx, NOTE, f"[PERSON_{n}] asked about rent. [PERSON_{n}.first] will call back.", "import")
    assert "[PERSON_1]" in web.stored_text(tx)
    r = web.post(f"/clients/{cid}/registry/delete", {"type": "PERSON", "n": str(n)}, follow_redirects=False)
    assert r.status_code == 303
    text = web.stored_text(tx)
    assert "[PERSON_" not in text and "Hi, I am Tomas Beltran. Call me Tomas, write to [EMAIL_1]" in text
    with store_of(web) as s:
        assert s.load_registry(cid).lookup("PERSON", "Tomas Beltran") is None
        versions = s.list_outputs(tx, NOTE)
    assert [v["source"] for v in versions] == ["import", "unhide"]
    assert versions[0]["content"].startswith(f"[PERSON_{n}]")                       # history is kept
    assert versions[1]["content"] == "Tomas Beltran asked about rent. Tomas will call back."


def test_deleting_one_hidden_name_leaves_the_codes_of_the_others(web):
    cid, tx, _ = make_call(web)
    with store_of(web) as s:
        n = s.load_registry(cid).lookup("PERSON", "Tomas Beltran")[0].n
    web.post(f"/clients/{cid}/registry/delete", {"type": "PERSON", "n": str(n)})
    text = web.stored_text(tx)
    assert "[EMAIL_1]" in text and "[ADDRESS_1]" in text


def test_a_name_can_be_hidden_again_after_it_was_deleted(web):
    cid, tx, _ = make_call(web)
    with store_of(web) as s:
        n = s.load_registry(cid).lookup("PERSON", "Tomas Beltran")[0].n
    web.post(f"/clients/{cid}/registry/delete", {"type": "PERSON", "n": str(n)})
    assert "Tomas Beltran" in web.stored_text(tx)
    r = web.post(f"/transcripts/{tx}/hide", {"type": "PERSON", "text": "Tomas Beltran"}, follow_redirects=False)
    assert r.status_code == 303 and "hid=0" not in r.headers["location"], r.text[:300]
    text = web.stored_text(tx)
    assert "Tomas Beltran" not in text and re.search(r"\[PERSON_\d+\]", text)
    with store_of(web) as s:
        ent = s.load_registry(cid).lookup("PERSON", "Tomas Beltran")[0]
        assert ent.n != n                                   # a new code, never the deleted one


# ---- a name hidden after the call was saved is hidden in every later copy ------------------------

def missed_name_call(web):
    """A saved call that holds a name in plain text, as if the scrubber missed it when the call was saved."""
    with store_of(web) as s:
        cid = s.create_client("Ines")
        tx = s.add_transcript(cid, "• Ines Moreau 0:01\nMy landlord is Dana Whitfield, and Dana Whitfield rang me.\n", date(2026, 11, 2))
        s.set_transcript_status(tx, "reviewed")
    return cid, tx


def test_a_name_added_later_is_hidden_in_the_next_copy_and_in_the_saved_call(web):
    cid, tx = missed_name_call(web)
    assert "Dana Whitfield" in copy(web, tx)                                  # not known yet, so it goes as written
    web.post(f"/clients/{cid}/registry/add", {"type": "PERSON", "value": "Dana Whitfield"})
    text = copy(web, tx)
    assert "Dana Whitfield" not in text and "Dana" not in text and re.search(r"\[PERSON_\d+\]", text)
    assert "Dana Whitfield" not in web.stored_text(tx)                         # the saved call is masked too
    with store_of(web) as s:
        assert "Dana Whitfield" not in s.list_messages(cid)[-1]["scrubbed_text"]


def test_the_transcript_tab_marks_a_name_hidden_after_the_save(web):
    cid, tx = missed_name_call(web)
    web.post(f"/clients/{cid}/registry/add", {"type": "PERSON", "value": "Dana Whitfield"})
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert re.search(r'<mark class="tag[^"]*">Dana Whitfield</mark>', page)


def test_a_change_request_hides_a_name_added_after_the_save(web):
    cid, tx = missed_name_call(web)
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Call with the client.", "import")
    web.post(f"/clients/{cid}/registry/add", {"type": "PERSON", "value": "Dana Whitfield"})
    r = web.post_json(f"/transcripts/{tx}/outputs/{NOTE}/request-change", {"text": "shorten it", "version": 1})
    assert r.status_code == 200 and "Dana Whitfield" not in r.json()["text"]


def test_a_word_kept_at_review_stays_as_written_when_the_name_is_added_later(web):
    cid, tx = missed_name_call(web)
    with store_of(web) as s:
        s.save_review_decision(tx, (0, 0), "Dana Whitfield", "keep")
    web.post(f"/clients/{cid}/registry/add", {"type": "PERSON", "value": "Dana Whitfield"})
    assert "Dana Whitfield" in copy(web, tx)


def test_the_sidebar_has_no_add_a_client_by_name_box(web):
    cid, tx, _ = make_call(web)
    for url in ("/", f"/clients/{cid}"):
        page = web.get(url).text
        assert "Add a client by name" not in page and 'action="/clients"' not in page and "New transcript" in page


def test_typed_boxes_are_kept_in_the_tab_and_a_leave_warning_covers_every_exit():
    assert "mwb-typed:" in JS and "forgetTyped" in JS and 'addEventListener("beforeunload"' in JS
    assert "textarea[data-keep]:not([data-change-text])" in JS


def test_the_check_command_accepts_a_name_restored_version(web):
    from app.check import check
    cid, tx, _ = make_call(web)
    with store_of(web) as s:
        n = s.load_registry(cid).lookup("PERSON", "Tomas Beltran")[0].n
        s.add_output(cid, tx, NOTE, f"[PERSON_{n}] asked about rent.", "import")
    web.post(f"/clients/{cid}/registry/delete", {"type": "PERSON", "n": str(n)})
    assert check(web.c.app.state.data_dir) == []
