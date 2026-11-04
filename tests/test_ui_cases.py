"""The call page board, the change request route, the fixed client page and the seed script."""
import html as h
import re
import runpy
from datetime import date
from pathlib import Path

import pytest

from app.scrub.ner import NerModel
from app.web import create_app
from app.outputs import NAMES, SLUGS, TEXT_SLUGS
from app.store import Store
from tests.fake_ner import FakeBackend
from tests.webhelp import Session, fixture_text, make_app, review_form, saved_tx

NOTE, CAL, FORM = TEXT_SLUGS
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def env(tmp_path):
    web = Session(make_app(tmp_path))
    cid = web.post("/clients", {"first_name": "Maria"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    r = web.post(f"/clients/{cid}/intake", {"text": fixture_text(1), "call_date": "2026-11-02"})
    tx = saved_tx(web.post(f"/clients/{cid}/intake/save", review_form(r.text), follow_redirects=False))
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note one for [PERSON_1].")
        s.add_output(cid, tx, NOTE, "Note two for [PERSON_1].", "edit")
        s.add_output(cid, tx, CAL, "Calendar one.")
        s.add_output(cid, tx, CAL, "Calendar two.", "mcp")
        s.set_requested_outputs(tx, [NOTE, CAL])
    return web, cid, tx, tmp_path


def store_of(web):
    app = web.c.app
    return Store.open(app.state.data_dir, env={}, home=app.state.home)


def change(web, tx, slug, text, **extra):
    return web.post_json(f"/transcripts/{tx}/outputs/{slug}/request-change", {"text": text, **extra})


def unflagged(web, tx, text="Make it shorter.", slug=NOTE, **extra):
    """Send a request, confirming whatever the scrubber flags, and return the response."""
    r = change(web, tx, slug, text, **extra)
    if r.status_code == 409:
        r = change(web, tx, slug, text, confirm=r.json()["flags"], **extra)
    return r


def column(page, slug):
    return re.search(rf'<section class="col" id="out-{slug}">(.*?)</section>', page, re.S).group(1)


# ---- the change request ------------------------------------------------------------------------------

def test_the_change_request_text_comes_in_the_planned_order(env):
    web, cid, tx, tmp = env
    r = unflagged(web, tx, "Make it shorter.", version=2)
    assert r.status_code == 200
    text = r.json()["text"]
    marks = [f"Change request for Clio Note (output ID {NOTE}).", f"[CLIENT: {cid} | TX: {tx}]",
             "Change requested:\nMake it shorter.", "Note two for [PERSON_1].", "Transcript:\n"]
    spots = [text.index(m) for m in marks]
    assert spots == sorted(spots) and len(set(spots)) == len(spots)
    assert "save_output" not in text and "[OUTPUT:" not in text and "Revise only" not in text
    assert NAMES[NOTE] in text and "Note one for" not in text
    with store_of(web) as s:
        assert text.endswith(s.get_transcript(tx)["scrubbed_text"])
        msgs = [m for m in s.list_messages(cid) if m["kind"] == "correction"]
        assert [m["scrubbed_text"] for m in msgs] == [text] and msgs[0]["transcript_id"] == tx
    # the version on screen is the one sent, and no version means the latest
    older = unflagged(web, tx, "Make it shorter.", version=1).json()["text"]
    assert "Note one for [PERSON_1]." in older and "Note two for" not in older
    assert "Note two for [PERSON_1]." in unflagged(web, tx).json()["text"]


def test_a_known_name_typed_in_the_box_never_reaches_the_copy_or_the_stored_message(env):
    web, cid, tx, tmp = env
    typed = "Say that Maria Lopez moved to the new office and her email is maria.lopez@example.org."
    r = unflagged(web, tx, typed)
    assert r.status_code == 200
    text = r.json()["text"]
    body = text.replace(f"[CLIENT: {cid} | TX: {tx}]", "")        # the header holds the client's ID, which has the first name
    assert "Lopez" not in text and "Maria" not in body and "maria.lopez@example.org" not in text
    assert re.search(r"Change requested:\n.*\[PERSON_\d+\]", text) and "[EMAIL_" in text
    with store_of(web) as s:
        stored = [m["scrubbed_text"] for m in s.list_messages(cid) if m["kind"] == "correction"]
        assert stored and all("Lopez" not in t and "maria.lopez@example.org" not in t for t in stored)
    on_disk = "".join(p.read_text(encoding="utf-8") for p in (tmp / "data" / "clients").rglob("*.json")
                      if p.name not in ("client.json",))
    assert "Lopez" not in on_disk
    # a refused request stores nothing either
    with store_of(web) as s:
        before = len(s.list_messages(cid))
    assert change(web, tx, NOTE, "  \n ").status_code == 400
    with store_of(web) as s:
        assert len(s.list_messages(cid)) == before


def test_flagged_words_stop_the_copy_until_each_one_is_confirmed(env):
    web, cid, tx, tmp = env
    typed = "Ask Zorbo Quillfeather to call about Gizmo."
    first = change(web, tx, NOTE, typed)
    assert first.status_code == 409
    flags = first.json()["flags"]
    assert flags and "text" not in first.json()
    with store_of(web) as s:
        assert [m for m in s.list_messages(cid) if m["kind"] == "correction"] == []
    assert change(web, tx, NOTE, typed, confirm=True).status_code == 409           # a bare yes is not enough
    if len(flags) > 1:
        assert change(web, tx, NOTE, typed, confirm=flags[:-1]).status_code == 409
    assert change(web, tx, NOTE, typed, confirm=["Unrelated"]).status_code == 409
    done = change(web, tx, NOTE, typed, confirm=flags)
    assert done.status_code == 200 and "Change requested:" in done.json()["text"]
    with store_of(web) as s:
        assert len([m for m in s.list_messages(cid) if m["kind"] == "correction"]) == 1
    # editing the text brings new flags, and the earlier confirmation does not cover them
    again = change(web, tx, NOTE, typed + " Also Flibbertigibbet.", confirm=flags)
    assert again.status_code == 409 and "Flibbertigibbet" in again.json()["flags"]


def test_an_empty_or_bad_request_is_refused_and_nothing_is_stored(env):
    web, cid, tx, tmp = env
    for text in ("", "   \n\t"):
        r = change(web, tx, NOTE, text)
        assert r.status_code == 400 and "Describe the change" in r.json()["error"]
    assert web.post_json(f"/transcripts/{tx}/outputs/{NOTE}/request-change", {}).status_code == 400
    assert change(web, tx, NOTE, "Shorter.", version=9).status_code == 400
    assert change(web, tx, FORM, "Shorter.").status_code == 400                    # no version of this output yet
    assert change(web, tx, "reply", "Shorter.").status_code == 400
    assert web.post_json("/transcripts/TX-20200101-1/outputs/clio-note/request-change", {"text": "x"}).status_code == 404
    assert web.c.post(f"/transcripts/{tx}/outputs/{NOTE}/request-change", json={"text": "x"}).status_code == 403   # no CSRF token
    with store_of(web) as s:
        assert [m for m in s.list_messages(cid) if m["kind"] == "correction"] == []


# ---- the board ---------------------------------------------------------------------------------------

def test_the_board_always_has_three_columns_in_fixed_order(env):
    web, cid, tx, tmp = env
    # a call with nothing asked for, then one with only the last output, then every query the page accepts
    with store_of(web) as s:
        other = s.add_transcript(cid, "Hello [PERSON_1].", date(2026, 11, 1))
        s.set_transcript_status(other, "reviewed")
    pages = [web.get(f"/transcripts/{other}?view=outputs").text, web.get(f"/transcripts/{tx}").text,
             web.get(f"/transcripts/{tx}?{FORM}=3&cmp-{CAL}=1&{NOTE}=x").text,
             web.get(f"/transcripts/{tx}?{CAL}=2&cmp-{CAL}=1&{NOTE}=1").text]
    web.post_json(f"/transcripts/{other}/copy", {"outputs": [FORM]})
    pages.append(web.get(f"/transcripts/{other}").text)
    for page in pages:
        assert re.findall(r'<section class="col" id="out-([a-z-]+)">', page) == [NOTE, CAL, FORM]
    states = re.findall(r'<section class="col" id="out-[a-z-]+">', pages[0])
    assert len(states) == 3 and "Waiting for Claude" not in pages[0] and pages[0].count("Not requested") == 5
    assert pages[1].count("Not requested") == 3 and "Waiting for Claude" not in pages[1]
    assert pages[4].count("Waiting for Claude") == 1 and pages[4].count("Not requested") == 4
    assert "Waiting for Claude" in column(pages[4], FORM)


def test_one_columns_version_choice_does_not_change_another(env):
    web, cid, tx, tmp = env
    page = web.get(f"/transcripts/{tx}?{NOTE}=1").text
    assert "Note one for" in column(page, NOTE) and "Note two for" not in column(page, NOTE)
    assert "Calendar two." in column(page, CAL) and "Calendar one." not in column(page, CAL)
    # the links in each column keep the other column's choice
    arrows = re.findall(r'class="arrow" href="([^"]*)"', column(page, CAL))
    hidden = re.findall(r'<input type="hidden" name="([^"]*)" value="([^"]*)">', column(page, CAL))
    assert arrows and all(f"{NOTE}=1" in h.unescape(c) for c in arrows) and (NOTE, "1") in hidden
    page = web.get(f"/transcripts/{tx}?{NOTE}=1&{CAL}=1").text
    assert "Note one for" in column(page, NOTE) and "Calendar one." in column(page, CAL)
    # the change box of a column carries the version on screen
    assert re.search(r'data-change data-version="1"', column(page, NOTE))
    assert re.search(r'data-change data-version="1"', column(page, CAL))
    assert re.search(r'data-change data-version="2"', column(web.get(f"/transcripts/{tx}?{CAL}=1").text, NOTE))
    assert "Changes from v1 to v2" in column(web.get(f"/transcripts/{tx}?{NOTE}=2&cmp-{NOTE}=1").text, NOTE)
    assert "Changes from" not in column(web.get(f"/transcripts/{tx}?{NOTE}=2&cmp-{NOTE}=1").text, CAL)


def test_the_page_never_reloads_over_typed_text_and_the_script_has_no_inline_code(env):
    web, cid, tx, tmp = env
    page = web.get(f"/transcripts/{tx}").text
    assert "data-new-version" in page and page.count("data-keep") == 4 and "<script>" not in page.replace("<script src", "")
    js = web.get("/static/app.js").text
    assert "hasTyped()" in js and js.count("location.reload()") == 1 and "if (!hasTyped()) { window.location.href" in js and "textarea[data-keep]" in js
    assert "←" not in page and "—" not in page and "–" not in page


# ---- pasting a reply on the call page ----------------------------------------------------------------

def test_a_reply_pasted_on_the_call_page_is_saved_to_this_call(env):
    web, cid, tx, tmp = env
    page = web.get(f"/transcripts/{tx}").text
    form = re.search(r'<form method="post" action="/clients/[^"]+/import"[^>]*>(.*?)</form>', page, re.S).group(1)
    assert f'name="tx_id" value="{tx}"' in form and 'name="kind" value="output"' in form and 'name="text"' in form
    assert page.count('name="output"') == 5                   # only the checkboxes of Request more outputs
    plain = "A reply with no header and no markers."
    chk = web.post(f"/clients/{cid}/import", {"text": plain, "kind": "output", "tx_id": tx, "output": FORM})
    assert "Will save 1 output" in chk.text and re.search(r"Belongs to Untitled, \d+ \w{3} \d{4}\.", chk.text) and tx not in re.search(r"Belongs to[^<]*", chk.text).group()
    content = h.unescape(re.search(r'<textarea name="content"[^>]*>(.*?)</textarea>', chk.text, re.S).group(1))
    saved = web.post(f"/clients/{cid}/import/save", {"content": content, "kind": "output", "tx_id": tx, "output": FORM},
                     follow_redirects=False)
    assert saved.status_code == 303 and saved.headers["location"] == f"/clients/{cid}?tx={tx}&view=outputs"
    with store_of(web) as s:
        assert [o["content"] for o in s.list_outputs(tx, FORM)] == [plain]
    shown = web.get(saved.headers["location"]).text
    assert plain in column(shown, FORM) and "Waiting for Claude" not in shown
    # the old routes still work
    assert web.get(f"/clients/{cid}/import").status_code == 200 and web.get(f"/clients/{cid}/outgoing").status_code == 200


# ---- the client page ---------------------------------------------------------------------------------

def test_the_client_page_has_three_tabs_a_call_selector_and_the_rest_under_more(env):
    web, cid, tx, tmp = env
    page = web.get(f"/clients/{cid}").text
    tabs = re.search(r'<nav class="tabs".*?</nav>', page, re.S).group(0)
    assert re.findall(r">([^<]+)</a>", tabs) == ["Transcripts", "Add transcript", "Hidden names"]
    assert "Import reply" not in tabs and "Message to Claude" not in tabs
    assert 'class="calls"' not in page and "<h2>Transcripts</h2>" not in page            # the old list is gone
    assert f'<option value="{tx}" data-id="{tx}" selected>Untitled, 2 Nov 2026, 2 of 2 outputs received</option>' in page and "1 of 1" in page
    assert page.index("<summary>More</summary>") < page.index("Running summary") < page.index("Manage client")
    for needle in ("Running summary", "Manage client"):
        assert re.search(rf"<details[^>]*>\s*<summary>{needle}", page)
    assert "<details open" not in page
    assert f'href="/clients/{cid}/outgoing"' in page and f'href="/clients/{cid}/import?kind=summary"' in page
    saved = web.get(f"/clients/{cid}?saved={tx}").text
    assert "Transcript saved" in saved and f'value="{tx}" data-id="{tx}" selected' in saved
    for route in ("intake", "registry", "outgoing", "import"):
        assert web.get(f"/clients/{cid}/{route}").status_code == 200
    web.post("/clients", {"first_name": "Nobody"})
    empty = web.get("/clients/" + [c for c in re.findall(r'/clients/(Nobody-[\w-]+)', web.get("/").text)][0]).text
    assert "No transcripts yet" in empty


# ---- the seed script ---------------------------------------------------------------------------------

def test_the_seed_script_is_safe_to_run_twice_and_leaves_other_clients_alone(tmp_path):
    seed = runpy.run_path(str(ROOT / "scripts" / "seed_test_cases.py"))
    folder = tmp_path / "data"
    with Store.open(folder, env={}, home=tmp_path) as s:
        mine = s.create_client("Real")
        s.add_transcript(mine, "Hello.")
    with Store.open(folder, env={}, home=tmp_path) as s:
        added, skipped = seed["seed"](s)
    assert len(added) == 14 and skipped == [] and all(a.startswith("Test") for a in added)
    snapshot = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file() and p.name != "audit.jsonl" and ".lock" not in p.name}
    with Store.open(folder, env={}, home=tmp_path) as s:
        added2, skipped2 = seed["seed"](s)
    assert added2 == [] and len(skipped2) == 14
    after = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file() and p.name != "audit.jsonl" and ".lock" not in p.name}
    assert after == snapshot
    with Store.open(folder, env={}, home=tmp_path) as s:
        rows = {c["first_name"]: c for c in s.list_clients(include_archived=True)}
        assert len(rows) == 15 and "Real" in rows and rows["Testi"]["archived"] and not rows["Testa"]["archived"]
        testa = rows["Testa"]["id"]
        tx = s.list_transcripts(testa)[0]
        assert [len(s.list_outputs(tx["id"], slug)) for slug in TEXT_SLUGS] == [3, 2, 1]
        assert [o["source"] for o in s.list_outputs(tx["id"], NOTE)] == ["import", "mcp", "edit"]
        assert len(s.list_transcripts(rows["Testg"]["id"])) == 6 and s.list_transcripts(rows["Testj"]["id"]) == []
        assert s.get_transcript(tx["id"])["requested_outputs"] == list(TEXT_SLUGS)
        reg = s.load_registry(testa)
        assert "Testa Allthree" in [e.forms.get(None) for e in reg.entities]
        assert "Testa Allthree" not in tx["scrubbed_text"] and "[PERSON_1]" in tx["scrubbed_text"]
    # the warnings client shows both warnings, and the pages render for every seeded call
    app = create_app(folder, env={}, home=tmp_path, ner=NerModel(backend_factory=lambda: FakeBackend({})))
    seeded = Session(app)
    with Store.open(folder, env={}, home=tmp_path) as s:
        testf = [c for c in s.list_clients() if c["first_name"] == "Testf"][0]["id"]
        calls = [t["id"] for c in s.list_clients(include_archived=True) for t in s.list_transcripts(c["id"])]
        warn_tx = s.list_transcripts(testf)[0]["id"]
    page = seeded.get(f"/transcripts/{warn_tx}").text
    assert "Unknown hidden names: [PERSON_9]" in page and "real value" in page
    for call in calls:
        r = seeded.get(f"/transcripts/{call}?view=outputs")
        assert r.status_code == 200 and len(re.findall(r'<section class="col"', r.text)) == 3
        assert re.search(rf'<option value="{call}" data-id="{call}" selected>[^<]+, \d+ \w{{3}} \d{{4}}, ', r.text)
