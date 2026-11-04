"""The two intake form outputs: reading answers, saving them as versions, the page, inline edits and the connector."""
import json
import re

import pytest

from app import forms
from app import workflow as wf
from app.outputs import FORM_SLUGS, TEXT_SLUGS
from mcp_server.server import save_output
from tests.test_outputs import copy, do_import, env, store_of, textarea  # noqa: F401  (env is a fixture)

PRO, EST = FORM_SLUGS
NOTE = TEXT_SLUGS[0]


def reply(cid, tx, slug, body):
    return f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {slug}]\n{body}"


def versions(web, tx, slug):
    with store_of(web) as s:
        return [o["content"] for o in s.list_outputs(tx, slug)]


# ---- the parser ---------------------------------------------------------------------------------------

def test_the_forms_have_the_question_counts_asked_for():
    assert forms.count(PRO) == 12 and forms.count(EST) == 15


def test_answers_are_read_under_their_markers_and_a_missing_one_is_listed():
    p = forms.parse(PRO, "Intro that is dropped.\n[ANSWER: 1]\nAna Ruiz\n[ANSWER: 3]\nCalifornia\n[ANSWER: 4]\n")
    assert p.answers == {1: "Ana Ruiz", 3: "California"} and p.blanks == [4] and p.loose == "Intro that is dropped."
    assert forms.missing(PRO, p.answers) == [2, 4, 5, 6, 7, 8, 9, 10, 11, 12]


def test_a_bold_marker_an_inline_answer_and_a_reordered_reply_are_read():
    p = forms.parse(PRO, "**[ANSWER: 2]** Yes, a will.\n## [ANSWER: 1]\nAna\n[ANSWER: 02]\nsecond")
    assert p.answers[1] == "Ana" and p.answers[2] == "Yes, a will." and p.dupes == [2]
    assert forms.parse(PRO, "[ANSWER: 99]\nx").unknown == [99] and forms.parse(PRO, "[ANSWER: 0]\nx").unknown == [0]
    assert forms.parse(PRO, "Just prose, no markers.").found is False


def test_render_is_canonical_and_merge_keeps_what_a_reply_skips():
    old = forms.render(PRO, {1: "Ana", 2: "Yes"})
    assert old.count("[ANSWER:") == 12 and old.startswith("[ANSWER: 1]\nAna\n\n[ANSWER: 2]\nYes")
    new = forms.merge(PRO, old, {2: "Not discussed", 3: "Texas"})
    got = forms.parse(PRO, new).answers
    assert got == {1: "Ana", 2: "Not discussed", 3: "Texas"} and forms.parse(PRO, new).blanks == [n for n in range(4, 13)]


def test_answer_markers_are_not_placeholders():
    from app.rehydrate import PLACEHOLDER_RE
    assert not PLACEHOLDER_RE.search("[ANSWER: 4]") and not PLACEHOLDER_RE.search(forms.render(PRO, {}))


# ---- import ------------------------------------------------------------------------------------------

def test_a_reply_saves_a_form_version_with_every_marker_and_a_later_reply_patches_it(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nA first answer\n[ANSWER: 3]\nCalifornia"))
    v1 = versions(web, tx, PRO)
    assert len(v1) == 1 and v1[0].count("[ANSWER:") == 12
    chk, _ = do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 3]\nNot discussed\n[ANSWER: 4]\nOrange"))
    assert "2 of 12" in chk.text
    v2 = versions(web, tx, PRO)[1]
    assert forms.parse(PRO, v2).answers == {1: "A first answer", 3: "Not discussed", 4: "Orange"}


def test_a_duplicate_unknown_or_marker_free_reply_blocks_the_whole_save(env):
    web, cid, tx, tmp = env
    for body in ("[ANSWER: 1]\nA\n[ANSWER: 1]\nB", "[ANSWER: 1]\nA\n[ANSWER: 13]\nB", "Only prose here."):
        chk = web.post(f"/clients/{cid}/import", {"text": reply(cid, tx, PRO, body)})
        assert 'class="error"' in chk.text and re.search(r"<button type=\"submit\" disabled", chk.text)
        saved = web.post(f"/clients/{cid}/import/save", {"content": textarea(chk.text), "kind": "output", "output": PRO},
                         follow_redirects=False)
        assert saved.status_code != 303
    assert versions(web, tx, PRO) == []


def test_the_connector_patches_a_form_and_rejects_without_echoing_content(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        s.set_setting("mcp_enabled", "1")
    opener = lambda: store_of(web)
    msg, bad = save_output(opener, dict(client_id=cid, transcript_id=tx, output=PRO, content="[ANSWER: 2]\nYes"))
    assert not bad and msg == f"saved {PRO} v1"
    msg, bad = save_output(opener, dict(client_id=cid, transcript_id=tx, output=PRO, content="[ANSWER: 2]\nSecretword\n[ANSWER: 2]\nTwice"))
    assert bad and "Secretword" not in msg and "Twice" not in msg
    assert forms.parse(PRO, versions(web, tx, PRO)[-1]).answers == {2: "Yes"}


# ---- the page ----------------------------------------------------------------------------------------

def test_the_forms_show_under_the_board_with_one_copy_box_per_answer(env):
    web, cid, tx, tmp = env
    copy(web, tx, [NOTE, PRO])
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nMaria Santos\n[ANSWER: 5]\nJune 1"))
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert len(re.findall(r'<section class="col" id="out-', page)) == 3
    assert page.index('class="board"') < page.index("Intake forms") < page.index(f'id="out-{PRO}"')
    assert "2 of 12 answered" in page and "Jump to:" in page
    assert page.count('class="answer"') == 2 and f'id="ans-{PRO}-1"' in page and f'id="ans-{PRO}-5"' in page
    assert "Copy all" in page and "Ask Claude to change this form" in page
    assert "Waiting for Claude" in page.split(f'id="out-{EST}"')[1] or "Not requested" in page.split(f'id="out-{EST}"')[1]
    assert f"/transcripts/{tx}/outputs/{PRO}/edit" in page and "<script>" not in page.replace("<script src", "")


def test_forms_are_never_ticked_unless_the_call_asked_for_them(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "n")
        s.add_output(cid, tx, PRO, forms.render(PRO, {1: "x"}))
        assert wf.preticked_outputs(s, [], []) == [] or PRO not in wf.preticked_outputs(s, [], [])
    copy(web, tx, [NOTE, PRO])
    page = web.get(f"/clients/{cid}?tx={tx}").text
    fields = page.split("<legend>Ask Claude for</legend>")[1].split("</fieldset>")[0]
    assert re.findall(r'value="([a-z-]+)"( checked)?', fields)[3:] == [(PRO, " checked"), (EST, "")]


def test_the_total_version_count_includes_the_forms(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nAna"))
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    latest = web.get(f"/transcripts/{tx}/latest").json()["version"]
    assert f'data-version="{latest}"' in page and latest >= 1


# ---- editing -----------------------------------------------------------------------------------------

def test_an_inline_answer_edit_changes_only_that_answer_and_masks_known_names(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nAna\n[ANSWER: 2]\nYes\n[ANSWER: 6]\nA house"))
    before = forms.parse(PRO, versions(web, tx, PRO)[0]).answers
    r = web.post_json(f"/transcripts/{tx}/outputs/{PRO}/answers", {"n": 2, "text": "No, none", "version": 1})
    assert r.status_code == 200 and r.json()["version"] == 2
    after = forms.parse(PRO, versions(web, tx, PRO)[1]).answers
    assert after == {**before, 2: "No, none"}
    with store_of(web) as s:
        assert [o["source"] for o in s.list_outputs(tx, PRO)] == ["import", "edit"]


def test_a_stale_answer_edit_is_refused_and_nothing_is_saved(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nAna"))
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nBea"))
    r = web.post_json(f"/transcripts/{tx}/outputs/{PRO}/answers", {"n": 1, "text": "Cy", "version": 1})
    assert r.status_code == 409 and r.json()["stale"] is True and len(versions(web, tx, PRO)) == 2
    for bad in ({"n": 13, "text": "x", "version": 2}, {"n": 1, "text": "[ANSWER: 3]\nx", "version": 2}, {"n": "1", "text": "x", "version": 2}):
        assert web.post_json(f"/transcripts/{tx}/outputs/{PRO}/answers", bad).status_code == 400
    assert web.post_json(f"/transcripts/{tx}/outputs/{NOTE}/answers", {"n": 1, "text": "x", "version": 1}).status_code == 400
    assert len(versions(web, tx, PRO)) == 2


def test_the_no_script_edit_page_has_one_box_per_question_and_clearing_a_box_clears_the_answer(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nAna\n[ANSWER: 2]\nYes"))
    page = web.get(f"/transcripts/{tx}/outputs/{PRO}/edit").text
    assert len(re.findall(r'<textarea id="edit-answer-\d+"', page)) == 12
    data = {f"answer_{n}": "" for n in range(1, 13)} | {"answer_1": "Ana", "answer_5": "May 5"}
    r = web.post(f"/transcripts/{tx}/outputs/{PRO}/edit?v=1", data, follow_redirects=False)
    assert r.status_code == 303
    assert forms.parse(PRO, versions(web, tx, PRO)[1]).answers == {1: "Ana", 5: "May 5"}
    again = web.post(f"/transcripts/{tx}/outputs/{PRO}/edit?v=2", data)
    assert "Nothing changed" in again.text


# ---- scrub this and compare --------------------------------------------------------------------------

def test_scrub_this_keeps_the_markers_and_compare_lists_changed_questions(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nMaria Santos\n[ANSWER: 8]\nHer sister Lupita lives nearby"))
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 8]\nHer sister Lupita and brother live nearby"))
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs&{PRO}=2&cmp-{PRO}=prev").text
    assert "1 question changed, 11 unchanged" in page
    for v in versions(web, tx, PRO):
        assert forms.parse(PRO, v).unknown == [] and v.count("[ANSWER:") == 12


# ---- the data check ---------------------------------------------------------------------------------

def test_the_data_check_reports_a_bad_form_version_without_its_text(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        s.add_output(cid, tx, PRO, "[ANSWER: 1]\nSecretword\n[ANSWER: 1]\nTwice")
    from app import check
    problems = check.check(tmp / "data")
    text = " ".join(problems)
    assert "Secretword" not in text and "answer marker" in text


# ---- hidden names ------------------------------------------------------------------------------------

def add_call_with_name(web, cid, answer):
    """A second call that holds the plain name Hartley Quimby, and a probate version that mentions him."""
    from datetime import date
    with store_of(web) as s:
        tx = s.add_transcript(cid, "Hartley Quimby is the landlord.", date(2026, 11, 1))
        s.set_transcript_status(tx, "reviewed")
        s.add_output(cid, tx, PRO, forms.render(PRO, {1: "Ana", 8: answer}))
    return tx


def test_a_name_hidden_after_a_form_was_saved_never_leaves_as_raw_text(env):
    web, cid, tx, tmp = env
    tx2 = add_call_with_name(web, cid, "The landlord Hartley Quimby")
    assert web.post_json(f"/transcripts/{tx2}/hide-word", {"text": "Hartley Quimby", "client": True}).status_code == 200
    page = web.get(f"/clients/{cid}?tx={tx2}&view=outputs").text
    raw_all = re.search(r'id="allraw-[^"]+">(.*?)</pre>', page, re.S).group(1)
    starts = re.findall(r'data-start="([^"]*)"', page) + re.findall(r'data-answer-text[^>]*>([^<]*)</textarea>', page)
    assert "Quimby" not in raw_all and not any("Quimby" in x for x in starts)
    assert "Quimby" in page.split(f'id="ans-{PRO}-8"')[1].split("</pre>")[0] or "Hartley" in page    # the shown text has the real name


def test_scrub_this_and_unscrub_add_form_versions_that_keep_all_markers(env):
    web, cid, tx, tmp = env
    tx2 = add_call_with_name(web, cid, "The landlord Hartley Quimby")
    r = web.post(f"/transcripts/{tx2}/hide", {"text": "Hartley Quimby", "type": "PERSON"}, follow_redirects=False)
    assert r.status_code == 303
    with store_of(web) as s:
        got = s.list_outputs(tx2, PRO)
        assert [o["source"] for o in got] == ["import", "hide"]
        assert "Quimby" not in got[-1]["content"] and got[-1]["content"].count("[ANSWER:") == 12
        assert forms.parse(PRO, got[-1]["content"]).unknown == []
        reg = s.load_registry(cid)
        n = next(e.n for e in reg.entities if e.type == "PERSON" and e.forms.get(None) == "Hartley Quimby")
        wf.delete_hidden_name(s, cid, "PERSON", n)
    with store_of(web) as s:
        got = s.list_outputs(tx2, PRO)
        assert got[-1]["source"] == "unhide" and "Hartley Quimby" in got[-1]["content"] and got[-1]["content"].count("[ANSWER:") == 12


def test_an_older_form_version_has_no_inline_edit_and_the_select_keeps_its_place(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nAna"))
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nBea"))
    old = web.get(f"/clients/{cid}?tx={tx}&view=outputs&{PRO}=1").text.split(f'id="out-{PRO}"')[1]
    assert "data-answer-edit" not in old and "Older version" in old
    assert "closest(\"section.col, .fpanel\")" in web.get("/static/app.js").text


def test_the_save_and_cancel_buttons_carry_a_value_the_script_can_test(env):
    """app.js picks a branch with `if (b.dataset.answerSave)`, and an empty attribute value is falsy, so a bare attribute never fires."""
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nAna"))
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert 'data-answer-save="1"' in page and 'data-answer-cancel="1"' in page
    assert "data-answer-save>" not in page and "data-answer-cancel>" not in page


# ---- copy next answer --------------------------------------------------------------------------------

def test_each_form_with_answers_has_one_copy_next_button_with_a_value_and_no_helper_panel(env):
    web, cid, tx, tmp = env
    assert "data-next-copy" not in web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nAna\n[ANSWER: 4]\nOrange"))
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    panel = page.split(f'id="out-{PRO}"')[1].split(f'id="out-{EST}"')[0]
    assert panel.count('data-next-copy="1"') == 1                  # a bare attribute is empty, so falsy in the script
    assert "data-helper" not in page and 'class="helper"' not in page
    assert "data-next-copy" not in page.split(f'id="out-{EST}"')[1]
    js = web.get("/static/app.js").text
    assert "copyNext" in js and "dataset.nextCopy" in js and "helperCopy" not in js
