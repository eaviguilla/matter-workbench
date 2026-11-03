"""UX review round 2: codes are never names (registry, scrubbing, import masking, the stored data), directions shown with
real names and kept after a copy, the connector sentence, the import check list, the speaker layout "Name: text",
the archived page and the compare list."""
import html as h
import json
import re
from pathlib import Path

import pytest

from app import workflow as wf
from app.check import check, fix, main as check_main
from app.outputs import SLUGS
from app.scrub.ner import NerModel
from app.scrub.parse import parse_lenient
from app.scrub.pipeline import ScrubConfig, scrub_message, scrub_transcript
from app.scrub.registry import Entity, PlaceholderValue, Registry, has_token
from app.store import Store
from tests.fake_ner import FakeBackend
from tests.test_ux_round import paste, save_call, store_of
from tests.webhelp import Session, make_app, review_form

NOTE, CAL, FORM = SLUGS
ROOT = Path(__file__).resolve().parent.parent
CODES = {f"[PERSON_{n}]": ("person", 0.95) for n in range(1, 9)}
CODES.update({f"[PERSON_{n}.first]": ("person", 0.95) for n in range(1, 9)})


@pytest.fixture
def web(tmp_path):
    """A web session whose name model also (wrongly) takes placeholder codes for people, as the real one did."""
    return Session(make_app(tmp_path, table=dict(CODES)))


def box_value(page: str, idp: str) -> str:
    return h.unescape(re.search(rf'<textarea id="{idp}-directions"[^>]*>(.*?)</textarea>', page, re.S).group(1))


def output_text(page: str, slug: str) -> str:
    raw = re.search(rf'<pre class="text" id="out-rehydrated-{slug}">(.*?)</pre>', page, re.S).group(1)
    return h.unescape(re.sub(r"<[^>]+>", "", raw))


def entity_values(web, cid) -> list:
    with store_of(web) as s:
        return [v for e in s.load_registry(cid).entities for v in e.forms.values()]


# ---- 1. a code is never a name --------------------------------------------------------------------------

def test_the_registry_refuses_a_value_that_is_or_holds_a_code():
    reg = Registry()
    reg.add_person("Dana Whitaker")
    ent = reg.entities[0]
    for bad in ("[PERSON_1]", "[PERSON_1.first]", "[person_2.last]", "Dana [PERSON_2]", "[ PERSON_ 3 ]"):
        with pytest.raises(PlaceholderValue):
            reg.add_person(bad)
        with pytest.raises(PlaceholderValue):
            reg.add_value("PERSON", bad)
        with pytest.raises(PlaceholderValue):
            reg.add_local_person(bad)
        with pytest.raises(PlaceholderValue):
            reg.set_form(ent, "first", bad)
        with pytest.raises(PlaceholderValue):
            reg.add_nickname(ent, bad)
        with pytest.raises(PlaceholderValue):
            reg.add_surname(ent, bad)
        with pytest.raises(PlaceholderValue):
            reg.add_firstname(ent, bad)
    with pytest.raises(PlaceholderValue):
        reg.add_value("EMAIL", "[EMAIL_1]")
    with pytest.raises(PlaceholderValue):
        reg.add_value("ADDRESS", "1 Main Street [ADDRESS_2]")
    assert [e.forms for e in reg.entities] == [{None: "Dana Whitaker", "first": "Dana", "last": "Whitaker"}]
    assert reg.add_person("Sam Officer")[0].n == 2                    # a refused value used no number
    assert issubclass(PlaceholderValue, ValueError)                   # so the hidden names page shows it as an error


def test_scrubbing_leaves_codes_alone_and_never_flags_them():
    reg = Registry()
    reg.add_person("Dana Whitaker")
    before = [(e.type, e.n, dict(e.forms)) for e in reg.entities]
    ner = NerModel(backend_factory=lambda: FakeBackend(dict(CODES)))
    text = "Tell [PERSON_1] and [PERSON_2.first] about it. Ask [Person_3] too, and [PERSON_1.last]."
    res = scrub_message(text, reg, ScrubConfig(), ner, plain_requests=True)
    assert res.text == text and res.flags == []
    assert [(e.type, e.n, dict(e.forms)) for e in reg.entities] == before
    # inside a call too, and a real name next to a code is still hidden
    call = "• Dana Whitaker 0:01\nCall [PERSON_1] back. Dana Whitaker agrees.\n"
    out = scrub_transcript(call, reg, ScrubConfig(), ner)
    assert "Call [PERSON_1] back. [PERSON_1] agrees." in out.text and [e.n for e in reg.entities] == [1]


def test_a_real_name_that_matches_a_word_inside_a_code_does_not_change_the_code():
    reg = Registry()
    reg.add_person("Sam First")                                       # the word "First" sits inside [PERSON_2.first]
    text = "Note for [PERSON_2.first] from First."
    res = scrub_message(text, reg, ScrubConfig(), None, plain_requests=True)
    assert res.text == "Note for [PERSON_2.first] from [PERSON_1.last]."
    masked, n = wf.mask_known_values(text, reg, set())
    assert masked == res.text and n == 1


def junk_registry() -> Registry:
    """What the old bug saved: an entry whose value is a code."""
    reg = Registry()
    reg.add_person("Testn Reviewwords")
    junk = Entity("PERSON", 5, {None: "[PERSON_1]"})
    reg.entities.append(junk)
    reg._index[("PERSON", "[person_1]")] = (junk, None)
    return reg


def test_import_masking_never_treats_a_code_as_a_real_value_even_if_one_was_saved():
    reg = junk_registry()
    text = "Call [PERSON_1] and [PERSON_1.first]. Testn Reviewwords agrees."
    found = []
    masked, n = wf.mask_known_values(text, reg, set(), found=found)
    assert masked == "Call [PERSON_1] and [PERSON_1.first]. [PERSON_1] agrees." and n == 1
    assert found == [("Testn Reviewwords", "[PERSON_1]")]
    assert [f.surface for f in reg.iter_forms() if has_token(f.surface)] == []


TESTN = (ROOT / "samples" / "review_may.txt").read_text(encoding="utf-8")
TESTJ = ("• Testj Empty 0:01\nHello, it is Testj. I am calling about the keys.\n"
         "• Pat Rivera 0:20\nThanks. Who has the second set of keys?\n"
         "• Testj Empty 0:31\nMy neighbour Jo Hartman has them.\n")


@pytest.mark.parametrize("name, call, directions, replace, expect", [
    ("Testn", TESTN, "Mention Testn Reviewwords and Sam Officer by role only.", "Testn Reviewwords", ["Testn Reviewwords", "Sam"]),
    ("Testj", TESTJ, "Ask Testj about Pat Rivera and Jo Hartman.", "Testj Empty", ["Testj", "Pat Rivera", "Jo Hartman"]),
])
def test_directions_survive_copy_import_and_copy_with_real_names(web, name, call, directions, replace, expect):
    cid, tx = save_call(web, call, outputs=[NOTE], directions=directions)
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    with store_of(web) as s:
        stored = s.get_transcript(tx)["directions"]
        count = len(s.load_registry(cid).entities)
    assert not any(real in stored for real in expect) and "[PERSON_" in stored        # stored only in scrubbed form
    shown = box_value(page, "send")
    assert shown == directions                                                        # real names in the box
    # Copy for Claude with what the box holds: codes go out, no real name, no new entry
    sent = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": shown}).json()["text"]
    head = sent.split(f"[CLIENT: {cid}")[0]
    assert stored in head and not any(real in head for real in expect)
    with store_of(web) as s:
        reg = s.load_registry(cid)
        assert len(reg.entities) == count and reg.code_entries() == []
        assert s.get_transcript(tx)["directions"] == stored                           # kept for the next copy
    assert not any(has_token(v) for v in entity_values(web, cid))
    # a box that still holds the codes (a page opened before this fix) must not register them as people either
    stale = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": stored}).json()["text"]
    assert stored in stale.split(f"[CLIENT: {cid}")[0]
    with store_of(web) as s:
        assert len(s.load_registry(cid).entities) == count and s.load_registry(cid).code_entries() == []
    # a second copy sends them again, unchanged
    again = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE], "directions": box_value(
        web.get(f"/clients/{cid}?tx={tx}&view=transcript").text, "send")}).json()["text"]
    assert stored in again.split(f"[CLIENT: {cid}")[0] and len(entity_values(web, cid)) >= count
    # Claude's reply uses the right codes; import keeps them and Copy with real names restores real names
    with store_of(web) as s:
        reg = s.load_registry(cid)
        lead = reg.lookup("PERSON", replace)
        code, first = lead[0].placeholder(), lead[0].placeholder("first")
    reply = f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {NOTE}]\nNote for {code}. {first} will follow up."
    chk = web.post(f"/clients/{cid}/import", {"text": reply, "kind": "output", "tx_id": tx})
    assert chk.status_code == 200 and "PERSON_9" not in chk.text
    body = h.unescape(re.search(r'<textarea name="content"[^>]*>(.*?)</textarea>', chk.text, re.S).group(1))
    saved = web.post(f"/clients/{cid}/import/save", {"content": body, "kind": "output", "tx_id": tx, "output": ""},
                     follow_redirects=False)
    assert saved.status_code == 303
    with store_of(web) as s:
        assert s.list_outputs(tx, NOTE)[-1]["content"] == f"Note for {code}. {first} will follow up."     # codes unchanged
    out = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    real = output_text(out, NOTE)
    assert replace in real and "[PERSON_" not in real
    raw = re.search(rf'<pre class="hidden-text" id="out-raw-{NOTE}">(.*?)</pre>', out, re.S).group(1)
    assert f"Note for {code}." in h.unescape(raw)
    with store_of(web) as s:
        assert s.load_registry(cid).code_entries() == []


def test_a_brand_new_code_in_directions_is_passed_through_not_registered(web):
    cid, tx = save_call(web, TESTN, outputs=[NOTE], directions="Keep [PERSON_1] and [PERSON_2.first] as they are.")
    with store_of(web) as s:
        assert s.get_transcript(tx)["directions"] == "Keep [PERSON_1] and [PERSON_2.first] as they are."
        assert s.load_registry(cid).code_entries() == []
    assert not any(has_token(v) for v in entity_values(web, cid))


def test_directions_shown_with_real_names_only_for_names_that_would_hide_again():
    reg = Registry()
    ent = reg.add_person("Maria Lopez")[0]
    local = reg.add_local_person("Mark")
    text = f"Tell {ent.placeholder('first')} and {local.placeholder()} and [PERSON_9] and {ent.placeholder()}."
    shown = wf.directions_for_display(reg, text)
    assert shown == f"Tell Maria and {local.placeholder()} and [PERSON_9] and Maria Lopez."      # a hidden-here word stays a code


def make_damaged(tmp_path):
    """A data folder holding what the old bug saved, for Testn and Testj."""
    web = Session(make_app(tmp_path))
    ids = []
    for first in ("Testn", "Testj"):
        cid = web.post("/clients", {"first_name": first}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
        with store_of(web) as s:
            reg = Registry()
            reg.add_person(f"{first} Person")
            reg.add_value("EMAIL", f"{first.lower()}@example.test")
            for n, code in enumerate(("[PERSON_1]", "[PERSON_2.first]"), 3):
                junk = Entity("PERSON", n, {None: code})
                reg.entities.append(junk)
                reg._index[("PERSON", code.lower())] = (junk, None)
            mixed = reg.add_person("Real Mixed")[0]
            mixed.forms["nick"] = "[PERSON_1]"
            s.save_registry(cid, reg)
        ids.append(cid)
    return web, ids


def test_check_reports_a_code_stored_as_a_name_without_showing_it_and_fix_removes_only_that(tmp_path, monkeypatch, capsys):
    web, ids = make_damaged(tmp_path)
    folder = web.c.app.state.data_dir
    problems = check(folder)
    codes = [p for p in problems if "holds a code" in p]
    assert len(codes) == 6 and all("[PERSON_" not in p and "PERSON_1]" not in p for p in problems)
    assert any("PERSON_3 holds a code" in p for p in codes) and any("PERSON_5" in p for p in codes)
    with store_of(web) as s:
        real = {c: {(e.type, e.n): dict(e.forms) for e in s.load_registry(c).entities if (e.type, e.n) in {("PERSON", 1), ("EMAIL", 1)}}
                for c in ids}
    # the command line: --fix prints counts only
    monkeypatch.setenv("MATTER_WORKBENCH_HOME", str(folder))
    assert check_main(["--fix"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Removed 4 hidden-name entries that held a code and 2 code forms in 2 clients.")
    assert "[" not in out and "Testn" not in out and "Person" not in out
    assert check(folder) == []
    with store_of(web) as s:
        for c in ids:
            reg = s.load_registry(c)
            assert reg.code_entries() == []
            assert {(e.type, e.n) for e in reg.entities} == {("PERSON", 1), ("EMAIL", 1), ("PERSON", 5)}
            assert {k: dict(reg.entity(*k).forms) for k in real[c]} == real[c]          # the real entries are untouched
            assert reg.entity("PERSON", 5).forms == {None: "Real Mixed", "first": "Real", "last": "Mixed"}   # only the code form went
            assert reg.high["PERSON"] >= 4                                  # the removed numbers are never reused
        assert s.load_registry(ids[0]).add_person("Next Person")[0].n > 5
    assert fix(folder) == {"clients": 0, "entries": 0, "forms": 0}          # nothing left to change


def test_fix_leaves_a_clean_folder_byte_for_byte_alone(tmp_path):
    web = Session(make_app(tmp_path))
    cid, tx = save_call(web, TESTN, outputs=[NOTE], directions="Be brief.")
    path = web.c.app.state.data_dir / "clients" / cid / "client.json"
    before = path.read_bytes()
    assert fix(web.c.app.state.data_dir) == {"clients": 0, "entries": 0, "forms": 0}
    assert path.read_bytes() == before


def test_the_hidden_names_page_flags_a_code_entry_and_can_delete_it(tmp_path):
    web, ids = make_damaged(tmp_path)
    cid = ids[0]
    page = web.get(f"/clients/{cid}/registry").text
    assert page.count("holds a hidden-name code instead of a real name") == 3          # two entries and the mixed one
    assert web.post(f"/clients/{cid}/registry/delete", {"type": "PERSON", "n": "3"}, follow_redirects=False).status_code == 303
    assert web.post(f"/clients/{cid}/registry/delete", {"type": "PERSON", "n": "4"}, follow_redirects=False).status_code == 303
    assert web.get(f"/clients/{cid}/registry").text.count("holds a hidden-name code instead of a real name") == 1      # the mixed one
    added = web.post(f"/clients/{cid}/registry/add", {"type": "PERSON", "value": "[PERSON_1]"})
    assert "cannot be added" in added.text


# ---- 8. the connector sentence ------------------------------------------------------------------------------

def test_the_save_output_sentence_appears_only_when_the_connector_is_on(web):
    cid, tx = save_call(web, TESTN, outputs=[NOTE])
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note for [PERSON_1].")
    body = {"text": "Make it shorter.", "version": 1}
    off_copy = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE]}).json()["text"]
    off_change = web.post_json(f"/transcripts/{tx}/outputs/{NOTE}/request-change", body).json()["text"]
    assert "save_output" not in off_copy and "save_output" not in off_change
    assert f"Reply with each output under a line that reads exactly like [OUTPUT: {NOTE}]" in off_copy
    assert f"Reply with the revised text under a line that reads exactly [OUTPUT: {NOTE}]" in off_change
    web.post("/settings", {"section": "connector", "mcp_enabled": "1"}, follow_redirects=False)
    on_copy = web.post_json(f"/transcripts/{tx}/copy", {"outputs": [NOTE]}).json()["text"]
    on_change = web.post_json(f"/transcripts/{tx}/outputs/{NOTE}/request-change", body).json()["text"]
    assert on_copy.count("save_output") == 1 and on_change.count("save_output") == 1
    assert "If you do not have it, reply with each output under a line" in on_copy
    assert "If you do not have it, reply with the revised text under a line" in on_change


# ---- 9. the import check list -----------------------------------------------------------------------------------

def test_the_import_check_lists_each_replaced_word_with_its_code_and_stores_nothing_extra(web):
    cid, tx = save_call(web, TESTN, outputs=[NOTE])
    reply = f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {NOTE}]\nNote for Testn Reviewwords. Sam Officer will call, Sam Officer."
    chk = web.post(f"/clients/{cid}/import", {"text": reply, "kind": "output", "tx_id": tx})
    assert "Replaced before saving" in chk.text
    items = re.findall(r'<li><span class="was">([^<]*)</span> became <code>([^<]*)</code>', chk.text)
    with store_of(web) as s:
        reg = s.load_registry(cid)
        testn, sam = reg.lookup("PERSON", "Testn Reviewwords")[0].placeholder(), reg.lookup("PERSON", "Sam Officer")[0].placeholder()
    assert items == [("Testn Reviewwords", testn), ("Sam Officer", sam)]
    assert "2 times" in chk.text
    content = h.unescape(re.search(r'<textarea name="content"[^>]*>(.*?)</textarea>', chk.text, re.S).group(1))
    assert "Testn" not in content and "Sam Officer" not in content
    web.post(f"/clients/{cid}/import/save", {"content": content, "kind": "output", "tx_id": tx})
    with store_of(web) as s:
        assert "Testn" not in json.dumps(s.list_outputs(tx, NOTE))
    clean = web.post(f"/clients/{cid}/import", {"text": f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {NOTE}]\nNothing named.", "kind": "output"})
    assert "Replaced before saving" not in clean.text


# ---- 5. summary import ------------------------------------------------------------------------------------------

def test_importing_a_summary_has_one_sentence_of_help_and_no_output_or_transcript_choice(web):
    cid, tx = save_call(web, TESTN)
    page = web.get(f"/clients/{cid}/import?kind=summary").text
    section = page.split("<section>")[1].split("</section>")[0]
    assert "<h2>Import a summary</h2>" in section and section.count('class="muted"') == 1
    assert "<select" not in section and 'name="kind" value="summary"' in section
    bad = web.post(f"/clients/{cid}/import", {"text": "  ", "kind": "summary"})
    assert "Import a summary</h2>" in bad.text and "<select" not in bad.text.split("<section>")[1]
    out = web.get(f"/clients/{cid}/import").text
    assert "Import Claude's reply</h2>" in out and out.count("<select") == 3


# ---- 7. "Name: text" lines ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, speakers", [
    ("Dana Whitaker: Thanks for calling.\nTomas Beltran: Hello, it is Tomas.\n", ["Dana Whitaker", "Tomas Beltran"]),
    ("Caller: Hi there.\nAgent: How can I help?\n", ["Caller", "Agent"]),
    ("Dana: Thanks for calling.\nTomas: Hello.\nDana: Who is this?\n", ["Dana", "Tomas", "Dana"]),
    ("Dana Whitaker: Thanks for calling.\nIt was a long day.\nTomas Beltran: Hello, it is Tomas.\n", ["Dana Whitaker", "Tomas Beltran"]),
])
def test_name_colon_text_lines_are_read_as_speakers(text, speakers):
    reading = parse_lenient(text)
    assert [t.speaker for t in reading.turns] == speakers
    assert not any("No speaker lines" in n for n in reading.notes)


@pytest.mark.parametrize("text", [
    "Note: call back on Friday.\nSubject: the lease\n",
    "Plan: call back.\nThe client was upset and called twice. She wants a refund and a copy of the lease.\nShe will come in on Friday.\nPerson: x\n",
    "Reminder: the keys.\nShe said hello.\nWe talked about the lease for a long time.\n",
    "Hello there. This is a plain paragraph with no labels.",
])
def test_notes_and_headings_are_still_plain_text(text):
    assert parse_lenient(text).turns == []


def test_a_name_colon_call_scrubs_the_names_for_certain(web):
    call = "Dana Whitaker: Thanks for calling.\nTomas Beltran: Hello, it is Tomas. My number is on file.\n"
    r = paste(web, call)
    assert "No speaker lines were recognized" not in r.text
    cid = re.search(r"/clients/([\w-]+)/intake/save", r.text).group(1)
    saved = web.post(f"/clients/{cid}/intake/save", review_form(r.text), follow_redirects=False)
    assert saved.status_code == 303


# ---- 11. archived page -------------------------------------------------------------------------------------------

def test_an_archived_client_page_has_only_the_archived_bar(web):
    cid, tx = save_call(web, TESTN)
    after = web.post(f"/clients/{cid}/archive", {}, follow_redirects=True).text
    main = after.split("<main")[1]
    assert main.count("Archived.") == 1 and "Client archived" not in after and "· archived" not in after
    assert "archivebar" in after and ">Restore</button>" in after
    restored = web.post(f"/clients/{cid}/archive", {}, follow_redirects=True).text
    assert "Client restored to the sidebar." in restored and "archivebar" not in restored


# ---- 12. compare -------------------------------------------------------------------------------------------------

def test_a_change_in_punctuation_alone_is_not_marked():
    rows = wf.diff_rows("Call Friday, then email Dana.", "Call Friday then email Dana!")
    assert [kind for kind, _ in rows] == ["del", "add"]
    assert all(not hot for _, parts in rows for _, hot in parts)
    rows = wf.diff_rows("Call Friday, then email Dana.", "Call Monday, then email Dana.")
    marked = [t for _, parts in rows for t, hot in parts if hot]
    assert any("Friday" in t for t in marked) and any("Monday" in t for t in marked)
    dash = wf.diff_rows("a - b", "a b")
    assert [kind for kind, _ in dash] == ["del", "add"] and not any(hot for _, parts in dash for _, hot in parts)
    assert "".join(t for t, _ in dash[0][1]) == "a - b"


def test_the_compare_list_has_no_version_that_repeats_previous(web):
    cid, tx = save_call(web, TESTN)
    with store_of(web) as s:
        for n in range(1, 4):
            s.add_output(cid, tx, NOTE, f"Note v{n}.")
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    sel = re.search(rf'<select id="cmp-{NOTE}".*?</select>', page, re.S).group(0)
    assert re.findall(r'<option value="([^"]*)"', sel) == ["", "prev", "1"]            # v2 is "prev"
    assert "Previous, v2" in sel
    by_number = web.get(f"/clients/{cid}?tx={tx}&view=outputs&cmp-{NOTE}=2").text      # an old link to v2 shows Previous
    assert '<option value="prev" selected>' in by_number and "Changes from v2 to v3" in by_number


# ---- 2, 10. markup the script relies on -----------------------------------------------------------------------------

def test_the_reasons_beside_disabled_buttons_can_be_cleared_by_the_script(web):
    cid, tx = save_call(web, TESTN)
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note.")
        s.add_transcript(cid, "[PERSON_1]: an older call", None)
    out = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert 'data-status data-reason="1">Type a change first</span>' in out
    js = (ROOT / "app" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "out.dataset.reason" in js and "data-tx-count" in out and "data-tx-count" in js
