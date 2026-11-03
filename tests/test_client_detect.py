"""Pasting a transcript with no client chosen: a person the app does not know becomes a new client."""
import re

import pytest

from tests.webhelp import Session, fixture_text, make_app, review_form, saved_tx


@pytest.fixture
def web(tmp_path):
    return Session(make_app(tmp_path))


def paste(web, text):
    return web.post("/intake", {"text": text, "call_date": "2026-11-02"})


def only_client_id(web):
    r = web.c.get("/", follow_redirects=False)
    return r.headers["location"].rsplit("/", 1)[1] if r.status_code == 303 else None


def save_first(web):
    r = paste(web, fixture_text(1))
    cid = re.search(r"/clients/(Maria-\d{8}-1)/intake/save", r.text).group(1)
    assert web.post(f"/clients/{cid}/intake/save", review_form(r.text), follow_redirects=False).status_code == 303
    return cid


def test_an_unknown_person_becomes_a_new_client_only_when_the_transcript_is_saved(web):
    r = paste(web, fixture_text(1))
    assert "Review before saving" in r.text and "New client Maria created from this transcript" in r.text
    cid = re.search(r"/clients/(Maria-\d{8}-1)/intake/save", r.text).group(1)
    assert only_client_id(web) is None                    # not in the sidebar yet, so no empty log to click
    r = web.post(f"/clients/{cid}/intake/save", review_form(r.text), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/clients/{cid}?saved={saved_tx(r)}"
    assert only_client_id(web) == cid
    page = web.get(r.headers["location"]).text                   # the client log, with the new transcript on it
    # the copy controls are on this same page, on the call that was just saved
    assert "Transcript saved" in page and saved_tx(r) in page and "Copy for Claude" in page
    assert "Copy for Claude" in web.get(f"/transcripts/{saved_tx(r)}").text      # the old address redirects here
    assert "Maria Lopez" in page


def test_the_first_speaker_is_not_taken_as_the_client(web):
    r = paste(web, fixture_text(3))
    assert "New client Priya created from this transcript" in r.text


def test_a_known_full_name_asks_instead_of_making_a_duplicate(web):
    cid = save_first(web)
    r = paste(web, fixture_text(1))
    assert "This looks like an existing client" in r.text and "already in this client" in r.text
    assert f'value="{cid}"' in r.text and "checked" not in r.text.split("<fieldset")[1].split("</fieldset>")[0]   # nothing preselected
    assert "Matched Maria Lopez" in r.text and "hidden names" in r.text and "registry" not in r.text.split("<h1>")[1]
    assert only_client_id(web) == cid
    r2 = web.post("/intake/start", {"text": fixture_text(1), "call_date": "2026-11-02", "client": cid})
    assert "Review before saving" in r2.text and f"/clients/{cid}/intake/save" in r2.text


def test_a_blank_name_asks_again_and_creates_nothing(web):
    r = web.post("/intake/start", {"text": fixture_text(1), "call_date": "2026-11-02", "client": "new",
                                   "first_name": ""})
    assert "Enter the client" in r.text and "first name" in r.text
    assert only_client_id(web) is None


def test_an_empty_paste_creates_nothing(web):
    r = paste(web, "   ")
    assert "Nothing was pasted" in r.text
    assert only_client_id(web) is None


def test_plain_text_with_no_speaker_lines_still_works_and_asks_for_a_name_only_if_none_found(web):
    r = paste(web, "hello there, this is a call about the roof")
    assert "Enter" in r.text or "first name" in r.text            # no person found, so it asks
    assert only_client_id(web) is None


def test_rename_changes_display_name_not_id(web):
    cid = save_first(web)
    assert web.post(f"/clients/{cid}/rename", {"first_name": "Mia"}, follow_redirects=False).status_code == 303
    page = web.get(f"/clients/{cid}").text
    assert 'value="Mia"' in page and cid in page


def test_an_abandoned_review_leaves_no_visible_client(web):
    paste(web, fixture_text(1))
    assert only_client_id(web) is None


def test_a_client_is_deleted_only_after_the_confirm_page(web):
    cid = web.post("/clients", {"first_name": "Zed"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    assert f'href="/clients/{cid}/delete"' in web.get(f"/clients/{cid}").text
    assert "There is no undo" in web.get(f"/clients/{cid}/delete").text
    assert only_client_id(web) == cid                      # looking at the page deleted nothing
    assert web.post(f"/clients/{cid}/delete", follow_redirects=False).status_code == 303
    assert only_client_id(web) is None


def test_a_client_with_a_transcript_can_be_deleted_and_its_files_go(web):
    cid = save_first(web)
    page = web.get(f"/clients/{cid}/delete").text
    assert "1 transcript," in page and "There is no undo" in page
    web.post(f"/clients/{cid}/delete", follow_redirects=False)
    assert only_client_id(web) is None
    assert web.get(f"/clients/{cid}").status_code == 404


THREE_LINE = "•\nDana Whitaker\n0:01\nThanks for calling. Is this Tomas Beltran?\n•\nTomas Beltran\n0:06\nYes, it is Tomas.\n"


def test_a_turn_with_the_bullet_name_and_time_on_separate_lines_is_read(web):
    r = paste(web, THREE_LINE)
    assert "Review before saving" in r.text and "New client Tomas created from this transcript" in r.text
    assert "could not be read" not in r.text


def test_the_same_first_name_as_a_client_asks_and_shows_the_last_call(web):
    cid = save_first(web)
    r = paste(web, "• Ana Ruiz 0:01\nThank you for calling.\n• Maria Santos 0:09\nHello, I am Maria Santos and I need help with a lease.\n")
    assert "Add to an existing client" in r.text and "Same first name as the client" in r.text
    assert "Last call 2026-11-02, 1 transcript." in r.text
    assert f'name="client" value="{cid}"' in r.text and 'name="client" value="new"' in r.text
    assert "New client Maria created" not in r.text and only_client_id(web) == cid          # nothing was created


def test_start_a_new_client_from_the_ask_page_still_works(web):
    save_first(web)
    r = web.post("/intake/start", {"text": "• Ana Ruiz 0:01\nThank you.\n• Maria Santos 0:09\nHello, I am Maria Santos.\n",
                                   "call_date": "2026-11-02", "client": "new", "first_name": "Maria"})
    assert "Review before saving" in r.text and re.search(r"/clients/Maria-\d{8}-2/intake/save", r.text)
