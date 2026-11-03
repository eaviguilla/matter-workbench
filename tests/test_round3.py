"""UX round 3: names hidden in one transcript only (Choose each place) in typed text for Claude, the Hide beside a
flagged word, live flags in the review directions, stale versions, the Hidden names labels, Last sent, the import
check wording, the Name: text notice, the filter and the connector switch."""
import html as h
import json
import re

import pytest

from app import workflow as wf
from app.outputs import SLUGS
from app.scrub.parse import parse_lenient
from app.scrub.pipeline import ScrubConfig, scrub_message
from app.scrub.registry import Registry
from app.store import Store
from tests.webhelp import Session, make_app, review_form, saved_tx

NOTE, CAL, FORM = SLUGS
CALL = ("• Ana Ruiz 0:01\nHello there.\n• Bo Lund 0:06\n"
        + " ".join(f"Then May {n} came." for n in range(1, 7)) + "\n")
ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


@pytest.fixture
def web(tmp_path):
    return Session(make_app(tmp_path))


def store_of(web) -> Store:
    app = web.c.app
    return Store.open(app.state.data_dir, env={}, home=app.state.home)


def each_form(page, choices):
    form = review_form(page)
    form["d0"] = "each"
    for j, choice in enumerate(choices):
        form[f"p0_{j}"] = choice
    return form


MAY = ["scrub", "keep", "scrub", "keep", "scrub", "keep"]


def may_case(web, title="Sister rent question", directions=""):
    """A client whose call holds May hidden in 3 places as a person and kept in 3 as a month, with a saved note."""
    cid = web.post("/clients", {"first_name": "Testn"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    page = web.post(f"/clients/{cid}/intake", {"text": CALL, "call_date": "2026-11-03"}).text
    form = each_form(page, MAY)
    form["title"], form["directions"] = title, directions
    tx = saved_tx(web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False))
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note about [PERSON_1].")
        s.set_transcript_status(tx, "copied")
    return cid, tx


def code_of_may(web, cid):
    with store_of(web) as s:
        ent = next(e for e in s.load_registry(cid).entities if e.local)
    assert ent.forms[None] == "May"
    return ent.placeholder()


def snapshot(web, cid, tx):
    with store_of(web) as s:
        return (s.get_transcript(tx)["scrubbed_text"], [(o["version"], o["content"]) for o in s.list_outputs(tx, NOTE)],
                s.load_registry(cid).to_dict()["index"])


def change(web, tx, text, **kw):
    return web.post_json(f"/transcripts/{tx}/outputs/{NOTE}/request-change", {"text": text, "version": 1, "latest": 1, **kw})


# ---- 1. a name hidden for this transcript only ---------------------------------------------------------

def only_place(web, tx, text):
    """The one place in typed text that needs a choice, from the live check."""
    asks = web.post_json(f"/transcripts/{tx}/scrub-preview", {"text": text}).json()["ask"]
    assert len(asks) == 1 and len(asks[0]["places"]) == 1
    return asks[0]["places"][0]["start"], asks[0]["word"], asks[0]["code"]


def test_a_name_hidden_in_this_transcript_is_asked_about_in_a_change_request_when_the_word_is_also_plain_text(web):
    """Round 4 changed this. May is hidden in 3 places and kept as a month in 3, so typed "May" is not replaced
    silently: it is flagged with two choices, and the chosen one decides what is sent."""
    cid, tx = may_case(web)
    code = code_of_may(web, cid)
    before = snapshot(web, cid, tx)
    assert before[0].count(code) == 3 and before[0].count("May") == 3        # 3 as a person, 3 kept as a month
    prev = web.post_json(f"/transcripts/{tx}/scrub-preview", {"text": "She lives with May."}).json()
    assert prev["flags"] == ["May"] and prev["ask"][0]["code"] == code
    refused = change(web, tx, "She lives with May.")
    assert refused.status_code == 409 and refused.json()["ask"][0]["word"] == "May"
    start, word, _ = only_place(web, tx, "She lives with May.")
    r = change(web, tx, "She lives with May.", places=[{"start": start, "word": word, "choice": "hide"}])
    assert r.status_code == 200
    asked = r.json()["text"].split("Change requested:\n", 1)[1].split("\n\n", 1)[0]
    assert asked == f"She lives with {code}." and "May" not in asked
    assert snapshot(web, cid, tx) == before                                   # transcript, outputs and month places unchanged
    with store_of(web) as s:
        stored = [m["scrubbed_text"] for m in s.list_messages(cid) if m["kind"] == "correction"]
    assert len(stored) == 1 and f"Change requested:\nShe lives with {code}." in stored[0] and "lives with May" not in stored[0]


def test_the_name_is_not_hidden_for_a_transcript_that_does_not_hold_its_code(web):
    cid, tx = may_case(web)
    other = web.post("/clients", {"first_name": "Zed"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    with store_of(web) as s:
        t2 = s.add_transcript(other, "[PERSON_1]: Hi.", __import__("datetime").date(2026, 11, 2), "")
    assert web.post_json(f"/transcripts/{t2}/scrub-preview", {"text": "She lives with May."}).json()["flags"] == ["May"]


def test_directions_with_the_name_send_a_code_when_chosen_and_the_box_keeps_the_code(web):
    cid, tx = may_case(web)
    code = code_of_may(web, cid)
    start, word, _ = only_place(web, tx, "her sister May")
    refused = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": "her sister May"})
    assert refused.status_code == 409 and refused.json()["ask"][0]["code"] == code     # nothing is sent as a code silently
    sent = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": "her sister May",
                                                      "places": [{"start": start, "word": word, "choice": "hide"}]}).json()["text"]
    assert f"Specific directions:\nher sister {code}" in sent
    assert "sister May" not in sent
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    box = re.search(r'<textarea id="send-directions"[^>]*>(.*?)</textarea>', page, re.S).group(1)
    assert h.unescape(box) == f"her sister {code}"                            # a name that needs a choice stays a code in the box
    assert "Real names are hidden before anything is copied" in page


def test_hide_beside_a_flagged_word_changes_no_stored_file_and_makes_no_version(web):
    cid, tx = may_case(web)
    before = snapshot(web, cid, tx)
    out = web.post_json(f"/transcripts/{tx}/hide-word", {"text": "Zorbax"})
    assert out.status_code == 200 and re.fullmatch(r"\[PERSON_\d+\]", out.json()["code"])
    after = snapshot(web, cid, tx)
    assert after[:2] == before[:2]                                            # transcript.txt and output versions untouched
    with store_of(web) as s:
        reg = s.load_registry(cid)
        assert reg.lookup("PERSON", "Zorbax") is None                         # round 4: this transcript only, never matched elsewhere
        assert [e.only for e in reg.entities if e.forms.get(None) == "Zorbax"] == [[tx]]
        assert wf.view_output(s, cid, out.json()["code"])[0].text == "Zorbax" # but its code restores
    asked = change(web, tx, "Mention Zorbax.").json()["text"].split("Change requested:\n", 1)[1].split("\n\n", 1)[0]
    assert asked == f"Mention {out.json()['code']}."
    assert web.post_json(f"/transcripts/{tx}/hide-word", {"text": "   "}).status_code == 400


def test_hide_does_not_override_a_keep_made_at_review(web):
    cid, tx = may_case(web)
    before = snapshot(web, cid, tx)[0]
    assert web.post_json(f"/transcripts/{tx}/hide-word", {"text": "Ana"}).status_code == 200
    assert snapshot(web, cid, tx)[0] == before and before.count("May") == 3


def test_a_change_request_for_a_stale_version_is_refused_with_a_message(web):
    cid, tx = may_case(web)
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note two.")                              # saved while the page still showed v1
    r = change(web, tx, "Shorten it.")
    assert r.status_code == 409 and r.json()["stale"] is True and "now at version 2" in r.json()["error"]
    assert change(web, tx, "Shorten it.", latest=2, version=2).status_code == 200
    assert "version 2" in change(web, tx, "Shorten it.", latest=2, version=2).json()["text"]
    with store_of(web) as s:
        assert len([m for m in s.list_messages(cid) if m["kind"] == "correction"]) == 2   # the refused one stored nothing


def test_the_change_box_sends_the_latest_version_it_was_built_from(web):
    cid, tx = may_case(web)
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert 'data-latest="1"' in page and "latest: Number(cbox.dataset.latest)" in (ROOT / "app/web/static/app.js").read_text()


def test_the_outgoing_message_hides_the_name_too(web):
    cid, tx = may_case(web)
    code = code_of_may(web, cid)
    blanket = web.post_json(f"/clients/{cid}/outgoing/copy", {"text": "Her sister May is moving.", "kind": "comment", "tx_id": tx, "confirm": "1"})
    assert blanket.status_code == 409 and blanket.json()["ask"]               # a blanket confirm never settles a place that needs a choice
    prev = web.post_json(f"/clients/{cid}/outgoing/preview", {"text": "Her sister May is moving.", "kind": "comment", "tx_id": tx}).json()
    start = prev["ask"][0]["places"][0]["start"]
    r = web.post_json(f"/clients/{cid}/outgoing/copy", {"text": "Her sister May is moving.", "kind": "comment", "tx_id": tx,
                                                         "places": [{"start": start, "word": "May", "choice": "hide"}]})
    assert r.status_code == 200 and f"Her sister {code} is moving." in r.json()["text"] and "May" not in r.json()["text"]


def test_a_local_name_wins_over_a_model_guess_and_the_pipeline_unit_hides_it():
    reg = Registry()
    ent = reg.add_local_person("May")
    cfg = ScrubConfig(keep_first_names=True)                                  # even when first names are left in plain text
    res = scrub_message("Lives with May and Maya in May.", reg, cfg, None, plain_requests=True, local=[ent])
    assert res.text == f"Lives with {ent.placeholder()} and Maya in {ent.placeholder()}."
    assert reg.lookup("PERSON", "May") is None                                # still not a name for other text


# ---- 2. the review directions box -----------------------------------------------------------------------

def review(web, text=CALL):
    cid = web.post("/clients", {"first_name": "Testn"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    return cid, web.post(f"/clients/{cid}/intake", {"text": text, "call_date": "2026-11-03"}).text


def test_the_review_page_has_a_live_directions_check_with_hide_and_a_message_spot(web):
    cid, page = review(web)
    assert f'data-preview-url="/clients/{cid}/intake/directions-preview"' in page
    assert "data-review-box" in page and "data-box-msg" in page and "data-hidden-words" in page
    assert "Real names are hidden before anything is copied" in page


def test_the_review_directions_preview_knows_places_chosen_before_saving(web):
    cid, page = review(web)
    form = each_form(page, MAY)
    form["directions"] = "her sister May"
    r = web.post(f"/clients/{cid}/intake/directions-preview", form)
    assert r.status_code == 200 and r.json()["flags"] == ["May"]              # May is also plain text here, so each place needs a choice
    start = r.json()["ask"][0]["places"][0]["start"]
    form["dir_place"] = f"{start}|hide|May"
    assert web.post(f"/clients/{cid}/intake/directions-preview", form).json() == {"flags": []}
    form["directions"] = "her sister May and Zorbax"
    assert web.post(f"/clients/{cid}/intake/directions-preview", form).json()["flags"] == ["Zorbax"]
    form["dir_hide"] = "Zorbax"
    assert web.post(f"/clients/{cid}/intake/directions-preview", form).json() == {"flags": []}
    bad = web.c.post(f"/clients/{cid}/intake/directions-preview", data=form)   # no token
    assert bad.status_code == 403
    with store_of(web) as s:
        assert s.list_transcripts(cid) == [] and s.load_registry(cid).entities == []   # a preview stores nothing


def test_saving_directions_with_the_name_stores_a_code_and_never_the_name(web):
    cid, page = review(web)
    form = each_form(page, MAY)
    form["directions"] = "her sister May and Zorbax"
    form["dir_hide"] = "Zorbax"
    refused = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    assert refused.status_code == 200 and "Not saved yet" in refused.text     # the place for May has no choice yet
    form["dir_place"] = "11|hide|May"
    tx = saved_tx(web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False))
    code = code_of_may(web, cid)
    with store_of(web) as s:
        meta = s.get_transcript(tx)
        zorbax = next(e for e in s.load_registry(cid).entities if e.forms.get(None) == "Zorbax")
        assert zorbax.local and zorbax.only == [tx]                           # Hide in the directions box is for this transcript only
        assert meta["directions"] == f"her sister {code} and {zorbax.placeholder()}"
        assert meta["scrubbed_text"].count("May") == 3 and "Zorbax" not in meta["scrubbed_text"]
    assert web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": "her sister May"}).status_code == 409
    sent = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": "her sister May",
                                                      "places": [{"start": 11, "word": "May", "choice": "hide"}]}).json()["text"]
    assert "sister May" not in sent


def test_unconfirmed_flagged_words_stay_beside_the_box_with_hide_after_a_refused_save(web):
    cid, page = review(web)
    form = each_form(page, MAY)
    form["directions"] = "and Zorbax"
    r = web.post(f"/clients/{cid}/intake/save", form)
    assert r.status_code == 200 and "Not saved yet" in r.text
    box = r.text.split("data-review-box", 1)[1]
    assert 'data-hide-word="Zorbax"' in box and "left as they are" in box


# ---- 3. hidden names page -------------------------------------------------------------------------------

def test_hidden_names_page_says_where_a_transcript_only_name_applies_and_shows_codes_in_merge(web):
    cid, tx = may_case(web)
    code = code_of_may(web, cid)
    page = web.get(f"/clients/{cid}/registry").text
    assert "Only in Sister rent question" in page
    assert f"May {code}</option>" in page and re.search(r"Ana Ruiz \[PERSON_\d+\]</option>", page)


def test_a_transcript_only_name_of_an_untitled_call_is_named_by_its_date(tmp_path):
    web = Session(make_app(tmp_path))
    cid, tx = may_case(web, title="")
    assert "Only in 3 Nov 2026" in web.get(f"/clients/{cid}/registry").text


# ---- 4. Ask Claude for this ---------------------------------------------------------------------------------

def test_the_request_box_can_show_last_sent_with_use_again_and_the_script_empties_the_box(web):
    cid, tx = may_case(web, directions="keep it short")
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert "data-last-sent" in page and "data-use-again" in page
    js = (ROOT / "app/web/static/app.js").read_text()
    assert 'last.hidden = false;\n      dirs.value = ""; dirs.defaultValue = "";' in js


# ---- 5. import check ------------------------------------------------------------------------------------------

def test_the_import_check_names_the_transcript_by_title_and_date_and_a_summary_by_client(web):
    cid, tx = may_case(web)
    chk = web.post(f"/clients/{cid}/import", {"text": "A plain reply.", "kind": "output", "tx_id": tx, "output": FORM}).text
    assert "Belongs to Sister rent question, 3 Nov 2026." in chk and tx not in re.search(r"Belongs to[^<]*", chk).group()
    summary = f"[CLIENT: {cid} | TX: {tx}]\nThe sister is moving out."
    s = web.post(f"/clients/{cid}/import", {"text": summary, "kind": "summary"}).text
    assert "Summary for Testn." in s and "Belongs to" not in s
    preview = re.search(r"<h3>Preview with real names</h3>\s*<pre class=\"text\">(.*?)</pre>", s, re.S).group(1)
    assert "[CLIENT:" not in preview and "The sister is moving out." in preview


# ---- 6. Name: text notice -----------------------------------------------------------------------------------------

def test_name_colon_text_is_noted_plainly_not_as_a_warning(web):
    text = "Dana Whitaker: Thanks for calling.\nTomas Beltran: Hello.\nDana Whitaker: Who is this?\n"
    reading = parse_lenient(text)
    assert reading.notes == [] and reading.info == ["Read 3 speaker lines (Name: text)."]
    cid = web.post("/clients", {"first_name": "Q"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    page = web.post(f"/clients/{cid}/intake", {"text": text, "call_date": "2026-11-03"}).text
    assert 'role="status">Read 3 speaker lines (Name: text).</p>' in page and "read loosely" not in page
    assert 'class="warn" role="status">Read' not in page


def test_a_genuinely_loose_layout_still_warns():
    reading = parse_lenient("Ana Ruiz 0:01 Hello there\nBo Lund 0:06 Hi\n")
    assert reading.info == [] and len(reading.notes) == 1 and "read loosely" in reading.notes[0]


# ---- 7 and 8. the filter and the connector switch -------------------------------------------------------------------

def test_the_filter_never_shows_a_non_matching_call_as_chosen():
    js = (ROOT / "app/web/static/app.js").read_text()
    assert '"Choose one of "' in js and '"No matches"' in js and "first.disabled = true" in js


def test_the_connector_checkbox_saves_on_change_and_says_so(web):
    page = web.get("/settings").text
    form = re.search(r'<form[^>]*data-autosave[^>]*>(.*?)</form>', page, re.S).group(1)
    assert 'name="mcp_enabled"' in form and "data-save-status" in form and "saves it at once" in form
    js = (ROOT / "app/web/static/app.js").read_text()
    assert 'form[data-autosave]' in js and "requestSubmit()" in js
    r = web.c.post("/settings", data={"section": "connector", "mcp_enabled": "1", "csrf": web.token},
                   headers={"Accept": "application/json"})
    assert r.status_code == 200
    with store_of(web) as s:
        assert wf.load_settings(s).mcp_enabled
