"""The one client page: call selector, Outputs and Transcript views, version controls, Scrub this, per-place review,
call titles, directions, request-verb friction, the summary header, and a whole flow through HTTP across a restart."""
import html as h
import importlib.util
import json
import re
import runpy
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app import workflow as wf
from app.outputs import SLUGS, TEXT_SLUGS
from app.scrub.ner import NerModel
from app.scrub.pipeline import ScrubConfig, scrub_message, scrub_transcript
from app.scrub.registry import Registry
from app.store import Store
from app.web import create_app
from tests.fake_ner import FakeBackend
from tests.webhelp import Session, make_app, review_form, saved_tx

NOTE, CAL, FORM = TEXT_SLUGS
ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "models" / "gliner_pii"
needs_model = pytest.mark.skipif(not (REAL / "model_quantized.onnx").exists()
                                 or importlib.util.find_spec("onnxruntime") is None, reason="real model not installed")
CALL = "• Ana Ruiz 0:01\nHello there.\n• Bo Lund 0:06\nMy sister May called me. We meet on 20 May.\n"
PLAIN = "Hartley Quimby is the landlord."


def store_of(web) -> Store:
    app = web.c.app
    return Store.open(app.state.data_dir, env={}, home=app.state.home)


def new_store(tmp_path) -> Store:
    """A store that has read nothing before, as a restarted app would."""
    return Store.open(tmp_path / "data", env={}, home=tmp_path / "home")


@pytest.fixture
def env(tmp_path):
    """Maria with three calls (1 Oct, 15 Oct, 2 Nov). Only the newest has outputs, a title and a copy."""
    web = Session(make_app(tmp_path))
    cid = web.post("/clients", {"first_name": "Maria"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    with store_of(web) as s:
        reg = Registry()
        reg.add_person("Maria Lopez")
        s.save_registry(cid, reg)
        txs = []
        for day, title in ((date(2026, 10, 1), ""), (date(2026, 10, 15), "Lease follow-up"), (date(2026, 11, 2), "Repair deadline")):
            tx = s.add_transcript(cid, f"[PERSON_1]: Call on {day}. {PLAIN}", day, title)
            s.set_transcript_status(tx, "reviewed")
            txs.append(tx)
        for n in range(1, 10):
            s.add_output(cid, txs[2], NOTE, f"Note v{n} for [PERSON_1].", "mcp" if n % 2 else "import")
        s.add_output(cid, txs[2], CAL, "Calendar one.")
        s.add_output(cid, txs[2], CAL, "Calendar two.", "edit")
        s.set_requested_outputs(txs[2], [NOTE, CAL])
        s.set_transcript_status(txs[2], "copied")
    return web, cid, txs, tmp_path


def option(page, tx):
    return re.search(rf'<option value="{tx}" data-id="{tx}"( selected)?>([^<]*)</option>', page)


def column(page, slug):
    return re.search(rf'<section class="col" id="out-{slug}">(.*?)</section>', page, re.S).group(1)


# ---- selecting a call ---------------------------------------------------------------------------------

def test_the_newest_call_is_selected_when_no_call_is_named(env):
    web, cid, txs, _ = env
    page = web.get(f"/clients/{cid}").text
    assert option(page, txs[2]).group(1) and not option(page, txs[1]).group(1) and "1 of 3" in page
    assert f'data-poll="/transcripts/{txs[2]}/latest"' in page          # polling follows the selected call


def test_a_named_call_is_selected_and_an_unknown_one_is_a_404(env):
    web, cid, txs, _ = env
    page = web.get(f"/clients/{cid}?tx={txs[1]}").text
    assert option(page, txs[1]).group(1) and not option(page, txs[2]).group(1) and "2 of 3" in page
    for bad in ("TX-20200101-1", "nonsense", "TX-20261102-99", "../etc"):
        assert web.get(f"/clients/{cid}?tx={bad}").status_code == 404
    other = web.post("/clients", {"first_name": "Zed"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    assert web.get(f"/clients/{other}?tx={txs[1]}").status_code == 404           # a call of another client
    assert "No transcripts yet" in web.get(f"/clients/{other}").text


def test_the_selector_lists_newest_first_with_arrows_and_a_position_label(env):
    web, cid, txs, _ = env
    page = web.get(f"/clients/{cid}?tx={txs[1]}").text
    values = re.findall(r'<option value="(TX-[^"]+)"', page)
    assert values == [txs[2], txs[1], txs[0]]
    assert option(page, txs[1]).group(2) == "Lease follow-up, 15 Oct 2026, Ready to copy"
    assert option(page, txs[2]).group(2) == "Repair deadline, 2 Nov 2026, 2 of 2 outputs received"
    assert option(page, txs[0]).group(2) == "Untitled, 1 Oct 2026, Ready to copy"          # the title leads and the ID is not read out
    older = re.search(r'<a class="arrow" href="([^"]*)"[^>]*aria-label="Older transcript"', page).group(1)
    newer = re.search(r'<a class="arrow" href="([^"]*)"[^>]*aria-label="Newer transcript"', page).group(1)
    assert older == f"/clients/{cid}?tx={txs[0]}" and newer == f"/clients/{cid}?tx={txs[2]}"
    newest = web.get(f"/clients/{cid}").text                      # at the ends the arrow is disabled, not a link
    assert 'aria-label="Newer transcript"' not in re.sub(r'<span class="arrow off".*?</span>', "", newest, flags=re.S)
    assert re.search(r'<span class="arrow off" aria-disabled="true" aria-label="Newer transcript, none">', newest)
    oldest = web.get(f"/clients/{cid}?tx={txs[0]}").text
    assert re.search(r'<span class="arrow off" aria-disabled="true" aria-label="Older transcript, none">', oldest)
    assert re.search(r'<form method="get" action="/clients/[^"]+" class="pickform" data-nav-form>.*?<noscript><button', page, re.S)


def test_the_old_call_address_redirects_to_the_client_page_with_its_choices(env):
    web, cid, txs, _ = env
    r = web.get(f"/transcripts/{txs[2]}?{NOTE}=4&cmp-{NOTE}=prev&{CAL}=1", follow_redirects=False)
    assert r.status_code == 303
    loc = urlparse(r.headers["location"])
    assert loc.path == f"/clients/{cid}"
    assert parse_qs(loc.query) == {"tx": [txs[2]], "view": ["outputs"], NOTE: ["4"], f"cmp-{NOTE}": ["prev"], CAL: ["1"]}
    plain = web.get(f"/transcripts/{txs[0]}", follow_redirects=False)
    assert parse_qs(urlparse(plain.headers["location"]).query) == {"tx": [txs[0]]}
    assert web.get("/transcripts/TX-20200101-1", follow_redirects=False).status_code == 404
    page = web.get(f"/transcripts/{txs[2]}?{NOTE}=4").text
    assert "Note v4 for Maria Lopez." in column(page, NOTE)              # a browser follows it to the right version


def test_the_view_opens_on_the_transcript_until_something_is_asked_or_received(env):
    web, cid, txs, _ = env
    quiet = web.get(f"/clients/{cid}?tx={txs[1]}").text
    assert 'id="scrubbed-view"' in quiet and 'class="board"' not in quiet and "Scrub this" in quiet
    busy = web.get(f"/clients/{cid}").text
    assert 'class="board"' in busy and 'id="scrubbed-view"' not in busy and "Request more outputs" in busy
    assert 'id="scrubbed-view"' in web.get(f"/clients/{cid}?tx={txs[2]}&view=transcript").text
    asked = web.get(f"/clients/{cid}?tx={txs[1]}&view=outputs").text
    assert asked.count("Not requested") == 5 and 'class="board"' in asked
    assert 'id="scrubbed-view"' in web.get(f"/clients/{cid}?tx={txs[1]}&view=sideways").text      # unknown means the default
    web.post_json(f"/transcripts/{txs[1]}/copy", {"outputs": [NOTE]})
    assert 'class="board"' in web.get(f"/clients/{cid}?tx={txs[1]}").text and "Waiting for Claude" in web.get(f"/clients/{cid}?tx={txs[1]}").text


def test_the_switch_links_keep_the_selected_call(env):
    web, cid, txs, _ = env
    page = web.get(f"/clients/{cid}?tx={txs[1]}").text
    nav = re.search(r'<nav class="viewswitch".*?</nav>', page, re.S).group(0)
    hrefs = [h.unescape(x) for x in re.findall(r'href="([^"]*)"', nav)]
    assert hrefs == [f"/clients/{cid}?tx={txs[1]}&view=outputs", f"/clients/{cid}?tx={txs[1]}&view=transcript"]
    assert re.findall(r">([^<]+)</a>", nav) == ["Outputs", "Transcript"] and 'aria-current="page"' in nav
    for href in hrefs:
        assert option(web.get(href).text, txs[1]).group(1)


def test_the_transcript_view_holds_the_text_the_checklist_directions_and_copy_button(env):
    web, cid, txs, _ = env
    page = web.get(f"/clients/{cid}?tx={txs[1]}").text
    order = ["Transcript", 'id="scrubbed-view"', "Ask Claude for", "Specific directions for Claude", "Copy for Claude", "Scrub this"]
    spots = [page.index(m) for m in order]
    assert spots == sorted(spots)
    assert page.count('name="output"') == 5 and "<details class=\"request\"" not in page
    assert 'data-after-copy="' in page and 'class="legend"' in page


def test_the_selector_row_shows_only_the_status_and_edit_title(env):
    web, cid, txs, _ = env
    page = web.get(f"/clients/{cid}?tx={txs[1]}").text
    row = re.search(r'<div class="titlerow">(.*?)</details>', page, re.S).group(1)
    assert "Edit title" in row and "data-tx-status" in row and "Lease follow-up</span>" not in row and "No title" not in page
    assert option(page, txs[1]).group(2).startswith("Lease follow-up, 15 Oct 2026")      # the title is read first in the option


def test_each_output_has_one_copy_button_and_quiet_text_actions_and_no_saved_from_line(env):
    web, cid, txs, _ = env
    note = column(web.get(f"/clients/{cid}").text, NOTE)
    actions = re.search(r'<div class="actions copyrow">(.*?)</div>', note, re.S).group(1)
    assert actions.count("<button") == 2 and actions.count('class="textbtn"') == 2      # Copy is the only plain button
    assert re.search(r'<button type="button" data-copy-text="#out-rehydrated-%s"[^>]*>Copy</button>' % NOTE, actions)
    assert 'class="textbtn" data-copy-text="#out-raw-%s">Copy with hidden names' % NOTE in actions and ">Edit</a>" in actions
    assert "from a pasted reply" not in note and "Unused placeholders" not in note and "Unused hidden names" not in note and "saved 20" not in note


def test_sidebar_rows_are_the_name_then_the_id_with_no_date(env):
    web, cid, txs, _ = env
    page = web.get(f"/clients/{cid}").text
    row = re.search(r'<li class="current"><a href="/clients/%s"[^>]*>(.*?)</a>' % re.escape(cid), page, re.S) or \
        re.search(r'<li class="current">\s*<a href="/clients/%s"[^>]*>(.*?)</a>' % re.escape(cid), page, re.S)
    assert row and 'aria-current="page"' in row.group(0)
    assert re.findall(r'class="(cname|cid)"', row.group(1)) == ["cname", "cid"] and "clast" not in page


# ---- version controls ---------------------------------------------------------------------------------

def test_each_output_has_arrows_a_select_and_a_back_to_latest_link_only_when_older(env):
    web, cid, txs, _ = env
    page = web.get(f"/clients/{cid}").text
    note = column(page, NOTE)
    options = re.findall(r'<option value="(\d+)"( selected)?>([^<]*)</option>', note.split('name="cmp-')[0])
    assert [o[0] for o in options] == [str(n) for n in range(9, 0, -1)]
    today = wf.short_day(Store.open(web.c.app.state.data_dir, env={}, home=web.c.app.state.home).list_outputs(txs[2], NOTE)[8]["created_at"])
    assert options[0][2] == f"v9 latest, {today}, Claude" and options[1][2] == f"v8, {today}, Pasted"
    assert options[0][1] and "Back to latest" not in note and "No newer version" in note
    older = column(web.get(f"/clients/{cid}?{NOTE}=4").text, NOTE)
    assert re.search(r'<option value="4" selected>v4, ', older) and "Back to latest" in older and "Note v4 for Maria Lopez." in older
    back = h.unescape(re.search(r'<a class="backlatest" href="([^"]*)"', older).group(1))
    assert back.startswith(f"/clients/{cid}?tx={txs[2]}&view=outputs") and f"{NOTE}=" not in back
    assert "Note v9 for Maria Lopez." in column(web.get(back).text, NOTE)
    hand = column(web.get(f"/clients/{cid}?{CAL}=2").text, CAL)
    assert "Hand edit" in hand and "Calendar two." in hand


def test_the_version_select_has_the_same_shape_at_any_count(env):
    web, cid, txs, _ = env
    page = web.get(f"/clients/{cid}").text
    shape = lambda col: re.sub(r"<option.*?</option>", "<o>", re.search(r'<form method="get".*?</form>', col, re.S).group(0), flags=re.S)
    assert shape(column(page, NOTE)).count("<select") == 2 and shape(column(page, CAL)).count("<select") == 2
    assert "Note v1" not in page and column(page, FORM).count("<select") == 0       # an empty column has none


def test_choosing_in_one_column_leaves_the_other_columns_alone(env):
    web, cid, txs, _ = env
    page = web.get(f"/clients/{cid}?{NOTE}=3&{CAL}=1").text
    assert "Note v3" in column(page, NOTE) and "Calendar one." in column(page, CAL)
    cal_hidden = dict(re.findall(r'<input type="hidden" name="([^"]*)" value="([^"]*)">', column(page, CAL)))
    note_hidden = dict(re.findall(r'<input type="hidden" name="([^"]*)" value="([^"]*)">', column(page, NOTE)))
    assert cal_hidden == {"tx": txs[2], "view": "outputs", NOTE: "3"}               # a column carries the others' choices
    assert note_hidden == {"tx": txs[2], "view": "outputs", CAL: "1"}               # and never its own
    only_cal = web.get(f"/clients/{cid}?{CAL}=1").text
    assert "Note v9" in column(only_cal, NOTE) and "Calendar one." in column(only_cal, CAL)
    arrows = re.findall(r'class="arrow" href="([^"]*)"', column(page, CAL))
    assert arrows and all(f"{NOTE}=3" in h.unescape(a) and f"{CAL}=" in h.unescape(a) for a in arrows)


def test_compare_with_offers_off_previous_and_each_version(env):
    web, cid, txs, _ = env
    page = web.get(f"/clients/{cid}").text
    sel = re.search(rf'<select id="cmp-{NOTE}".*?</select>', column(page, NOTE), re.S).group(0)
    assert re.findall(r'<option value="([^"]*)"', sel) == ["", "prev", "7", "6", "5", "4", "3", "2", "1"]   # v8 is "prev"
    assert re.findall(r">([^<]+)</option>", sel)[:3] == ["Off", "Previous, v8", "v7"]
    assert "Changes from" not in column(page, NOTE)
    prev = web.get(f"/clients/{cid}?cmp-{NOTE}=prev").text
    assert "Changes from v8 to v9" in column(prev, NOTE) and '<option value="prev" selected>' in column(prev, NOTE)
    assert "Changes from v2 to v9" in column(web.get(f"/clients/{cid}?cmp-{NOTE}=2").text, NOTE)
    assert "Changes from" not in column(web.get(f"/clients/{cid}?cmp-{NOTE}=prev").text, CAL)
    first = web.get(f"/clients/{cid}?{NOTE}=1&cmp-{NOTE}=prev").text                # nothing before v1
    assert "Changes from" not in column(first, NOTE) and 'value="prev"' not in column(first, NOTE)


# ---- Scrub this on a saved call --------------------------------------------------------------------------

def hide(web, tx, text, kind="PERSON", **kw):
    return web.post(f"/transcripts/{tx}/hide", {"text": text, "type": kind}, follow_redirects=False, **kw)


def client_json(tmp_path, cid) -> bytes:
    return (tmp_path / "data" / "clients" / cid / "client.json").read_bytes()


@pytest.fixture
def seen(env):
    """The newest call, which was copied and has outputs; its transcript and its note v9 hold a name in plain text."""
    web, cid, txs, tmp = env
    with store_of(web) as s:
        s.add_output(cid, txs[2], NOTE, f"Note v10 for [PERSON_1]. {PLAIN}", "import")
        s.add_output(cid, txs[2], FORM, "Form text with nobody in it.", "import")
    return web, cid, txs[2], tmp


def test_hide_this_hides_the_word_in_the_transcript_and_masks_outputs_that_hold_it(seen):
    web, cid, tx, tmp = seen
    r = hide(web, tx, "Hartley Quimby")
    assert r.status_code == 303
    loc = r.headers["location"]
    assert "Hartley" not in loc and "Quimby" not in loc and parse_qs(urlparse(loc).query)["hid"] == ["1"]
    with new_store(tmp) as s:
        text = s.get_transcript(tx)["scrubbed_text"]
        assert "Hartley" not in text and "Quimby" not in text and "[PERSON_2] is the landlord." in text
        notes = s.list_outputs(tx, NOTE)
        assert len(notes) == 10 + 1 and notes[-1]["source"] == "hide" and notes[-1]["content"].endswith("[PERSON_2] is the landlord.")
        assert "Hartley Quimby" in notes[-2]["content"]                      # history stays, the new version is the safe one
        assert len(s.list_outputs(tx, CAL)) == 2 and len(s.list_outputs(tx, FORM)) == 1       # nothing else changed
        reg = s.load_registry(cid)
        assert reg.lookup("PERSON", "Hartley Quimby") and reg.lookup("PERSON", "Quimby")
    page = web.get(loc).text
    assert "Hidden in 1 place in the transcript and in 1 output" in page and "no undo" in page
    assert "Claude already received this transcript, so text it holds cannot be changed" in page
    with new_store(tmp) as s:
        shown = s.list_audit()[-1]
    assert shown["action"] == "transcript_hidden" and shown["client_id"] == cid and shown["transcript_id"] == tx
    assert set(shown) == {"id", "at", "action", "client_id", "transcript_id", "bytes"} and shown["bytes"] > 0
    assert "Quimby" not in (tmp / "data" / "audit.jsonl").read_text(encoding="utf-8")


def test_hide_this_counts_every_whole_word_place_and_leaves_longer_words_alone(env):
    web, cid, txs, tmp = env
    tx = txs[1]
    with store_of(web) as s:
        s.update_scrubbed_text(tx, "Rob met Robert. Rob's car. Rob, Rob. Robbing is not Rob-like? Rob")
    r = hide(web, tx, "Rob")
    assert r.status_code == 303 and parse_qs(urlparse(r.headers["location"]).query)["hid"] == ["6"]
    with new_store(tmp) as s:
        text = s.get_transcript(tx)["scrubbed_text"]
    assert text == "[PERSON_2] met Robert. [PERSON_2]'s car. [PERSON_2], [PERSON_2]. Robbing is not [PERSON_2]-like? [PERSON_2]"
    page = web.get(r.headers["location"]).text
    assert "Hidden in 6 places" in page and "Claude already received" not in page       # never copied, no outputs


def test_hide_this_works_for_an_email_and_an_address(env):
    web, cid, txs, tmp = env
    tx = txs[0]
    with store_of(web) as s:
        s.update_scrubbed_text(tx, "Write to Kim.Reed@Example.org or kim.reed@example.org. She lives at 9 Elm Road, Testville.")
    assert hide(web, tx, "kim.reed@example.org", "EMAIL").status_code == 303
    assert hide(web, tx, "9 Elm Road", "ADDRESS").status_code == 303
    with new_store(tmp) as s:
        assert s.get_transcript(tx)["scrubbed_text"] == "Write to [EMAIL_1] or [EMAIL_1]. She lives at [ADDRESS_1], Testville."


@pytest.mark.parametrize("text, kind, why", [
    ("", "PERSON", "Select or type"), ("   ", "PERSON", "Select or type"), ("x" * 201, "PERSON", "over 200 characters"),
    ("[PERSON_1]", "PERSON", "overlaps a hidden name"), ("PERSON_1", "PERSON", "overlaps a hidden name"),
    ("person", "PERSON", "overlaps a hidden name"), ("a [PERS", "PERSON", "overlaps a hidden name"),
    ("Nobody Here", "PERSON", "not in this transcript"), ("Hartley", "SECRET", "Choose Person"),
])
def test_hide_this_refuses_empty_long_overlapping_and_missing_text(seen, text, kind, why):
    web, cid, tx, tmp = seen
    before = client_json(tmp, cid)
    files = {p: p.read_bytes() for p in (tmp / "data" / "clients" / cid).rglob("*.*")}
    r = web.post(f"/transcripts/{tx}/hide", {"text": text, "type": kind}, follow_redirects=False)
    assert r.status_code == 400 and why in r.text and "Scrub this" in r.text          # the form comes back with the reason
    assert client_json(tmp, cid) == before
    assert {p: p.read_bytes() for p in (tmp / "data" / "clients" / cid).rglob("*.*")} == files
    assert web.post(f"/transcripts/{tx}/hide", {"text": text, "type": kind, "csrf": "bad"}).status_code == 403


def test_hide_this_without_a_csrf_token_is_refused_and_unknown_calls_are_404(env):
    web, cid, txs, _ = env
    assert web.c.post(f"/transcripts/{txs[1]}/hide", data={"text": "Maria", "type": "PERSON"}).status_code == 403
    assert hide(web, "TX-20200101-1", "x").status_code == 404


def test_a_copied_call_shows_the_warning_before_hiding_and_a_quiet_one_does_not(env):
    web, cid, txs, _ = env
    assert "cannot be changed" in web.get(f"/clients/{cid}?tx={txs[2]}&view=transcript").text
    assert "cannot be changed" not in web.get(f"/clients/{cid}?tx={txs[1]}").text


@pytest.mark.parametrize("step, nth", [("before_client", 1), ("after_client", 1), ("later_file", 1), ("later_file", 2)])
def test_a_crash_at_any_save_step_while_hiding_leaves_a_state_that_a_retry_completes(seen, step, nth):
    web, cid, tx, tmp = seen
    seen_steps = []

    def boom(name):
        if name == step:
            seen_steps.append(name)
            if len(seen_steps) == nth:
                raise RuntimeError("power cut")
    Store.fault = boom
    try:
        with new_store(tmp) as s, pytest.raises(RuntimeError):
            wf.hide_in_transcript(s, cid, tx, "PERSON", "Hartley Quimby")
    finally:
        Store.fault = None
    with new_store(tmp) as s:
        reg = s.load_registry(cid)
        text = s.get_transcript(tx)["scrubbed_text"]
        known = {e.placeholder() for e in reg.entities}
        for ph in re.findall(r"\[(?:PERSON|EMAIL|ADDRESS)_\d+\]", text + "".join(o["content"] for o in s.list_outputs(tx, NOTE))):
            assert ph in known                       # a placeholder on disk always has its registry entry
        assert len(s.list_outputs(tx, NOTE)) in (10, 11)
    with new_store(tmp) as s:
        done = "Quimby" not in s.get_transcript(tx)["scrubbed_text"] and "Quimby" not in s.list_outputs(tx, NOTE)[-1]["content"]
        if done:                                     # the crash came after the last file, so the work was already complete
            with pytest.raises(wf.ImportProblem):
                wf.hide_in_transcript(s, cid, tx, "PERSON", "Hartley Quimby")
        else:
            result = wf.hide_in_transcript(s, cid, tx, "PERSON", "Hartley Quimby")
            assert result.places + result.outputs >= 1
    with new_store(tmp) as s:
        assert "Quimby" not in s.get_transcript(tx)["scrubbed_text"]
        notes = s.list_outputs(tx, NOTE)
        assert len(notes) == 11 and "Quimby" not in notes[-1]["content"]          # one masked version, however many tries
        with pytest.raises(wf.ImportProblem):
            wf.hide_in_transcript(s, cid, tx, "PERSON", "Hartley Quimby")        # a third time finds nothing to do


# ---- call titles -------------------------------------------------------------------------------------------

def review_page(web, cid, text, day="2026-11-02"):
    return web.post(f"/clients/{cid}/intake", {"text": text, "call_date": day}).text


def test_a_title_is_stored_as_typed_with_no_flagged_word_check(env):
    web, cid, txs, tmp = env
    page = review_page(web, cid, "• Maria Lopez 0:01\nHello there.\n• Bo Lund 0:06\nWe talked about the roof.\n", "2026-11-01")
    assert 'name="title"' in page and "never sent to Claude" in page and "title_ok" not in page
    form = review_form(page)
    form["title"] = "  Call with   Maria Lopez about the roof "
    r = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    assert r.status_code == 303                                   # capitalized words in a title never block the save
    tx = saved_tx(r)
    with new_store(tmp) as s:
        assert s.get_transcript(tx)["title"] == "Call with Maria Lopez about the roof"      # real name, spaces tidied
    shown = web.get(f"/clients/{cid}?tx={tx}").text
    assert "Edit title" in shown and 'value="Call with Maria Lopez about the roof"' in shown
    assert option(shown, tx).group(2).startswith("Call with Maria Lopez about the roof, 1 Nov 2026")
    assert 'class="calltitle"' not in shown and "No title" not in shown          # the selector line is not repeated


def test_the_edit_title_form_saves_clears_and_limits_a_title(env):
    web, cid, txs, tmp = env
    tx = txs[0]
    r = web.post(f"/transcripts/{tx}/title", {"title": "Roof talk with Maria Lopez and Zephyr"}, follow_redirects=False)
    assert r.status_code == 303                                   # no tick needed for capitalized words
    with new_store(tmp) as s:
        assert s.get_transcript(tx)["title"] == "Roof talk with Maria Lopez and Zephyr"
    page = web.get(r.headers["location"]).text
    assert "Title saved." in page and "Roof talk with Maria Lopez and Zephyr" in page and "title_ok" not in page
    too_long = web.post(f"/transcripts/{tx}/title", {"title": "x" * 121})
    assert too_long.status_code == 400 and "over 120 characters" in too_long.text
    cleared = web.post(f"/transcripts/{tx}/title", {"title": "  "}, follow_redirects=False)
    assert "Title removed." in web.get(cleared.headers["location"]).text
    with new_store(tmp) as s:
        assert s.get_transcript(tx)["title"] == ""
    assert web.c.post(f"/transcripts/{tx}/title", data={"title": "x"}).status_code == 403


def test_a_title_with_a_real_name_never_reaches_any_text_for_claude(env):
    web, cid, txs, tmp = env
    tx = txs[2]
    title = "Zed Brightwater lease for Maria Lopez"
    assert web.post(f"/transcripts/{tx}/title", {"title": title}, follow_redirects=False).status_code == 303
    assert title in web.get(f"/clients/{cid}?tx={tx}").text                   # shown on screen
    copied = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE, CAL]}).json()["text"]
    asked = web.post_json(f"/transcripts/{tx}/outputs/{NOTE}/request-change", {"text": "Shorten it.", "version": 3}).json()["text"]
    other = web.post_json(f"/transcripts/{txs[1]}/copy", {"outputs": [NOTE]}).json()["text"]
    for text in (copied, asked, other):
        assert "Brightwater" not in text and "Lopez" not in text and "lease for" not in text
    with new_store(tmp) as s:
        assert all("lease for" not in m["scrubbed_text"] for m in s.list_messages(cid))


def test_the_title_field_is_checked_by_the_data_folder_check(env):
    from app.check import check
    web, cid, txs, tmp = env
    assert check(tmp / "data") == []
    path = tmp / "data" / "clients" / cid / "client.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["transcripts"][txs[0]]["title"] = 5
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert any("field title is not str" in p for p in check(tmp / "data"))


# ---- a hidden word in older versions ---------------------------------------------------------------------------

def _output_files(tmp, cid, tx):
    return {p.name: p.read_bytes() for p in sorted((tmp / "data" / "clients" / cid / "transcripts" / tx).glob("*.json"))}


def _hidden_later(env):
    """Maria's newest call. v1 of the note holds Hartley Quimby in plain text; Scrub this then masks only v2."""
    web, cid, txs, tmp = env
    tx = txs[2]
    with store_of(web) as s:
        s.add_output(cid, tx, FORM, "Form v1: Hartley Quimby signs on 5 Nov.", "import")
        s.add_output(cid, tx, FORM, "Form v2 mentions Hartley Quimby again.", "import")
        wf.hide_in_transcript(s, cid, tx, "PERSON", "Hartley Quimby")
        assert len(s.list_outputs(tx, FORM)) == 3 and "Quimby" in s.list_outputs(tx, FORM)[0]["content"]
    return web, cid, tx, tmp


def test_a_word_hidden_later_is_left_out_of_a_change_request_for_an_older_version(env):
    web, cid, tx, tmp = _hidden_later(env)
    before = _output_files(tmp, cid, tx)
    r = web.post_json(f"/transcripts/{tx}/outputs/{FORM}/request-change", {"text": "Shorten it.", "version": 1})
    assert r.status_code == 200
    text = r.json()["text"]
    assert "Quimby" not in text and re.search(r"Form v1: \[PERSON_\d+\] signs on 5 Nov\.", text)
    assert _output_files(tmp, cid, tx) == before                       # history is not rewritten
    assert b"Quimby" in before[f"{FORM}.json"]
    with new_store(tmp) as s:
        assert all("Quimby" not in m["scrubbed_text"] for m in s.list_messages(cid))


def test_the_placeholder_copy_target_and_edit_form_of_an_older_version_hide_the_word(env):
    web, cid, tx, tmp = _hidden_later(env)
    before = _output_files(tmp, cid, tx)
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs&{FORM}=1").text
    raw = re.search(r'<pre class="hidden-text" id="out-raw-%s">(.*?)</pre>' % FORM, page, re.S).group(1)
    assert "Quimby" not in raw and re.search(r"Form v1: \[PERSON_\d+\] signs", raw)
    shown = re.search(r'<pre class="text" id="out-rehydrated-%s">(.*?)</pre>' % FORM, page, re.S).group(1)
    assert "Hartley Quimby" in h.unescape(shown)                        # the screen still shows the real name
    edit = web.get(f"/transcripts/{tx}/outputs/{FORM}/edit?v=1").text
    assert "Quimby" not in edit and re.search(r"Form v1: \[PERSON_\d+\] signs", h.unescape(edit))
    assert _output_files(tmp, cid, tx) == before


# ---- directions ---------------------------------------------------------------------------------------------

def copy(web, tx, directions, **extra):
    return web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE, FORM], "directions": directions, **extra})


def test_directions_are_scrubbed_ordered_and_saved_as_a_comment(env):
    web, cid, txs, tmp = env
    r = copy(web, txs[1], "Ask Maria Lopez about the roof. Please keep it short.")
    assert r.status_code == 200
    text = r.json()["text"]
    body = text.replace(f"[CLIENT: {cid} | TX: {txs[1]}]", "")
    assert "Lopez" not in text and "Maria" not in body and "Ask [PERSON_1] about the roof." in text
    marks = ["Outputs to write: Clio Note (clio-note), Clio form note (clio-form-note).", "Specific directions:\nAsk", f"[CLIENT: {cid} | TX: {txs[1]}]",
             "[PERSON_1]: Call on"]
    spots = [text.index(m) for m in marks]
    assert spots == sorted(spots) and len(set(spots)) == len(spots)
    with new_store(tmp) as s:
        comments = [m for m in s.list_messages(cid) if m["kind"] == "comment"]
        assert len(comments) == 1 and comments[0]["transcript_id"] == txs[1] and comments[0]["scrubbed_text"] == \
            "Ask [PERSON_1] about the roof. Please keep it short."
        assert "Lopez" not in json.dumps(s.list_messages(cid)) and s.get_transcript(txs[1])["status"] == "copied"
    plain = copy(web, txs[0], "").json()["text"]
    assert "Specific directions" not in plain


def test_flagged_words_in_directions_block_the_copy_until_confirmed_and_store_nothing(env):
    web, cid, txs, tmp = env
    r = copy(web, txs[1], "Add that Zephyr called.")
    assert r.status_code == 409 and r.json()["flags"] == ["Zephyr"]
    with new_store(tmp) as s:
        assert s.list_messages(cid) == [] and s.get_transcript(txs[1])["status"] == "reviewed"
    ok = copy(web, txs[1], "Add that Zephyr called.", confirm=["Zephyr"])
    assert ok.status_code == 200 and "Add that Zephyr called." in ok.json()["text"]
    with new_store(tmp) as s:
        assert [m["kind"] for m in s.list_messages(cid)] == ["transcript", "comment"]


def test_the_copy_button_still_needs_a_tick_and_the_review_to_be_done(env):
    web, cid, txs, _ = env
    assert web.post_json(f"/transcripts/{txs[1]}/copy", {"outputs": [], "directions": "x"}).status_code == 400
    with store_of(web) as s:
        s.set_transcript_status(txs[0], "draft")
    assert web.post_json(f"/transcripts/{txs[0]}/copy", {"outputs": [NOTE]}).status_code == 409


# ---- request verbs and sentence openers ------------------------------------------------------------------

def flags_of(text, plain):
    reg = Registry()
    reg.add_person("Maria Lopez")
    return [f.text for f in scrub_message(text, reg, ScrubConfig(), None, plain_requests=plain).flags]


@pytest.mark.parametrize("word", ["Shorten", "Add", "Remove", "Change", "Use", "Make", "Rewrite", "Fix", "Keep", "Delete",
                                  "Include", "Replace", "Move", "Update", "Explain", "List", "Please", "Try"])
def test_plain_request_verbs_opening_a_sentence_are_not_flagged_in_requests(word):
    assert flags_of(f"{word} the date in the note. {word} the second line too.", plain=True) == []


def test_request_verbs_are_still_flagged_elsewhere_and_other_capitals_stay_flagged():
    assert "Shorten" in flags_of("Shorten the note.", plain=False)                  # an ordinary message
    assert flags_of("Then Shorten it.", plain=True) == ["Shorten"]                   # in the middle of a sentence
    assert flags_of("Shorten it. Zephyr called.", plain=True) == ["Zephyr"]
    assert flags_of("Shorten it for Mark.", plain=True) == ["Mark"]
    for name in ("Mark", "Will", "Bill", "Grant", "Rob", "Chase", "Frank", "May"):   # names are never on the list
        assert flags_of(f"{name} called.", plain=True) == [name]


def test_a_known_name_at_the_start_of_a_request_is_still_scrubbed():
    reg = Registry()
    reg.add_person("Maria Lopez")
    out = scrub_message("Maria said hello. Shorten it.", reg, ScrubConfig(), None, plain_requests=True)
    assert out.text == "[PERSON_1.first] said hello. Shorten it." and out.flags == []


def test_the_transcript_review_still_flags_a_verb_opening_a_sentence():
    text = "• Ana Ruiz 0:01\nHello there.\n• Bo Lund 0:06\nShorten the visit.\n"
    assert "Shorten" in [f.text for f in scrub_transcript(text, Registry()).flags]


def test_a_change_request_with_plain_verbs_needs_no_confirmation(env):
    web, cid, txs, _ = env
    r = web.post_json(f"/transcripts/{txs[2]}/outputs/{NOTE}/request-change", {"text": "Shorten it. Add the deadline."})
    assert r.status_code == 200
    mid = web.post_json(f"/transcripts/{txs[2]}/outputs/{NOTE}/request-change", {"text": "Please Shorten it."})
    assert mid.status_code == 409 and mid.json()["flags"] == ["Shorten"]
    msg = web.post_json(f"/clients/{cid}/outgoing/copy", {"text": "Shorten it.", "kind": "comment"})
    assert msg.status_code == 409                                                     # the Message page is not relaxed


# ---- the summary header -------------------------------------------------------------------------------------

def test_an_imported_summary_does_not_keep_its_header_line(env):
    web, cid, txs, tmp = env
    header = f"[CLIENT: {cid} | TX: {txs[2]}]"
    text = f"{header}\nSummary of [PERSON_1]'s case so far.\nMore on [PERSON_1]."
    chk = web.post(f"/clients/{cid}/import", {"text": text, "kind": "summary"})
    saved = web.post(f"/clients/{cid}/import/save", {"content": h.unescape(re.search(
        r'<textarea name="content"[^>]*>(.*?)</textarea>', chk.text, re.S).group(1)), "kind": "summary"}, follow_redirects=False)
    assert saved.status_code == 303
    with new_store(tmp) as s:
        summaries = [m["scrubbed_text"] for m in s.list_messages(cid) if m["kind"] == "summary"]
    assert summaries == ["Summary of [PERSON_1]'s case so far.\nMore on [PERSON_1]."] and "[CLIENT" not in summaries[0]
    assert "[CLIENT" not in "".join(m["scrubbed_text"] for m in new_store(tmp).list_messages(cid))
    unknown = f"[CLIENT: {cid} | TX: TX-20200101-1]\nAnother summary."          # a header naming a call that is not here
    chk = web.post(f"/clients/{cid}/import", {"text": unknown, "kind": "summary"})
    web.post(f"/clients/{cid}/import/save", {"content": h.unescape(re.search(
        r'<textarea name="content"[^>]*>(.*?)</textarea>', chk.text, re.S).group(1)), "kind": "summary"})
    with new_store(tmp) as s:
        assert [m["scrubbed_text"] for m in s.list_messages(cid) if m["kind"] == "summary"][-1] == "Another summary."


# ---- review: choose each place -------------------------------------------------------------------------------

def each_form(page, choices):
    """The review form with 'Choose each place' for the first flagged word, and one choice per place."""
    form = review_form(page)
    form["d0"] = "each"
    for j, choice in enumerate(choices):
        form[f"p0_{j}"] = choice
    return form


def flagged_words(page):
    return [h.unescape(w) for w in re.findall(r'<input type="hidden" name="w\d+" value="([^"]*)">', page)]


def test_the_review_lists_every_place_with_its_own_choice(env):
    web, cid, txs, _ = env
    text = "• Ana Ruiz 0:01\nHello.\n• Bo Lund 0:06\n" + " ".join(f"Then May {n} came." for n in range(1, 8)) + "\n"
    page = review_page(web, cid, text)
    assert flagged_words(page) == ["May"]
    assert page.count('data-place>') == 7 and 'value="each" data-each' in page and "and 4 more" in page
    assert len(re.findall(r'name="p0_\d" value="scrub"', page)) == 7
    spans = re.search(r'name="s0" value="([^"]*)"', page).group(1).split(",")
    cleaned = h.unescape(re.search(r'<textarea name="text"[^>]*>(.*?)</textarea>', page, re.S).group(1))
    assert len(spans) == 7 and all(cleaned[int(a):int(b)] == "May" for a, b in (s.split(":") for s in spans))
    single = review_page(web, cid, "• Ana Ruiz 0:01\nHello.\n• Bo Lund 0:06\nMy sister May called.\n")
    assert "data-each" not in single                                 # one place has nothing to choose between


def test_only_the_chosen_places_are_scrubbed_and_the_others_stay_as_written(env):
    web, cid, txs, tmp = env
    page = review_page(web, cid, CALL)
    assert flagged_words(page) == ["May"]
    spans = re.search(r'name="s0" value="([^"]*)"', page).group(1)
    r = web.post(f"/clients/{cid}/intake/save", each_form(page, ["scrub", "keep"]), follow_redirects=False)
    assert r.status_code == 303
    tx = saved_tx(r)
    with new_store(tmp) as s:
        text = s.get_transcript(tx)["scrubbed_text"]
        n = s.load_registry(cid).entity("PERSON", int(re.search(r"sister \[PERSON_(\d+)\] called", text).group(1))).n
        assert re.search(rf"My sister \[PERSON_{n}\] called me\. We meet on 20 May\.\n$", text) and text.count("May") == 1
        decisions = s.list_review_decisions(tx)
        assert sorted((d["span"], d["decision"]) for d in decisions) == sorted(zip(spans.split(","), ["scrub", "keep"]))
        reg = s.load_registry(cid)
        ent = reg.entity("PERSON", n)
        assert ent.local and ent.forms[None] == "May" and reg.lookup("PERSON", "May") is None      # not known for other text
        assert wf.view_output(s, cid, f"Call [PERSON_{n}] back.")[0].text == "Call May back."       # but it restores
    later = review_page(web, cid, "• Ana Ruiz 0:01\nHello.\n• Bo Lund 0:06\nMay is a good month. My niece is May.\n", "2026-11-03")
    assert flagged_words(later) == ["May"]                           # the word is still asked about next time


def test_scrub_and_keep_for_all_places_work_as_before(env):
    web, cid, txs, tmp = env
    page = review_page(web, cid, CALL)
    form = review_form(page, "scrub")
    tx = saved_tx(web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False))
    with new_store(tmp) as s:
        text = s.get_transcript(tx)["scrubbed_text"]
        n = s.load_registry(cid).lookup("PERSON", "May")[0].n
        assert "May" not in text and text.count(f"[PERSON_{n}]") == 2
        assert not s.load_registry(cid).entity("PERSON", n).local    # scrubbed the normal way, so it is known afterwards
    page = review_page(web, cid, CALL.replace("sister", "friend"), "2026-11-03")
    assert flagged_words(page) == []                                 # known now, nothing to ask
    other = web.post("/clients", {"first_name": "Zed"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    form = review_form(review_page(web, other, CALL), "keep")
    tx2 = saved_tx(web.post(f"/clients/{other}/intake/save", form, follow_redirects=False))
    with new_store(tmp) as s:
        assert s.get_transcript(tx2)["scrubbed_text"].count("May") == 2


def test_rescan_and_the_carry_field_keep_per_place_choices(env):
    web, cid, txs, tmp = env
    text = CALL + "• Ana Ruiz 0:20\nThen Zephyr arrived.\n"
    page = review_page(web, cid, text)
    assert flagged_words(page) == ["May", "Zephyr"]
    form = each_form(page, ["scrub", "keep"])
    del form["d1"]                                                   # nothing chosen for Zephyr yet
    form["extra_type"], form["extra_text"] = "PERSON", "Hello"
    again = web.post(f"/clients/{cid}/intake/rescan", form)
    assert flagged_words(again.text) == ["Zephyr"]                   # May is decided at both places and not asked again
    carry = json.loads(h.unescape(re.search(r'name="carry" value="([^"]*)"', again.text).group(1)))
    assert sorted((d["decision"], d["each"]) for d in carry["decisions"]) == [("keep", True), ("scrub", True)]
    form2 = review_form(again.text, "scrub")
    assert "May" not in form2.get("w0", "") and form2["carry"]
    saved = web.post(f"/clients/{cid}/intake/save", form2, follow_redirects=False)
    assert saved.status_code == 303
    with new_store(tmp) as s:
        body = s.get_transcript(saved_tx(saved))["scrubbed_text"]
    assert "20 May" in body and "sister [PERSON_" in body and "Zephyr" not in body


def test_moved_offsets_are_not_trusted(env):
    web, cid, txs, tmp = env
    page = review_page(web, cid, CALL)
    form = each_form(page, ["scrub", "keep"])
    form["s0"] = ",".join(f"{int(a) + 1}:{int(b) + 1}" for a, b in (p.split(":") for p in form["s0"].split(",")))
    r = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    assert r.status_code == 200 and "still need a decision" in r.text and "May" in flagged_words(r.text)
    with new_store(tmp) as s:
        assert len(s.list_transcripts(cid)) == 3
    form = each_form(page, ["scrub"])                                # a place with no choice is not decided
    assert web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False).status_code == 200


def test_the_page_text_is_the_cleaned_text_so_offsets_survive_crlf_and_hidden_characters(env):
    web, cid, txs, tmp = env
    messy = "﻿• Ana Ruiz 0:01\r\nHello.\r\n• Bo Lund 0:06\r\nMy sister Ma​y called me. Then May came. And Ma​y again. We meet on 20 May.\r\n"
    page = review_page(web, cid, messy)
    words = flagged_words(page)
    assert "May" in words
    i = words.index("May")
    form = review_form(page)
    form[f"d{i}"] = "each"
    spans = form[f"s{i}"].split(",")
    for j in range(len(spans)):
        form[f"p{i}_{j}"] = "scrub" if j == 0 else "keep"
    form["text"] = form["text"].replace("\n", "\r\n")                # a browser posts line breaks as CRLF
    for k in [k for k in form if re.fullmatch(r"d\d+", k) and k != f"d{i}"]:
        form[k] = "scrub"
    r = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    assert r.status_code == 303
    with new_store(tmp) as s:
        text = s.get_transcript(saved_tx(r))["scrubbed_text"]
    assert text.count("May") == len(spans) - 1


@needs_model
def test_with_the_real_model_may_as_a_name_and_as_a_month_in_one_call(tmp_path):
    (tmp_path / "home").mkdir()
    web = Session(create_app(tmp_path / "data", env={}, home=tmp_path / "home", model_dir=REAL))
    cid = web.post("/clients", {"first_name": "Testn"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    sample = (ROOT / "samples" / "review_may.txt").read_text(encoding="utf-8")
    page = web.post(f"/clients/{cid}/intake", {"text": sample, "call_date": "2026-11-02"}).text
    words = flagged_words(page)
    assert words == ["May"], words
    form = review_form(page, "scrub")
    form["d0"] = "each"
    cleaned = h.unescape(form["text"])
    spans = [tuple(map(int, s.split(":"))) for s in form["s0"].split(",")]
    assert len(spans) == 6
    for j, (a, b) in enumerate(spans):
        before = cleaned[:a].split()[-1]                         # the word before: "sister", "did" and "that" are the name
        form[f"p0_{j}"] = "scrub" if before in ("sister", "did", "that") else "keep"
    assert [form[f"p0_{j}"] for j in range(6)].count("scrub") == 3
    r = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    assert r.status_code == 303, flagged_words(r.text)
    with new_store(tmp_path) as s:
        text = s.get_transcript(saved_tx(r))["scrubbed_text"]
    assert re.search(r"my sister \[PERSON_\d+\]\. She", text) and re.search(r"did \[PERSON_\d+\] start", text)
    assert re.search(r"that \[PERSON_\d+\] pays", text)
    assert "20 May" in text and "1 May next year" in text and "renews in May." in text and text.count("May") == 3


# ---- everything through HTTP, across a restart ---------------------------------------------------------------

def test_a_whole_working_session_survives_a_restart(tmp_path):
    def start():
        return Session(make_app(tmp_path))
    web = start()
    cid = web.post("/clients", {"first_name": "Maria"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    assert "Add transcript" in web.get(f"/clients/{cid}").text and "No transcripts yet" in web.get(f"/clients/{cid}").text
    # paste, and choose each place for May
    page = review_page(web, cid, "• Maria Lopez 0:01\nHello.\n• Bo Lund 0:06\nMy sister May called me. We meet on 20 May.\n", "2026-11-02")
    form = each_form(page, ["scrub", "keep"])
    form["title"] = "Roof talk with Maria Lopez"
    saved = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    tx = saved_tx(saved)
    first = web.get(saved.headers["location"]).text
    assert "Transcript saved" in first and 'id="scrubbed-view"' in first and "Roof talk with Maria Lopez" in first
    # copy with directions: the box and the copy are separate things, and the page then opens on the outputs
    r = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE, CAL], "directions": "Add Maria Lopez by role only."})
    assert r.status_code == 200 and "Lopez" not in r.json()["text"] and "Specific directions:\nAdd [PERSON_2]" in r.json()["text"]
    waiting = web.get(f"/clients/{cid}").text
    assert waiting.count("Waiting for Claude") == 2 and 'class="board"' in waiting
    # Claude's reply is pasted and saved
    reply = f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {NOTE}]\nCall with [PERSON_2] and [PERSON_1].\n[OUTPUT: {CAL}]\n20 May: deadline."
    chk = web.post(f"/clients/{cid}/import", {"text": reply, "kind": "output", "tx_id": tx})
    web.post(f"/clients/{cid}/import/save", {"content": h.unescape(re.search(r'<textarea name="content"[^>]*>(.*?)</textarea>', chk.text, re.S).group(1)),
                                            "kind": "output", "tx_id": tx})
    # ask for a change, paste the new version
    ask = web.post_json(f"/transcripts/{tx}/outputs/{NOTE}/request-change", {"text": "Shorten it.", "version": 1})
    assert ask.status_code == 200 and "Call with [PERSON_2] and [PERSON_1]." in ask.json()["text"]
    reply2 = f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {NOTE}]\nShort call with [PERSON_1]."
    chk = web.post(f"/clients/{cid}/import", {"text": reply2, "kind": "output", "tx_id": tx})
    web.post(f"/clients/{cid}/import/save", {"content": h.unescape(re.search(r'<textarea name="content"[^>]*>(.*?)</textarea>', chk.text, re.S).group(1)),
                                            "kind": "output", "tx_id": tx})
    # look at the older version
    old = web.get(f"/clients/{cid}?{NOTE}=1").text
    assert "Call with Maria Lopez and May." in column(old, NOTE) and "Back to latest" in column(old, NOTE)
    latest = web.get(f"/clients/{cid}").text
    assert "Short call with May." in column(latest, NOTE) and "v2 latest" in column(latest, NOTE)
    # restart: a new app on the same folder
    again = start()
    page = again.get(f"/clients/{cid}?tx={tx}").text
    assert option(page, tx).group(1) and "Roof talk with Maria Lopez" in page and "2 of 2 outputs received" in page
    assert "1 of 1" in page and "Waiting for Claude" not in page
    assert "Call with Maria Lopez and May." in column(again.get(f"/clients/{cid}?{NOTE}=1").text, NOTE)
    assert again.get(f"/transcripts/{tx}/latest").json() == {"version": 3}
    with new_store(tmp_path) as s:
        assert [m["kind"] for m in s.list_messages(cid)] == ["transcript", "comment", "correction"]
        assert s.get_transcript(tx)["title"] == "Roof talk with Maria Lopez" and len(s.list_outputs(tx, NOTE)) == 2
        assert "May" in s.get_transcript(tx)["scrubbed_text"] and "sister [PERSON_" in s.get_transcript(tx)["scrubbed_text"]
    on_disk = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "data" / "clients").rglob("*") if p.is_file() and p.name != "client.json")
    assert "Lopez" not in on_disk and "Maria" not in on_disk


# ---- the kept test cases ----------------------------------------------------------------------------------

def test_the_new_seed_cases_have_what_they_promise(tmp_path):
    seed = runpy.run_path(str(ROOT / "scripts" / "seed_test_cases.py"))
    with Store.open(tmp_path / "data", env={}, home=tmp_path) as s:
        seed["seed"](s)
    with Store.open(tmp_path / "data", env={}, home=tmp_path) as s:
        by = {c["first_name"]: c["id"] for c in s.list_clients(include_archived=True)}
        k = s.list_transcripts(by["Testk"])
        assert len(k) == 1 and [len(s.list_outputs(k[0]["id"], slug)) for slug in TEXT_SLUGS] == [9, 2, 2] and k[0]["title"]
        calls = s.list_transcripts(by["Testl"])
        states = {(len([1 for slug in TEXT_SLUGS if s.list_outputs(t["id"], slug)]), t["status"]) for t in calls}
        assert len(calls) == 40 and all(t["title"] for t in calls) and len(states) >= 4
        assert len({t["call_date"][:7] for t in calls}) >= 4
        m = s.list_transcripts(by["Testm"])[0]
        assert m["status"] == "copied" and "Hartley Quimby" in m["scrubbed_text"] and s.load_registry(by["Testm"]).lookup("PERSON", "Hartley Quimby") is None
        assert s.list_transcripts(by["Testn"]) == []
        for tx in [t["id"] for t in k + calls[:2]]:
            assert s.get_transcript(tx)["title"] != ""
        old = s.list_transcripts(by["Testa"])
        assert all(t["title"] == "" for t in old)                    # the first ten have no titles
    sample = (ROOT / "samples" / "review_may.txt").read_text(encoding="utf-8")
    assert sample.count("May") >= 4 and "sister May" in sample and "20 May" in sample
