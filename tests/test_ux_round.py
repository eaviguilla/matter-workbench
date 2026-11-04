"""The UX review round: review page checklist and directions, who the client is, live flagged words, Scrub this in the
Outputs view, word-level compare, settings sections, the hidden names editor and the small wording and state fixes."""
import html as h
import json
import re

import pytest

from app import workflow as wf
from app.check import check
from app.outputs import FORM_SLUGS, SLUGS, TEXT_SLUGS
from app.scrub.pipeline import ScrubConfig, scrub_message
from app.scrub.registry import Registry
from app.store import Store
from tests.webhelp import Session, fixture_text, make_app, review_form, saved_tx

NOTE, CAL, FORM = TEXT_SLUGS


@pytest.fixture
def web(tmp_path):
    return Session(make_app(tmp_path))


def store_of(web) -> Store:
    app = web.c.app
    return Store.open(app.state.data_dir, env={}, home=app.state.home)


def paste(web, text, day="2026-11-02"):
    return web.post("/intake", {"text": text, "call_date": day})


def save_call(web, text, day="2026-11-02", outputs=(), directions="", extra=None):
    """Paste a call as a new client, save its review, and return (client ID, transcript ID)."""
    r = paste(web, text, day)
    cid = re.search(r"/clients/([\w-]+)/intake/save", r.text).group(1)
    form = review_form(r.text)
    form.update(extra or {})
    if outputs:
        form["output"] = list(outputs)
    form["directions"] = directions
    saved = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    return cid, saved_tx(saved)


def add_client(web, first, people, office=()):
    """A saved client whose hidden names hold these full names (office ones marked)."""
    with store_of(web) as s:
        cid = s.create_client(first)
        reg = Registry()
        for name in people:
            ent = reg.add_person(name)[0]
            ent.office = name in office
        s.save_registry(cid, reg)
        s.add_transcript(cid, "[PERSON_1]: hello", None)
    return cid


# ---- 1. review page: checklist and directions ---------------------------------------------------------

def test_the_review_page_saves_the_checklist_and_scrubbed_directions_and_the_client_page_shows_them(web):
    r = paste(web, fixture_text(1))
    assert r.text.count('name="output"') == 5 and 'name="directions"' in r.text and "Specific directions for Claude" in r.text
    assert r.text.index("Specific directions for Claude") < r.text.index("data-gate-save")      # above Save
    cid, tx = save_call(web, fixture_text(1), outputs=[NOTE, FORM], directions="Mention Maria Lopez by role only.")
    with store_of(web) as s:
        row = s.get_transcript(tx)
        assert row["planned_outputs"] == [NOTE, FORM] and row["requested_outputs"] == [] and row["status"] == "reviewed"
        assert "Lopez" not in row["directions"] and "[PERSON_" in row["directions"]            # scrubbed before it is stored
        assert s.get_setting("last_outputs") == f"{NOTE},{FORM}"
        assert s.list_messages(cid) == []                                                       # nothing is copied on save
    page = web.get(f"/clients/{cid}?saved={tx}").text
    assert 'id="scrubbed-view"' in page and 'class="board"' not in page                         # opens on the Transcript view
    box = page.split("<legend>Ask Claude for</legend>")[1].split("</fieldset>")[0]
    assert re.findall(r'value="([a-z-]+)"( checked)?', box) == [(NOTE, " checked"), (CAL, ""), (FORM, " checked"), (FORM_SLUGS[0], ""), (FORM_SLUGS[1], "")]
    assert "Mention Maria Lopez by role only.</textarea>" in page         # real names in the box, because a copy scrubs them
    assert "Copy for Claude" in page and re.search(r'data-copy-url="[^"]*">Copy for Claude', page)   # enabled, not locked
    assert page.count("Transcript saved") == 1 and '<section class="saved"' not in page


def test_a_brand_new_clients_review_starts_from_the_last_choice_made_anywhere(web):
    save_call(web, fixture_text(1), outputs=[CAL, FORM])
    r = paste(web, fixture_text(3))
    box = r.text.split("<legend>Ask Claude for</legend>")[1].split("</fieldset>")[0]
    assert re.findall(r'value="([a-z-]+)"( checked)?', box) == [(NOTE, ""), (CAL, " checked"), (FORM, " checked"), (FORM_SLUGS[0], ""), (FORM_SLUGS[1], "")]


def test_flagged_words_in_review_directions_stop_the_save_until_confirmed(web):
    r = paste(web, fixture_text(1))
    cid = re.search(r"/clients/([\w-]+)/intake/save", r.text).group(1)
    form = review_form(r.text)
    form.update(output=[NOTE], directions="Ask Zephyr to call back.")
    held = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    assert held.status_code == 200 and "Not saved yet" in held.text and 'name="dir_confirm" value="Zephyr"' in held.text
    assert "Ask Zephyr to call back." in held.text and 'value="clio-note" checked' in held.text      # what was typed is kept
    with store_of(web) as s:
        assert s.list_transcripts(cid) == []
    form["dir_confirm"] = "Zephyr"
    ok = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    assert ok.status_code == 303
    with store_of(web) as s:
        assert s.get_transcript(saved_tx(ok))["directions"] == "Ask Zephyr to call back."


def test_copy_sends_the_saved_directions_and_keeps_them_until_cleared(web):
    cid, tx = save_call(web, fixture_text(1), outputs=[NOTE], directions="Keep it under 100 words.")
    page = web.get(f"/clients/{cid}?saved={tx}").text
    assert "Keep it under 100 words.</textarea>" in page
    text = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": "Keep it under 100 words."}).json()["text"]
    assert "Specific directions:\nKeep it under 100 words." in text
    with store_of(web) as s:
        assert s.get_transcript(tx)["directions"] == "Keep it under 100 words."          # kept, so a second copy sends them too
    assert "Keep it under 100 words.</textarea>" in web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    again = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": "Keep it under 100 words."}).json()["text"]
    assert "Specific directions:\nKeep it under 100 words." in again
    web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": ""})            # clearing the box clears them
    with store_of(web) as s:
        assert s.get_transcript(tx)["directions"] == ""
    assert "Keep it under 100 words.</textarea>" not in web.get(f"/clients/{cid}?tx={tx}&view=transcript").text


def test_check_py_checks_the_new_fields_and_the_name_hidden_source(tmp_path):
    web = Session(make_app(tmp_path))
    cid, tx = save_call(web, fixture_text(1), outputs=[NOTE], directions="Be brief.")
    folder = web.c.app.state.data_dir
    assert check(folder) == []
    path = folder / "clients" / cid / "client.json"
    doc = json.loads(path.read_text())
    doc["transcripts"][tx]["planned_outputs"] = ["nope"]
    doc["transcripts"][tx]["directions"] = 5
    path.write_text(json.dumps(doc))
    found = check(folder)
    assert any("planned_outputs" in p for p in found) and any("directions" in p for p in found)


# ---- 2. who is the client -----------------------------------------------------------------------------

SAM_FIRST = ("• Sam Officer 0:01\nThanks for calling the office. Who am I speaking with?\n"
             "• Rowan Fielding 0:10\nHello, this is Rowan. I am calling about the lease.\n")
CLIENT_FIRST = ("• Rowan Fielding 0:01\nHello, it is Rowan. I am calling about the lease.\n"
                "• Sam Officer 0:20\nThank you. When did the lease start?\n")


def detect(web, text):
    with store_of(web) as s:
        return wf.detect_client(s, text, web.c.app.state.ner, wf.load_settings(s))


def seeded_office(web, n=4):
    """n clients that all store the office speaker Sam Officer, and Rowan Fielding as one of them."""
    ids = {}
    for first, last in [("Rowan", "Fielding")] + [(f"Client{k}", f"Other{k}") for k in range(n - 1)]:
        ids[first] = add_client(web, first, [f"{first} {last}", "Sam Officer"])
    return ids


@pytest.mark.parametrize("text", [SAM_FIRST, CLIENT_FIRST])
def test_the_office_speaker_seen_in_every_client_does_not_match_them_all(web, text):
    ids = seeded_office(web)
    found = detect(web, text)
    assert [m["id"] for m in found.matches] == [ids["Rowan"]]                     # only the right client, and first
    assert found.matches[0]["via"] == "Rowan Fielding" and found.matches[0]["strong"]
    assert found.suggested == ""                                                  # Rowan is known and Sam is staff
    assert [p.full for p in found.people if p.likely_staff] == ["Sam Officer"]


def test_a_marked_office_speaker_is_ignored_even_in_one_client_and_a_new_person_is_suggested(web):
    cid = add_client(web, "Tomas", ["Tomas Beltran", "Dana Whitaker"], office=["Dana Whitaker"])
    text = "• Dana Whitaker 0:01\nThanks for calling.\n• Ines Ramos 0:08\nHello, it is Ines.\n"
    found = detect(web, text)
    assert found.matches == [] and found.suggested == "Ines"
    assert cid


def test_a_weak_first_name_match_is_named_and_ranks_below_a_full_name(web):
    ids = seeded_office(web, 2)
    other = add_client(web, "Ines", ["Ines Ramos"])
    text = ("• Sam Officer 0:01\nThanks for calling.\n• Rowan Fielding 0:08\nHello, it is Rowan, and my friend Ines Calder "
            "is with me.\n")
    found = detect(web, text)
    assert found.matches[0]["id"] == ids["Rowan"] and found.matches[0]["strong"]
    assert any(m["id"] == other and not m["strong"] and m["via"] == "Ines Calder" for m in found.matches)


def test_the_choose_page_names_the_matched_person_and_preselects_nothing(web):
    ids = seeded_office(web)
    r = paste(web, SAM_FIRST)
    assert "This looks like an existing client" in r.text and "Matched Rowan Fielding" in r.text
    assert r.text.count('name="client"') == 2 and "checked" not in r.text.split("<form")[1].split("</form>")[0]
    assert f'value="{ids["Client0"]}"' not in r.text                              # no other client is offered
    assert 'name="first_name" value=""' in r.text                                 # no name is prefilled
    assert "registry" not in re.sub(r'(?s)<script.*?</script>', "", r.text.split("<main")[1]).lower()
    none = web.post("/intake/start", {"text": SAM_FIRST, "call_date": "2026-11-02"})
    assert "Choose a client above" in none.text
    picked = web.post("/intake/start", {"text": SAM_FIRST, "call_date": "2026-11-02", "client": ids["Rowan"]})
    assert f"/clients/{ids['Rowan']}/intake/save" in picked.text


def test_an_unknown_caller_with_known_office_staff_becomes_a_new_client_not_a_match(web):
    seeded_office(web)
    text = "• Sam Officer 0:01\nThanks for calling.\n• Tomas Beltran 0:08\nHello, it is Tomas.\n"
    r = paste(web, text)
    assert "New client Tomas created from this transcript" in r.text and "Overview tab" not in r.text
    assert "open More, then Manage client" in r.text or "under More, then Manage client" in r.text


def test_saving_marks_the_office_speaker_and_later_calls_do_not_match_on_them(web):
    first = ("• Dana Whitaker 0:01\nThanks for calling. Is this Tomas?\n• Tomas Beltran 0:06\nYes, it is Tomas.\n")
    cid, _ = save_call(web, first)
    with store_of(web) as s:
        reg = s.load_registry(cid)
        assert reg.lookup("PERSON", "Dana Whitaker")[0].office and not reg.lookup("PERSON", "Tomas Beltran")[0].office
    later = "• Dana Whitaker 0:01\nThanks for calling.\n• Ines Ramos 0:08\nHello, it is Ines.\n"
    found = detect(web, later)
    assert found.matches == [] and found.suggested == "Ines"


# ---- 6. flagged words, Hide, the plain words -----------------------------------------------------------

def test_plain_instruction_words_are_not_flagged_but_a_possible_name_still_is():
    cfg = ScrubConfig()
    ok = "Shorten it - Next steps: add the date; Then mention Friday. Summary of the call. Also keep the Overview short."
    assert scrub_message(ok, Registry(), cfg, None, plain_requests=True).flags == []
    names = scrub_message("Add Zorbax and Will to the note.", Registry(), cfg, None, plain_requests=True).flags
    assert [f.text for f in names] == ["Zorbax", "Will"]                           # a word that is also a first name stays flagged
    assert [f.text for f in scrub_message("Say Next to Zorbax.", Registry(), cfg, None).flags] == ["Next", "Zorbax"]


def test_the_live_preview_flags_unknown_words_but_replaces_names_already_hidden(web):
    cid, tx = save_call(web, fixture_text(1))
    r = web.post_json(f"/transcripts/{tx}/scrub-preview", {"text": "Add Zorbax. Next, say Maria Lopez agreed. Ask Sam Whitaker."})
    assert r.status_code == 200 and r.json() == {"flags": ["Zorbax"]}
    assert web.post_json(f"/transcripts/{tx}/scrub-preview", {"text": "   "}).json() == {"flags": []}
    bad = web.c.post(f"/transcripts/{tx}/scrub-preview", json={"text": "x"})
    assert bad.status_code == 403                                                  # no CSRF header
    with store_of(web) as s:
        assert len(s.list_messages(cid)) == 0                                       # a preview stores nothing


def test_hide_beside_a_flagged_word_adds_it_to_hidden_names_and_the_word_is_then_replaced(web):
    cid, tx = save_call(web, fixture_text(1))
    out = web.post_json(f"/transcripts/{tx}/hide-word", {"text": "Zorbax"})
    assert out.status_code == 200 and re.fullmatch(r"\[PERSON_\d+\]", out.json()["code"])
    with store_of(web) as s:
        reg = s.load_registry(cid)
        assert reg.lookup("PERSON", "Zorbax") is None                               # round 4: this transcript only by default
        assert any(e.local and e.only == [tx] and e.forms.get(None) == "Zorbax" for e in reg.entities)
        assert s.list_outputs(tx, NOTE) == []                                       # nothing else was changed
    assert web.post_json(f"/transcripts/{tx}/scrub-preview", {"text": "Add Zorbax."}).json() == {"flags": []}
    sent = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": "Add Zorbax."}).json()["text"]
    assert "Zorbax" not in sent and f"Add {out.json()['code']}." in sent
    assert web.post_json(f"/transcripts/{tx}/hide-word", {"text": "   "}).status_code == 400
    assert web.post_json(f"/transcripts/{tx}/hide-word", {"text": "[PERSON_1]"}).status_code == 400


def test_a_flagged_word_hidden_this_way_leaves_the_transcript_and_outputs_alone(web):
    """Round 3 changed this: the Hide beside a flagged word changes only the text being sent. Rewriting the transcript
    is for the Scrub this form alone (it was the other way before, and the old test asserted the rewrite)."""
    cid, tx = save_call(web, fixture_text(1))
    with store_of(web) as s:
        text = s.get_transcript(tx)["scrubbed_text"] + "\n[PERSON_1]: Zorbax is the landlord."
        s.update_scrubbed_text(tx, text)
        s.add_output(cid, tx, NOTE, "Zorbax is the landlord.")
    assert web.post_json(f"/transcripts/{tx}/hide-word", {"text": "Zorbax"}).status_code == 200
    with store_of(web) as s:
        assert s.get_transcript(tx)["scrubbed_text"] == text
        assert [o["content"] for o in s.list_outputs(tx, NOTE)] == ["Zorbax is the landlord."]


# ---- 7 and 12. import page ----------------------------------------------------------------------------

def test_a_reply_without_output_lines_offers_the_output_of_the_latest_change_request(web):
    cid, tx = save_call(web, fixture_text(1))
    with store_of(web) as s:
        s.add_output(cid, tx, CAL, "Calendar one.")
        s.add_output(cid, tx, NOTE, "Note one.")
    assert web.post_json(f"/transcripts/{tx}/outputs/{CAL}/request-change", {"text": "Shorten it.", "version": 1}).status_code == 200
    r = web.post(f"/clients/{cid}/import", {"text": "A plain reply.", "kind": "output", "tx_id": tx})
    assert f'<option value="{CAL}" selected>' in r.text and f'<option value="{NOTE}" selected>' not in r.text
    assert web.post_json(f"/transcripts/{tx}/outputs/{NOTE}/request-change", {"text": "Add a date.", "version": 1}).status_code == 200
    r = web.post(f"/clients/{cid}/import", {"text": "A plain reply.", "kind": "output", "tx_id": tx})
    assert f'<option value="{NOTE}" selected>' in r.text
    with store_of(web) as s:
        assert [m["output"] for m in s.list_messages(cid) if m["kind"] == "correction"] == [CAL, NOTE]
    assert "Not used" not in r.text


def test_import_a_summary_opens_with_running_summary_chosen_and_the_return_says_saved_and_dates_it(web):
    cid, tx = save_call(web, fixture_text(1))
    assert f'href="/clients/{cid}/import?kind=summary"' in web.get(f"/clients/{cid}").text
    page = web.get(f"/clients/{cid}/import?kind=summary").text
    assert "Import a summary</h2>" in page and 'name="kind" value="summary"' in page      # the output and transcript selects are gone
    assert 'name="output"' not in page and 'name="tx_id"' not in page and "Import Claude" not in page
    chk = web.post(f"/clients/{cid}/import", {"text": "People: [PERSON_1] called about the lease.", "kind": "summary"})
    body = h.unescape(re.search(r'<textarea name="content"[^>]*>(.*?)</textarea>', chk.text, re.S).group(1))
    saved = web.post(f"/clients/{cid}/import/save", {"content": body, "kind": "summary"}, follow_redirects=False)
    assert saved.headers["location"] == f"/clients/{cid}?summary=saved"
    back = web.get(saved.headers["location"]).text
    assert "Summary saved." in back and re.search(r"<summary>Summary of \d+ \w{3} \d{4}</summary>", back)
    assert "Summary saved 1" not in back and '<details class="inner" open>' in back


# ---- 9 and 10. compare and Scrub this in the Outputs view ---------------------------------------------

def test_a_changed_line_marks_only_the_changed_words():
    rows = wf.diff_rows("The quick brown fox jumps.\nSame line.\nGone line here.", "The quick red fox jumps.\nSame line.\nNew line there.")
    assert rows[0] == ("del", [("The quick ", False), ("brown", True), (" fox jumps.", False)])
    assert rows[1] == ("add", [("The quick ", False), ("red", True), (" fox jumps.", False)])
    assert rows[2] == ("same", [("Same line.", False)])
    assert wf.diff_rows("a\nb", "a\nb") == [("same", [("a", False)]), ("same", [("b", False)])]
    assert wf.diff_rows("", "x") == [("add", [("x", True)])]


def test_compare_shows_word_marks_and_escapes_the_text(web):
    cid, tx = save_call(web, fixture_text(1))
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Hello <b>old</b> world, and the rest stays.")
        s.add_output(cid, tx, NOTE, "Hello <b>new</b> world, and the rest stays.")
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs&{NOTE}=2&cmp-{NOTE}=1").text
    diff = re.search(r'<pre class="text diff">(.*?)</pre>', page, re.S).group(1)
    assert '<mark class="w-del">' in diff and '<mark class="w-add">' in diff
    assert "&lt;b&gt;" in diff and "<b>" not in diff and "world, and the rest stays." in diff


@pytest.fixture
def seen(web):
    cid, tx = save_call(web, "• Ana Ruiz 0:01\nHello there.\n• Bo Lund 0:06\nHartley Quimby is the landlord.\n")
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Call. Hartley Quimby is the landlord.")
        s.set_requested_outputs(tx, [NOTE])
        s.set_transcript_status(tx, "copied")
    return web, cid, tx


def test_hide_this_is_on_the_transcript_view_only_and_labels_the_version_name_hidden(seen):
    web, cid, tx = seen
    outputs = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert "data-hide-form" not in outputs and "data-hide-source" not in outputs and 'id="hide-outputs"' not in outputs
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert 'name="view" value="transcript"' in page and "data-hide-source" in page and page.count("data-hide-form") == 1
    r = web.post(f"/transcripts/{tx}/hide", {"text": "Hartley Quimby", "type": "PERSON", "view": "transcript"}, follow_redirects=False)
    assert r.status_code == 303 and "view=transcript" in r.headers["location"] and "Hartley" not in r.headers["location"]
    with store_of(web) as s:
        versions = s.list_outputs(tx, NOTE)
        assert [v["source"] for v in versions] == ["import", "hide"] or [v["source"] for v in versions][-1] == "hide"
    shown = web.get(r.headers["location"].replace("view=transcript", "view=outputs")).text
    assert "v2 latest, " in shown and "Name hidden" in shown
    folder = web.c.app.state.data_dir
    assert check(folder) == []
    export = wf.export_markdown(Store.open(folder, env={}, home=web.c.app.state.home), cid)
    assert "name hidden" in export


def test_a_refused_hide_comes_back_on_the_transcript_view(seen):
    web, cid, tx = seen
    r = web.post(f"/transcripts/{tx}/hide", {"text": "Nobody Here", "type": "PERSON", "view": "transcript"})
    assert r.status_code == 400 and 'id="scrubbed-view"' in r.text and "not in this transcript" in r.text


# ---- 11, 15, 16, 17, 18, 19 --------------------------------------------------------------------------

def test_saving_a_title_keeps_the_view_and_the_version_choices(seen):
    web, cid, tx = seen
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs&{NOTE}=1").text
    form = re.search(r'<form method="post" action="/transcripts/[^"]+/title".*?</form>', page, re.S).group(0)
    assert 'name="view" value="outputs"' in form and f'name="{NOTE}" value="1"' in form
    r = web.post(f"/transcripts/{tx}/title", {"title": "Roof", "view": "outputs", NOTE: "1"}, follow_redirects=False)
    assert "view=outputs" in r.headers["location"] and f"{NOTE}=1" in r.headers["location"] and "titled=1" in r.headers["location"]
    r = web.post(f"/transcripts/{tx}/title", {"title": "Roof", "view": "bogus", NOTE: "x<"}, follow_redirects=False)
    assert "view=" not in r.headers["location"] and NOTE not in r.headers["location"]


def test_waiting_text_points_at_the_box_above_and_names_the_connector_only_when_it_is_on(seen):
    web, cid, tx = seen
    with store_of(web) as s:
        s.set_requested_outputs(tx, [NOTE, CAL])
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    col = re.search(rf'<section class="col" id="out-{CAL}">(.*?)</section>', page, re.S).group(1)
    assert "Waiting for Claude" in col and "Paste Claude's reply in the box above." in col and "connector" not in col
    assert page.index('id="paste"') < page.index('class="board"')                    # the paste box comes first while waiting
    with store_of(web) as s:
        wf.save_settings(s, wf.Settings(mcp_enabled=True))
    col = re.search(rf'<section class="col" id="out-{CAL}">(.*?)</section>', web.get(f"/clients/{cid}?tx={tx}&view=outputs").text, re.S).group(1)
    assert "connector" in col
    with store_of(web) as s:
        s.set_requested_outputs(tx, [NOTE])
    quiet = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert quiet.index('class="board"') < quiet.index('id="paste"')                   # nothing waiting, so it moves below


def test_not_requested_columns_offer_ask_claude_for_this(seen):
    web, cid, tx = seen
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    for slug in (CAL, FORM):
        col = re.search(rf'<section class="col" id="out-{slug}">(.*?)</section>', page, re.S).group(1)
        assert f'data-ask="{slug}"' in col and "Ask Claude for this" in col
    assert 'data-ask' not in re.search(rf'<section class="col" id="out-{NOTE}">(.*?)</section>', page, re.S).group(1)
    assert 'id="request-more"' in page and "<details class=\"request\"" not in page      # always open, below the outputs
    assert page.index('class="board"') < page.index('id="request-more"')


def test_disabled_copy_buttons_say_why(web):
    cid, tx = save_call(web, fixture_text(1))
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    assert re.search(r"disabled>Copy for Claude</button>\s*<span class=\"status-msg\" data-status data-reason=\"1\">Tick at least one output</span>", page)
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note.")
    out = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert re.search(r'disabled>Copy for Claude</button>\s*<span class="status-msg" data-status data-reason="1">Type a change first</span>', out)


def test_an_older_version_says_so_on_the_copy_button(seen):
    web, cid, tx = seen
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note two.")
    old = web.get(f"/clients/{cid}?tx={tx}&view=outputs&{NOTE}=1").text
    assert ">Copy v1 (older)</button>" in old and "Older version." in old
    latest = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert ">Copy</button>" in latest and "(older)" not in latest


def test_the_selector_leads_with_the_title_hides_the_id_and_has_a_filter_and_list_order_counter(web):
    cid, tx = save_call(web, fixture_text(1), extra={"title": "Lease follow-up"})
    second = web.post(f"/clients/{cid}/intake", {"text": fixture_text(1).replace("Hi,", "Hey,"), "call_date": "2026-10-01"})
    web.post(f"/clients/{cid}/intake/save", review_form(second.text), follow_redirects=False)
    page = web.get(f"/clients/{cid}?tx={tx}").text
    opts = re.findall(r'<option value="(TX-[^"]+)" data-id="[^"]+"[^>]*>([^<]*)</option>', page)
    assert opts[0][1].startswith("Lease follow-up, 2 Nov 2026") and opts[1][1].startswith("Untitled, 1 Oct 2026")
    assert all(tx_id not in text for tx_id, text in opts) and "1 of 2" in page
    assert 'data-tx-filter="#tx-select"' in page and 'id="tx-filter"' in page
    assert page.index('id="tx-filter"') < page.index('id="tx-select"')
    assert 'name="' not in re.search(r'<input id="tx-filter"[^>]*>', page).group(0)      # not part of the form
    assert "2 of 2" in web.get(f"/clients/{cid}?tx={opts[1][0]}").text


def test_statuses_use_plain_words(web):
    cid, tx = save_call(web, fixture_text(1))
    assert "Ready to copy" in web.get(f"/clients/{cid}").text
    web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE, CAL]})
    assert "Copied, waiting for Claude" in web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note.")
    assert "1 of 2 outputs received" in web.get(f"/clients/{cid}?tx={tx}&view=transcript").text


def test_an_archived_client_has_a_one_line_restore_bar_on_every_page(web):
    cid, tx = save_call(web, fixture_text(1))
    assert "archivebar" not in web.get(f"/clients/{cid}").text
    web.post(f"/clients/{cid}/archive", {}, follow_redirects=False)
    for url in (f"/clients/{cid}", f"/clients/{cid}/registry", f"/clients/{cid}/intake"):
        page = web.get(url).text
        assert re.search(rf'<form method="post" action="/clients/{cid}/archive" class="archivebar"[^>]*>.*?Archived\..*?Restore', page, re.S)
    r = web.post(f"/clients/{cid}/archive", {}, follow_redirects=False)
    assert r.headers["location"].endswith("done=restored") and "archivebar" not in web.get(f"/clients/{cid}").text


def test_the_manage_link_opens_more_and_manage_client(web):
    cid, tx = save_call(web, fixture_text(1))
    plain = web.get(f"/clients/{cid}").text
    assert 'id="manage"' in plain and '<details class="inner manage" id="manage">' in plain
    opened = web.get(f"/clients/{cid}?manage=1").text
    assert '<details class="inner manage" id="manage" open>' in opened
    saved = web.get(f"/clients/{cid}?saved={tx}").text
    assert f'href="/clients/{cid}?manage=1#manage"' in saved


# ---- 13. settings ----------------------------------------------------------------------------------------

def test_settings_sections_save_alone_in_place_and_use_plain_words(web):
    page = web.get("/settings").text
    assert page.count('<button type="submit">Save</button>') == 2 and "Reset to starter text" not in page
    assert "slug" not in page.lower() and ">clio-note<" not in page and "Confidence threshold" not in page
    assert "Download history with real names" in page and "Export history" not in page
    json_ok = lambda r: r.status_code == 200 and r.json() == {"ok": True}
    r = web.c.post("/settings", data={"csrf": web.token, "section": "connector", "mcp_enabled": "1"}, headers={"Accept": "application/json"})
    assert json_ok(r)
    r = web.c.post("/settings", data={"csrf": web.token, "section": "model", "threshold": "0.7", "idle_minutes": "20"}, headers={"Accept": "application/json"})
    assert json_ok(r)
    with store_of(web) as s:
        cfg = wf.load_settings(s)
        assert cfg.mcp_enabled and cfg.threshold == 0.7 and cfg.idle_minutes == 20      # one section never undoes another
    r = web.c.post("/settings", data={"csrf": web.token, "section": "model", "threshold": "9"}, headers={"Accept": "application/json"})
    assert r.status_code == 400 and "threshold" in r.json()["error"]
    r = web.c.post("/settings", data={"csrf": web.token, "section": "connector"}, headers={"Accept": "application/json"})
    with store_of(web) as s:
        assert not wf.load_settings(s).mcp_enabled and wf.load_settings(s).threshold == 0.7
    plain = web.post("/settings", {"section": "model", "threshold": "0.6", "idle_minutes": "5"}, follow_redirects=False)
    assert plain.status_code == 303 and plain.headers["location"] == "/settings?saved=model"
    assert "Saved." in web.get("/settings?saved=model").text


# ---- 14. hidden names ------------------------------------------------------------------------------------

def test_hidden_names_lead_with_the_value_group_a_person_and_save_once(web):
    cid, tx = save_call(web, fixture_text(1))
    page = web.get(f"/clients/{cid}/registry").text
    assert "Placeholder" not in page and "registry" not in re.sub(r"/registry|class=\"registry\"", "", page).lower().split("<main")[1]
    maria = re.search(r'<form method="post" action="/clients/[^"]+/registry/save" class="forms">(.*?)</form>', page, re.S)
    assert maria and page.count('class="formrow"') >= 3
    assert page.index("Full name") < page.index("[PERSON_")                               # the real value leads
    with store_of(web) as s:
        reg = s.load_registry(cid)
        ent = reg.lookup("PERSON", "Maria Lopez")[0]
    fields = {"type": "PERSON", "n": str(ent.n), "value_full": "Maria Lopez-Reyes", "value_first": "Maria", "value_last": "Lopez-Reyes", "office": "1"}
    r = web.post(f"/clients/{cid}/registry/save", fields, follow_redirects=False)
    assert r.status_code == 303
    with store_of(web) as s:
        ent = s.load_registry(cid).entity("PERSON", ent.n)
        assert ent.forms[None] == "Maria Lopez-Reyes" and ent.forms["last"] == "Lopez-Reyes" and ent.office
    assert re.search(r'<input type="checkbox" name="office" value="1" checked>', web.get(f"/clients/{cid}/registry").text)
    clash = web.post(f"/clients/{cid}/registry/save", {**fields, "value_first": "Sam", "office": ""})
    assert "already belongs" in clash.text
    with store_of(web) as s:
        assert s.load_registry(cid).entity("PERSON", ent.n).forms["first"] == "Maria"      # nothing partial was saved


def test_words_confirmed_on_the_review_page_are_not_asked_again_on_the_client_page(web):
    cid, tx = save_call(web, fixture_text(1), outputs=[NOTE], directions="Say hello to Zephyr.", extra={"dir_confirm": "Zephyr"})
    page = web.get(f"/clients/{cid}?saved={tx}").text
    assert "data-confirmed='[&#34;Zephyr&#34;]'" in page or 'data-confirmed=\'["Zephyr"]\'' in page
    web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": "Say hello to Zephyr.", "confirm": ["Zephyr"]})
    kept = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text         # the directions stay, so the confirmed word stays
    assert "data-confirmed='[&#34;Zephyr&#34;]'" in kept or 'data-confirmed=\'["Zephyr"]\'' in kept
    web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": ""})
    assert "data-confirmed='[]'" in web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
