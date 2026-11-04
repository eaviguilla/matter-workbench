"""UX round 4: one scope rule for words hidden for one transcript or for the client, in every box that takes typed text
about a transcript. A transcript-only name is replaced silently only when every place of its word was scrubbed. A word
kept at some places is asked about place by place. Hide beside a flagged word covers this transcript only unless the
client-wide box is ticked. Also the hidden names page, the archived bar, the settings Save and the import wording."""
import json
import re
from datetime import date

import pytest

from app import workflow as wf
from app.check import check
from app.outputs import SLUGS, TEXT_SLUGS
from app.scrub.registry import Registry
from app.store import Store
from tests.test_round3 import CALL, MAY, NOTE, change, code_of_may, each_form, may_case, review, store_of
from tests.webhelp import Session, make_app, review_form, saved_tx

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
JS = (ROOT / "app/web/static/app.js").read_text()


@pytest.fixture
def web(tmp_path):
    return Session(make_app(tmp_path))


def add_call(web, cid, text, title="", output=None, day=date(2026, 11, 2)):
    with store_of(web) as s:
        tx = s.add_transcript(cid, text, day, title)
        if output:
            s.add_output(cid, tx, NOTE, output)
        return tx


def preview(web, tx, text):
    return web.post_json(f"/transcripts/{tx}/scrub-preview", {"text": text}).json()


def place_of(web, tx, text):
    ask = preview(web, tx, text)["ask"][0]
    return [{"start": p["start"], "word": ask["word"]} for p in ask["places"]]


def choose(places, *choices):
    return [dict(p, choice=c) for p, c in zip(places, choices)]


def asked(response):
    return response.json()["text"].split("Change requested:\n", 1)[1].split("\n\n", 1)[0]


# ---- 1. a name hidden for one transcript, in typed text ------------------------------------------------------

def test_a_name_scrubbed_in_every_place_is_replaced_without_asking(web):
    cid = web.post("/clients", {"first_name": "Testn"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    page = web.post(f"/clients/{cid}/intake", {"text": CALL, "call_date": "2026-11-03"}).text
    tx = saved_tx(web.post(f"/clients/{cid}/intake/save", each_form(page, ["scrub"] * 6), follow_redirects=False))
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note.")
    code = code_of_may(web, cid)
    assert preview(web, tx, "She lives with May.") == {"flags": []}
    assert asked(change(web, tx, "She lives with May.")) == f"She lives with {code}."


def test_the_may_sample_asks_about_every_typed_place_and_never_sends_a_code_silently(web):
    cid, tx = may_case(web)
    code = code_of_may(web, cid)
    prev = preview(web, tx, "The lease renews in May.")
    assert prev["flags"] == ["May"] and prev["ask"][0]["code"] == code and len(prev["ask"][0]["places"]) == 1
    assert "renews in" in prev["ask"][0]["places"][0]["before"]
    for body in ({}, {"confirm": ["May"]}, {"places": [{"start": 999, "word": "May", "choice": "hide"}]}):
        r = change(web, tx, "The lease renews in May.", **body)
        assert r.status_code == 409 and r.json()["ask"][0]["word"] == "May"      # a tick or a wrong place settles nothing
    with store_of(web) as s:
        assert [m for m in s.list_messages(cid) if m["kind"] == "correction"] == []
    place = place_of(web, tx, "The lease renews in May.")
    month = change(web, tx, "The lease renews in May.", places=choose(place, "send"))
    assert asked(month) == "The lease renews in May."                              # the month is sent as written, on purpose
    person = change(web, tx, "The lease renews in May.", places=choose(place, "hide"))
    assert asked(person) == f"The lease renews in {code}."


def test_two_typed_places_get_two_separate_choices(web):
    cid, tx = may_case(web)
    code = code_of_may(web, cid)
    text = "May is moving out in May."
    places = place_of(web, tx, text)
    assert len(places) == 2
    assert change(web, tx, text, places=choose(places[:1], "hide")).status_code == 409        # one place left open
    r = change(web, tx, text, places=choose(places, "hide", "send"))
    assert asked(r) == f"{code} is moving out in May."


def test_directions_and_messages_ask_the_same_way(web):
    cid, tx = may_case(web)
    code = code_of_may(web, cid)
    place = place_of(web, tx, "renews in May")
    assert web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": "renews in May"}).status_code == 409
    sent = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": "renews in May",
                                                      "places": choose(place, "send")}).json()["text"]
    assert sent.split("Specific directions:\n", 1)[1].split("\n\n", 1)[0] == "renews in May" and code != "May"
    msg = {"text": "It renews in May.", "kind": "comment", "tx_id": tx}
    prev = web.post_json(f"/clients/{cid}/outgoing/preview", msg).json()
    assert prev["flags"] == ["May"] and prev["ask"][0]["code"] == code
    assert web.post_json(f"/clients/{cid}/outgoing/copy", dict(msg, confirm="1")).status_code == 409
    start = prev["ask"][0]["places"][0]["start"]
    ok = web.post_json(f"/clients/{cid}/outgoing/copy", dict(msg, places=[{"start": start, "word": "May", "choice": "send"}]))
    assert ok.status_code == 200 and "It renews in May." in ok.json()["text"]


def test_an_old_transcript_without_the_word_is_not_affected(web):
    cid, tx = may_case(web)
    other = add_call(web, cid, "[PERSON_9]: Hi there.")
    out = preview(web, other, "She lives with May.")
    assert out == {"flags": ["May"]}                                                 # plain flag, no code: the name is not hidden there


# ---- 2. the Hide beside a flagged word -------------------------------------------------------------------------------

def hide(web, tx, word, wide=False):
    return web.post_json(f"/transcripts/{tx}/hide-word", {"text": word, "client": wide})


def test_hide_in_a_box_is_for_this_transcript_only_and_never_reaches_other_text(web):
    cid, tx = may_case(web)
    tx2 = add_call(web, cid, "[PERSON_8]: Renewal talk. Then May came.", "Second call", "Renews in May.")
    other = add_call(web, cid, "[PERSON_8]: Another call. The month is May.", "Third call", "Also May.", date(2026, 11, 1))
    r = hide(web, tx2, "May")
    assert r.status_code == 200 and r.json()["scope"] == "transcript"
    new_code = r.json()["code"]
    assert new_code != code_of_may(web, cid)
    with store_of(web) as s:
        reg = s.load_registry(cid)
        ent = next(e for e in reg.entities if e.local and e.only == [tx2])
        assert ent.via == tx2 and reg.lookup("PERSON", "May") is None                # not a hidden name for the client
        assert wf.placeholder_text(s, cid, "Renews in May.", reg) == "Renews in May."         # Copy with hidden names, this call
        assert wf.placeholder_text(s, cid, s.list_outputs(other, NOTE)[-1]["content"], reg) == "Also May."   # another call
        check_ = wf.check_import(s, cid, "Renews in May.", other, False, NOTE)                # an import that mentions May
        assert check_.masked == 0 and check_.content == "Renews in May."
        new_call = wf.run_intake(s, cid, "• Ana Ruiz 0:01\nHello.\n• Bo Lund 0:06\nThe lease renews in May.\n",
                                 web.c.app.state.ner, wf.load_settings(s))
        assert "May" in new_call.scrubbed and [g.text for g in new_call.groups] == ["May"]    # a new transcript still shows the month
    third = preview(web, other, "the lease renews in May.")
    assert third == {"flags": ["May"]}                                               # and typed text about another call
    this = preview(web, tx2, "the lease renews in May.")
    assert this["ask"][0]["code"] == new_code                                        # this call knows it, asks per place (its text holds May)


def test_hide_for_this_transcript_replaces_the_word_when_the_call_never_wrote_it(web):
    cid, tx = may_case(web)
    r = hide(web, tx, "Zorbax")
    code = r.json()["code"]
    assert preview(web, tx, "Mention Zorbax.") == {"flags": []}
    assert asked(change(web, tx, "Mention Zorbax.")) == f"Mention {code}."
    other = add_call(web, cid, "[PERSON_8]: Hello.")
    assert preview(web, other, "Mention Zorbax.") == {"flags": ["Zorbax"]}


def test_the_client_wide_option_hides_it_everywhere_from_now_on(web):
    cid, tx = may_case(web)
    tx2 = add_call(web, cid, "[PERSON_8]: Renewal talk.", "Second call", "Renews in May.")
    r = hide(web, tx2, "May", wide=True)
    assert r.json()["scope"] == "client"
    with store_of(web) as s:
        reg = s.load_registry(cid)
        assert reg.lookup("PERSON", "May")
        assert wf.placeholder_text(s, cid, "Renews in May.", reg) != "Renews in May."
        assert wf.check_import(s, cid, "Renews in May.", tx2, False, NOTE).masked == 1
        assert next(e for e in reg.entities if e.forms.get(None) == "May" and not e.local).via == tx2
    assert hide(web, tx2, "   ").status_code == 400
    assert hide(web, tx2, "[PERSON_1]").status_code == 400


def test_a_word_hidden_for_the_transcript_can_be_made_client_wide_later_and_keeps_its_code(web):
    cid, tx = may_case(web)
    first = hide(web, tx, "Zorbax").json()
    second = hide(web, tx, "Zorbax", wide=True).json()
    assert second["scope"] == "client" and second["code"] == first["code"]
    with store_of(web) as s:
        reg = s.load_registry(cid)
        assert reg.lookup("PERSON", "Zorbax")[0].placeholder() == first["code"] and not reg.lookup("PERSON", "Zorbax")[0].local


def test_hide_in_a_message_with_no_transcript_can_only_be_for_the_client(web):
    cid, tx = may_case(web)
    r = web.post_json(f"/clients/{cid}/outgoing/hide-word", {"text": "Zorbax", "tx_id": ""})
    assert r.status_code == 200 and r.json()["scope"] == "client"
    r = web.post_json(f"/clients/{cid}/outgoing/hide-word", {"text": "Quillfield", "tx_id": tx})
    assert r.json()["scope"] == "transcript"
    assert web.post_json(f"/clients/{cid}/outgoing/hide-word", {"text": "Quillfield", "tx_id": "TX-20200101-1"}).status_code == 400
    page = web.get(f"/clients/{cid}/outgoing").text
    assert "data-msg-flags" in page and "data-hide-url" in page and "data-msg-text" in page


def test_the_registry_round_trip_keeps_the_transcript_link():
    reg = Registry()
    ent = reg.add_local_person("May", new=True)
    ent.only, ent.via = ["TX-20261103-1"], "TX-20261103-1"
    again = Registry.from_dict(json.loads(json.dumps(reg.to_dict())))
    assert again.entities[0].only == ["TX-20261103-1"] and again.entities[0].via == "TX-20261103-1" and again.entities[0].local
    plain = Registry()
    plain.add_local_person("May")
    assert "only" not in plain.to_dict()["entities"][0] and "via" not in plain.to_dict()["entities"][0]
    assert plain.add_local_person("May") is plain.entities[0] and plain.add_local_person("May", new=True) is not plain.entities[0]


# ---- 4. a word already kept at review -------------------------------------------------------------------------

KEEP_CALL = "• Ana Ruiz 0:01\nHello there.\n• Bo Lund 0:06\nWe met Quillfield at noon.\n"


def test_a_word_kept_at_review_is_not_flagged_in_typed_text_about_that_transcript(web):
    cid, page = review(web, KEEP_CALL)
    form = review_form(page, "keep")
    tx = saved_tx(web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False))
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note.")
    assert preview(web, tx, "Mention Quillfield and Zorbax.") == {"flags": ["Zorbax"]}
    assert asked(change(web, tx, "Mention Quillfield.")).endswith("Mention Quillfield.")
    other = add_call(web, cid, "[PERSON_8]: Hello.")
    assert preview(web, other, "Mention Quillfield.") == {"flags": ["Quillfield"]}          # only for the transcript it was kept in


def test_the_review_page_uses_the_choices_on_the_page_before_saving(web):
    cid, page = review(web, KEEP_CALL)
    form = review_form(page, "keep")
    form["directions"] = "Mention Quillfield and Zorbax."
    got = web.post(f"/clients/{cid}/intake/directions-preview", form).json()
    assert got == {"flags": ["Zorbax"]}
    scrub = review_form(page, "scrub")
    scrub["directions"] = "Mention Quillfield."
    assert web.post(f"/clients/{cid}/intake/directions-preview", scrub).json() == {"flags": []}     # hidden, so not flagged either


def test_a_kept_word_that_is_also_a_hidden_person_is_still_asked_about(web):
    cid, tx = may_case(web)
    with store_of(web) as s:
        assert s.decided_keep(tx, "May") and not s.decided_keep(tx, "Zorbax")
    assert preview(web, tx, "In May.")["ask"]                                       # kept as a month, hidden as a person: asked


# ---- 6. the review box says what Hide will do -----------------------------------------------------------------

def test_the_review_page_names_the_scope_of_each_word_hidden_in_the_directions(web):
    cid, page = review(web, KEEP_CALL)
    form = review_form(page, "keep")
    form.update(directions="Say Zorbax and Frobnitz and Gleeb.", dir_hide="Zorbax", dir_hide_client="Frobnitz")
    r = web.post(f"/clients/{cid}/intake/save", form)
    assert "Zorbax will be hidden for this transcript" in r.text
    assert "Frobnitz will be hidden for this client from now on" in r.text
    assert 'name="dir_hide" value="Zorbax"' in r.text and 'name="dir_hide_client" value="Frobnitz"' in r.text
    form["dir_confirm"] = "Gleeb"
    tx = saved_tx(web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False))
    with store_of(web) as s:
        reg = s.load_registry(cid)
        z = next(e for e in reg.entities if e.forms.get(None) == "Zorbax")
        f = reg.lookup("PERSON", "Frobnitz")[0]
        assert z.local and z.only == [tx] and z.via == tx and not f.local and f.via == tx and reg.lookup("PERSON", "Zorbax") is None
    # the transcript-only word is not matched in a later transcript of this client
    later = web.post(f"/clients/{cid}/intake", {"text": "• Ana Ruiz 0:01\nHi.\n• Bo Lund 0:06\nZorbax came.\n", "call_date": "2026-11-03"}).text
    assert "Zorbax" in later and "data-flag" in later


# ---- 7. hidden names page ---------------------------------------------------------------------------------------

def test_the_hidden_names_page_says_where_a_row_came_from_and_confirms_a_delete(web):
    cid, tx = may_case(web)
    hide(web, tx, "Zorbax")
    hide(web, tx, "Frobnitz", wide=True)
    page = web.get(f"/clients/{cid}/registry").text
    assert "Only in Sister rent question" in page
    assert page.count("Added from a message on Sister rent question") == 1
    with store_of(web) as s:
        n = s.load_registry(cid).lookup("PERSON", "Frobnitz")[0].n
    r = web.post(f"/clients/{cid}/registry/delete", {"type": "PERSON", "n": str(n)}, follow_redirects=False)
    assert r.status_code == 303 and "Frobnitz" not in r.headers["location"] and "?" not in r.headers["location"]
    after = web.get(r.headers["location"]).text
    assert "Unscrubbed Frobnitz" in after and 'name="value_full" value="Frobnitz"' not in after
    assert "Unscrubbed" not in web.get(f"/clients/{cid}/registry").text                 # shown once


# ---- 3. a stale refusal keeps the typed text ------------------------------------------------------------------------

def test_the_change_box_keeps_its_text_across_the_reload_a_stale_version_asks_for(web):
    cid, tx = may_case(web)
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert f'data-store-key="change-{tx}-{NOTE}"' in page and "data-stale-version" in page
    assert "so nothing was copied" in page and "is kept and will be there after the reload" in page
    assert "sessionStorage" in JS and "keepTyped(cbox, ctext.value)" in JS and "keepTyped(cbox, \"\")" in JS
    assert "if (saved && field.value === \"\")" in JS


# ---- 8, 9, 10. small wording and layout --------------------------------------------------------------------------

def test_the_archived_bar_reads_hidden_from_the_client_list_and_the_page_stays_usable(web):
    cid, tx = may_case(web)
    web.post(f"/clients/{cid}/archive", follow_redirects=False)
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    bar = re.search(r'<form[^>]*class="archivebar".*?</form>', page, re.S).group()
    assert "Archived. Hidden from the client list." in bar and ">Restore</button>" in bar
    assert "data-change" in page and 'data-nav-select' in page and "Add transcript" in page      # still the working page


def test_the_settings_connector_save_button_is_only_for_pages_without_script(web):
    page = web.get("/settings").text
    form = re.search(r'<form[^>]*data-autosave[^>]*>(.*?)</form>', page, re.S).group(1)
    assert re.search(r"<noscript><button type=\"submit\">Save</button></noscript>", form)
    assert "<button" not in re.sub(r"<noscript>.*?</noscript>", "", form, flags=re.S)


def test_the_import_check_says_a_new_version_for_one_output_and_new_versions_for_more(web):
    cid, tx = may_case(web)
    one = web.post(f"/clients/{cid}/import", {"text": "A reply.", "kind": "output", "tx_id": tx, "output": TEXT_SLUGS[2]}).text
    assert "Import as a new version</button>" in one and "as a new version:" in one and "new versions" not in one
    two = web.post(f"/clients/{cid}/import", {"text": "[OUTPUT: clio-note]\nOne.\n[OUTPUT: clio-form-note]\nTwo.", "kind": "output", "tx_id": tx}).text
    assert "Import as new versions</button>" in two and "as new versions:" in two


# ---- 5. the selection popup (the logic is in app.js, which a browser check drives) -------------------------------------

def test_the_selection_button_snaps_to_whole_words_and_trims_lowercase_ends():
    assert "function snapWords(" in JS and "\\p{Ll}" in JS and "\\p{L}" in JS
    assert "if (!tokens.length) { return \"\"; }" in JS        # nothing capitalised or no whole word: no button


# ---- the repair --------------------------------------------------------------------------------------------------------

def test_check_validates_the_new_registry_fields_and_reports_no_stored_value(tmp_path):
    web = Session(make_app(tmp_path))
    cid, tx = may_case(web)
    hide(web, tx, "Zorbax")
    folder = web.c.app.state.data_dir
    assert check(folder) == []
    path = folder / "clients" / cid / "client.json"
    doc = json.loads(path.read_text())
    doc["registry"]["entities"][-1]["only"] = "TX-1"
    path.write_text(json.dumps(doc))
    problems = check(folder)
    assert problems and all("Zorbax" not in p for p in problems) and any("only" in p for p in problems)
