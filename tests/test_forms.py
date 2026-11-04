"""The intake form outputs: reading answers, saving them as versions, the page, inline edits and the connector."""
import json
import re

import pytest

from app import forms
from app import workflow as wf
from app.outputs import FORM_SLUGS, TEXT_SLUGS
from mcp_server.server import save_output
from tests.test_outputs import copy, do_import, env, store_of, textarea  # noqa: F401  (env is a fixture)

PRO, EST, GEN, TRU = FORM_SLUGS
NOTE = TEXT_SLUGS[0]


def reply(cid, tx, slug, body):
    return f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {slug}]\n{body}"


def versions(web, tx, slug):
    with store_of(web) as s:
        return [o["content"] for o in s.list_outputs(tx, slug)]


# ---- the parser ---------------------------------------------------------------------------------------

def test_the_forms_have_the_question_counts_asked_for():
    assert forms.count(PRO) == 16 and forms.count(EST) == 19 and forms.count(GEN) == 5
    assert forms.count(TRU) == 9


def test_the_estate_plan_form_follows_the_clio_page():
    """Clio shows a follow-up only after a Yes or No, and a checkbox question takes any of three options. Each
    follow-up is its own entry that names the earlier answer that opens it."""
    q = forms.DETAILS[EST]
    assert [x.text for x in q] == list(forms.QUESTIONS[EST]) and len(q) == forms.count(EST)
    for n, x in enumerate(q, 1):
        assert x.kind in ("text", "yesno", "checkbox")
        if x.when:
            parent, answer = x.when
            assert parent < n and (q[parent - 1].kind == "yesno" and answer in ("Yes", "No") or answer in q[parent - 1].options)
        if x.kind == "text":
            assert x.limit == 255                      # every text box on the page takes 255 characters
        else:
            assert x.limit is None
    assert {n: x.when for n, x in enumerate(q, 1) if x.when} == {
        2: (1, "Yes"), 3: (1, "No"), 9: (8, "Yes"), 10: (8, "Yes"), 14: (13, "Yes"), 16: (15, "No"), 19: (18, "Yes")}
    assert q[11].kind == "checkbox" and len(q[11].options) == 3 and q[11].options[2] == "None!"
    assert q[13].clio == q[18].clio == "Please explain." and q[13].text != q[18].text    # same title on Clio, told apart here


def test_the_probate_form_follows_the_clio_page():
    q = forms.DETAILS[PRO]
    assert [x.text for x in q] == list(forms.QUESTIONS[PRO]) and len(q) == forms.count(PRO)
    assert [x.kind for x in q] == ["text", "checkbox", "text", "text", "date", "textarea", "yesno", "text", "yesno",
                                   "checkbox", "yesno", "text", "yesno", "text", "text", "textarea"]
    for n, x in enumerate(q, 1):
        if x.when:
            parent, answer = x.when
            assert parent < n and (q[parent - 1].kind == "yesno" and answer in ("Yes", "No") or answer in q[parent - 1].options)
        assert (x.limit == 255) == (x.kind == "text")          # the long text areas have no practical limit
    assert {n: x.when for n, x in enumerate(q, 1) if x.when} == {8: (7, "Yes"), 9: (7, "Yes"), 12: (11, "Yes"), 14: (13, "Yes")}
    assert q[1].options[-1] == "Not sure." and len(q[1].options) == 4
    assert q[9].options == ("Spouse", "Children", "Parent", "Sibling")
    assert q[10].clio.endswith("loved one’s belongings or affairs?") and q[11].clio == "Please explain."


def test_the_general_intake_form_follows_the_clio_page():
    q = forms.DETAILS[GEN]
    assert [x.text for x in q] == list(forms.QUESTIONS[GEN]) and len(q) == forms.count(GEN)
    assert [x.kind for x in q] == ["checkbox", "text", "radio", "checkbox", "text"]
    assert q[0].options == ("Estate Planning", "Probate", "Trust Administration", "Other")
    assert q[2].options == ("Phone Call", "Email", "Text Message")
    assert q[3].options == ("Referral", "Online", "Other")
    assert [x.limit for x in q] == [None, 255, None, None, 255] and not any(x.when for x in q)
    assert q[4].text.startswith("Next Steps: The lead attorney, Jordan, will review")
    from app.outputs import NAMES
    assert NAMES[GEN] == "General Intake Form" and wf.is_form(GEN)


def test_the_trust_admin_form_follows_the_clio_page():
    """A follow-up can be opened by a radio option as well as by a Yes or No."""
    q = forms.DETAILS[TRU]
    assert [x.text for x in q] == list(forms.QUESTIONS[TRU]) and len(q) == forms.count(TRU)
    assert [x.kind for x in q] == ["text", "radio", "text", "radio", "text", "yesno", "text", "text", "textarea"]
    for n, x in enumerate(q, 1):
        if x.when:
            parent, answer = x.when
            assert parent < n and (q[parent - 1].kind == "yesno" and answer in ("Yes", "No") or answer in q[parent - 1].options)
        assert (x.limit == 255) == (x.kind == "text")
    assert {n: x.when for n, x in enumerate(q, 1) if x.when} == {3: (2, "Not available"), 5: (4, "Not available"), 7: (6, "Yes")}
    assert q[1].options == q[3].options == ("Mail", "Drop Off", "Email", "Not available")
    assert q[1].text.endswith("(trust, will, etc.)?") and q[3].text.endswith("(trust, will, etc.)?")   # as Clio has it
    assert q[2].clio == q[4].clio == "When will it be available?" and q[2].text != q[4].text
    assert q[5].clio.endswith("loved one’s belongings or affairs?") and q[6].clio == "Please explain."
    from app.outputs import NAMES, SHORT_NAMES
    assert NAMES[TRU] == "Trust Admin Intake Form" and SHORT_NAMES[TRU] == "Trust admin" and wf.is_form(TRU)
    assert forms.hint(TRU, 3) == "Only if answer 2 is Not available. 255 characters at most."
    assert forms.hint(TRU, 2) == "One of: Mail | Drop Off | Email | Not available"


@pytest.mark.parametrize("slug, answers, expected", [
    (TRU, {2: "Not available", 4: "Email"}, {3: "open", 5: "closed", 7: "unset"}),
    (TRU, {2: "Mail", 4: "Not available", 6: "Yes"}, {3: "closed", 5: "open", 7: "open"}),
    (TRU, {2: "Not discussed", 4: "", 6: "No"}, {3: "unset", 5: "unset", 7: "closed"}),
    (TRU, {2: "will email it later", 6: "Yes, a brother"}, {3: "unset", 5: "unset", 7: "open"}),
    (PRO, {7: "Yes", 11: "No", 13: "Not discussed"}, {8: "open", 9: "open", 12: "closed", 14: "unset"}),
    (PRO, {7: "Probably", 11: "Yes", 13: "No."}, {8: "unset", 9: "unset", 12: "open", 14: "closed"}),
    (EST, {1: "Yes", 8: "No", 13: "Yes", 15: "No", 18: "No"},
     {2: "open", 3: "closed", 9: "closed", 10: "closed", 14: "open", 16: "open", 19: "closed"}),
    (EST, {}, {2: "unset", 3: "unset", 14: "unset", 19: "unset"}),
])
def test_a_follow_up_is_open_closed_or_unset_by_its_parent_answer(slug, answers, expected):
    seen = forms.visibility(slug, answers)
    assert {n: seen[n][0] for n in expected} == expected
    for n, (state, parent, reason) in seen.items():
        assert (state == "always") == (parent is None) and bool(reason) == (state in ("closed", "unset"))


def test_a_closed_parent_closes_what_hangs_below_it_and_unset_is_never_closed():
    """No form has a follow-up of a follow-up today, so the chain rule is checked on a made-up form."""
    q = (forms.Question("A", "yesno"), forms.Question("B", "yesno", when=(1, "Yes")), forms.Question("C", when=(2, "Yes")))
    forms.QUESTIONS["t"], forms.DETAILS["t"] = tuple(x.text for x in q), q
    try:
        assert [forms.visibility("t", {1: "No", 2: "Yes"})[n][0] for n in (2, 3)] == ["closed", "closed"]
        assert [forms.visibility("t", {})[n][0] for n in (2, 3)] == ["unset", "unset"]
    finally:
        del forms.QUESTIONS["t"], forms.DETAILS["t"]


def test_choice_reads_yes_no_radio_and_checkbox_answers_and_flags_what_clio_cannot_pick():
    assert forms.choice(TRU, 2, "Drop off.") == (("Drop Off",), True)
    assert forms.choice(EST, 1, "yes, since 2001") == (("Yes",), False) and forms.choice(EST, 1, "Yesterday") is None
    assert forms.choice(EST, 12, "None! | A little! We have some documents done.")[0][0] == "None!"
    assert forms.choice(TRU, 2, "Not discussed") is None and forms.choice(TRU, 1, "Ana") is None
    assert forms.choice_problem(TRU, 2, "Mail") == "" and forms.choice_problem(TRU, 2, "Will email it").startswith("Not one of")
    assert forms.choice_problem(EST, 1, "Yes, married") == "Has extra words. Clio takes only Yes or No here."
    assert forms.choice_problem(TRU, 1, "Ana Ruiz") == "" and forms.choice_problem(TRU, 2, "Not discussed") == ""


@pytest.mark.parametrize("slug", FORM_SLUGS)
def test_every_follow_up_comes_after_its_parent_and_no_follow_up_is_a_parent(slug):
    q = forms.DETAILS[slug]
    for n, x in enumerate(q, 1):
        if x.when:
            assert x.when[0] < n and not q[x.when[0] - 1].when
    assert [x["n"] for x in forms.schema(slug)] == list(range(1, len(q) + 1))
    json.dumps(forms.schema(slug))


def test_the_numbering_of_each_form_is_pinned():
    """The stored answers and the Claude Project text are numbered by position. Moving, adding or dropping an entry
    renumbers every saved version, so this fails on purpose and says to change the Project text with it."""
    def at(slug, n, start):
        return forms.DETAILS[slug][n - 1].text.startswith(start)
    assert at(PRO, 1, "What was the name of your lo") and at(PRO, 16, "Is there anything else you")
    assert at(EST, 1, "Are you legally married?") and at(EST, 19, "Please explain. (anything else)")
    assert at(GEN, 1, "Matter Type:") and at(GEN, 5, "Next Steps: The lead attorney")
    assert at(TRU, 2, "Do you have a copy of the estate plan") and at(TRU, 4, "Do you have a copy of the death certificate")
    assert at(TRU, 9, "Is there anything else you")
    assert [forms.count(s) for s in FORM_SLUGS] == [16, 19, 5, 9]


def test_the_claude_project_question_lists_match_the_app():
    """docs/claude-project/JLC-CASE-NOTES-V2.md lists every question by number for Claude. It is pasted by hand, so
    this keeps it in step with app/forms.py: the text, the kind of each entry and the condition."""
    from pathlib import Path
    doc = Path(__file__).resolve().parent.parent / "docs" / "claude-project" / "JLC-CASE-NOTES-V2.md"
    if not doc.exists():
        pytest.skip("the Project notes are not in this copy")
    lines = doc.read_text(encoding="utf-8").splitlines()
    heads = {PRO: "Probate Intake Form questions:", EST: "Estate Plan - General Intake form questions:",
             GEN: "General Intake Form questions:", TRU: "Trust Admin Intake Form questions:"}
    kinds = {"yesno": "Yes or No", "text": "255", "textarea": "long text", "date": "date MM/DD/YYYY", "checkbox": "checkbox",
             "radio": "radio"}
    for slug, head in heads.items():
        start = lines.index(head) + 1
        listed = {}
        for line in lines[start:]:
            if not line.strip():
                break
            m = re.match(r"^(\d+) (.*?)((?: \[[^\]]*\])+)$", line)
            if m:
                listed[int(m[1])] = (m[2], m[3])
        assert sorted(listed) == list(range(1, forms.count(slug) + 1)), head
        for n, x in enumerate(forms.DETAILS[slug], 1):
            text, tags = listed[n]
            assert text == x.text, (head, n)
            assert kinds[x.kind] in tags, (head, n)
            assert ("only if" in tags) == bool(x.when), (head, n)
            if x.when:
                assert f"only if {x.when[0]} is {x.when[1]}" in tags or f"only if {x.when[0]} is {x.when[1]}]" in tags, (head, n)


def test_hints_say_when_a_question_is_asked_and_what_it_takes():
    assert forms.hint(GEN, 1) == "Any of: Estate Planning | Probate | Trust Administration | Other"
    assert forms.hint(GEN, 3) == "One of: Phone Call | Email | Text Message"
    assert forms.hint(GEN, 2) == "255 characters at most."
    assert forms.hint(EST, 1) == "Yes or No."
    assert forms.hint(EST, 2) == "Only if answer 1 is Yes. 255 characters at most."
    assert forms.hint(EST, 12).startswith("Any of: Yes! A full estate plan") and forms.hint(EST, 12).endswith("None!")
    assert forms.hint(PRO, 3) == "255 characters at most."
    assert forms.hint(PRO, 5) == "A date as MM/DD/YYYY." and forms.hint(PRO, 6) == ""
    assert forms.hint(PRO, 8) == "Only if answer 7 is Yes. 255 characters at most."
    assert forms.hint(PRO, 10) == "Any of: Spouse | Children | Parent | Sibling"
    assert forms.over(EST, 2, "x" * 255) == 0 and forms.over(EST, 2, "x" * 260) == 5
    assert forms.over(EST, 1, "x" * 999) == 0 and forms.over(PRO, 16, "x" * 9999) == 0 and forms.over(PRO, 1, "x" * 300) == 45


def test_answers_are_read_under_their_markers_and_a_missing_one_is_listed():
    p = forms.parse(PRO, "Intro that is dropped.\n[ANSWER: 1]\nAna Ruiz\n[ANSWER: 3]\nCalifornia\n[ANSWER: 4]\n")
    assert p.answers == {1: "Ana Ruiz", 3: "California"} and p.blanks == [4] and p.loose == "Intro that is dropped."
    assert forms.missing(PRO, p.answers) == [2] + list(range(4, 17))


def test_a_bold_marker_an_inline_answer_and_a_reordered_reply_are_read():
    p = forms.parse(PRO, "**[ANSWER: 2]** Yes, a will.\n## [ANSWER: 1]\nAna\n[ANSWER: 02]\nsecond")
    assert p.answers[1] == "Ana" and p.answers[2] == "Yes, a will." and p.dupes == [2]
    assert forms.parse(PRO, "[ANSWER: 99]\nx").unknown == [99] and forms.parse(PRO, "[ANSWER: 0]\nx").unknown == [0]
    assert forms.parse(PRO, "Just prose, no markers.").found is False


def test_render_is_canonical_and_merge_keeps_what_a_reply_skips():
    old = forms.render(PRO, {1: "Ana", 2: "Yes"})
    assert old.count("[ANSWER:") == 16 and old.startswith("[ANSWER: 1]\nAna\n\n[ANSWER: 2]\nYes")
    new = forms.merge(PRO, old, {2: "Not discussed", 3: "Texas"})
    got = forms.parse(PRO, new).answers
    assert got == {1: "Ana", 2: "Not discussed", 3: "Texas"} and forms.parse(PRO, new).blanks == [n for n in range(4, 17)]


def test_answer_markers_are_not_placeholders():
    from app.rehydrate import PLACEHOLDER_RE
    assert not PLACEHOLDER_RE.search("[ANSWER: 4]") and not PLACEHOLDER_RE.search(forms.render(PRO, {}))


# ---- import ------------------------------------------------------------------------------------------

def test_a_reply_saves_a_form_version_with_every_marker_and_a_later_reply_patches_it(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nA first answer\n[ANSWER: 3]\nCalifornia"))
    v1 = versions(web, tx, PRO)
    assert len(v1) == 1 and v1[0].count("[ANSWER:") == 16
    chk, _ = do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 3]\nNot discussed\n[ANSWER: 4]\nOrange"))
    assert "2 of 16" in chk.text
    v2 = versions(web, tx, PRO)[1]
    assert forms.parse(PRO, v2).answers == {1: "A first answer", 3: "Not discussed", 4: "Orange"}


def test_a_duplicate_unknown_or_marker_free_reply_blocks_the_whole_save(env):
    web, cid, tx, tmp = env
    for body in ("[ANSWER: 1]\nA\n[ANSWER: 1]\nB", "[ANSWER: 1]\nA\n[ANSWER: 17]\nB", "Only prose here."):
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
    assert re.findall(r'<section class="col" id="out-([a-z-]+)">', page) == [NOTE]       # only what was asked for is on the page
    assert page.index('class="board"') < page.index("Intake forms") < page.index(f'id="out-{PRO}"')
    assert "2 of 16 answered" in page and "Jump to:" in page
    assert page.count('class="answer"') == 2 and f'id="ans-{PRO}-1"' in page and f'id="ans-{PRO}-5"' in page
    assert "Copy all" in page and "Ask Claude to change this form" in page
    assert f'id="out-{EST}"' not in page and "Not requested" not in page and "Ask Claude for this" not in page
    assert f"/transcripts/{tx}/outputs/{PRO}/edit" in page and "<script>" not in page.replace("<script src", "")


def test_the_estate_plan_form_shows_hints_and_warns_about_an_answer_over_the_clio_limit(env):
    web, cid, tx, tmp = env
    copy(web, tx, [NOTE, EST])
    long = "x" * 260
    do_import(web, cid, reply(cid, tx, EST, f"[ANSWER: 1]\nYes\n[ANSWER: 2]\n{long}\n[ANSWER: 12]\nNone!"))
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    panel = page.split(f'id="out-{EST}"')[1]
    assert "3 of 18 answered" in panel          # answer 1 is Yes, so entry 3 (only if No) is not counted
    assert "Only if answer 1 is Yes. 255 characters at most." in panel and "Only if answer 8 is Yes." in panel
    assert panel.count("5 characters over what the Clio box takes") == 1
    edit = web.get(f"/transcripts/{tx}/outputs/{EST}/edit").text
    assert len(re.findall(r'name="answer_\d+"', edit)) == 19 and "Only if answer 15 is No." in edit
    assert edit.count("<select ") == 12 and edit.count("<textarea ") == 7         # a Yes or No entry is a drop-down


def test_a_yes_or_no_entry_shows_as_a_yes_or_no_pick_and_flags_extra_words(env):
    """Do they have special needs and Are they minors are Yes or No boxes on Clio, so a plain Yes shows as a pick, an
    answer with detail is flagged, and both can be set with Yes, No or Not discussed."""
    web, cid, tx, tmp = env
    copy(web, tx, [NOTE, EST])
    do_import(web, cid, reply(cid, tx, EST, "[ANSWER: 8]\nYes\n[ANSWER: 9]\nNo\n[ANSWER: 10]\nYes, Clara is 16"))
    panel = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text.split(f'id="out-{EST}"')[1]
    assert panel.count('class="answer pick pick-yes"') == 1 and panel.count('class="answer pick pick-no"') == 1
    assert panel.count("Has extra words. Clio takes only Yes or No here.") == 1
    assert panel.count('data-fill="No"') == 12 and "255 characters at most" not in panel.split('id="q-' + EST + '-9"')[1][:400]
    edit = web.get(f"/transcripts/{tx}/outputs/{EST}/edit").text
    assert '<select id="edit-answer-9"' in edit and '<option value="No" selected>' in edit
    assert "Yes, Clara is 16 (not Yes or No)" in edit
    for slug, n in ((PRO, 9), (EST, 9), (EST, 10)):
        assert forms.DETAILS[slug][n - 1].kind == "yesno" and forms.DETAILS[slug][n - 1].limit is None


def test_the_trust_admin_form_saves_and_shows_a_follow_up_opened_by_a_radio_option(env):
    web, cid, tx, tmp = env
    copy(web, tx, [NOTE, TRU])
    do_import(web, cid, reply(cid, tx, TRU, "[ANSWER: 1]\nAna Ruiz\n[ANSWER: 2]\nNot available\n[ANSWER: 3]\nNext month\n"
                                            "[ANSWER: 4]\nEmail\n[ANSWER: 5]\nNot discussed"))
    assert forms.parse(TRU, versions(web, tx, TRU)[-1]).answers == {1: "Ana Ruiz", 2: "Not available", 3: "Next month", 4: "Email", 5: "Not discussed"}
    panel = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text.split(f'id="out-{TRU}"')[1]
    assert "4 of 8 answered, 1 follow-up not shown in Clio" in panel and panel.count("Only if answer 2 is Not available. 255 characters at most.") == 1
    assert "One of: Mail | Drop Off | Email | Not available" in panel
    edit = web.get(f"/transcripts/{tx}/outputs/{TRU}/edit").text
    assert len(re.findall(r'name="answer_\d+"', edit)) == 9 and "Only if answer 4 is Not available." in edit


def panel_of(web, cid, tx, slug):
    return web.get(f"/clients/{cid}?tx={tx}&view=outputs").text.split(f'id="out-{slug}"')[1].split("</article>")[0]


def test_a_follow_up_clio_would_not_show_is_folded_when_empty_and_kept_visible_when_it_holds_an_answer(env):
    web, cid, tx, tmp = env
    copy(web, tx, [NOTE, TRU])
    do_import(web, cid, reply(cid, tx, TRU, "[ANSWER: 4]\nEmail\n[ANSWER: 5]\nNot discussed\n[ANSWER: 6]\nNo\n"
                                            "[ANSWER: 7]\nThey argue about the house"))
    panel = panel_of(web, cid, tx, TRU)
    assert "1 follow-up Clio does not show, because answer 4 is Email" in panel          # entry 5 sits in a closed row
    assert "Kept, but Clio shows this box only if answer 6 is Yes, and answer 6 is No. Copy all leaves it out." in panel and "1 kept answer Clio will not show" in panel
    assert "They argue about the house" in panel and 'id="ans-%s-7"' % TRU in panel     # an answer is never hidden
    fold = panel.split("<details>")[1].split("</details>")[0]
    assert 'id="q-%s-5"' % TRU in fold and 'id="q-%s-7"' % TRU not in fold                # entry 5 is inside the fold, entry 7 is not
    assert "2 of 7 answered" in panel
    everything = panel.split(f'id="all-{TRU}">')[1].split("</pre>")[0]
    assert "They argue about the house" not in everything and "Email" in everything       # Copy all leaves out a closed entry
    assert forms.parse(TRU, versions(web, tx, TRU)[-1]).answers[7] == "They argue about the house"   # stored text is whole


def test_changing_a_parent_answer_brings_a_closed_follow_up_back(env):
    web, cid, tx, tmp = env
    copy(web, tx, [NOTE, TRU])
    do_import(web, cid, reply(cid, tx, TRU, "[ANSWER: 6]\nNo\n[ANSWER: 7]\nA family quarrel"))
    assert "1 kept answer Clio will not show" in panel_of(web, cid, tx, TRU)
    r = web.post_json(f"/transcripts/{tx}/outputs/{TRU}/answers", {"n": 6, "text": "Yes", "version": 1})
    assert r.status_code == 200
    panel = panel_of(web, cid, tx, TRU)
    assert "kept answer" not in panel and "2 of 9 answered" in panel and "A family quarrel" in panel


def test_an_answer_that_is_not_an_option_is_warned_and_an_unsettled_parent_keeps_its_follow_up_listed(env):
    web, cid, tx, tmp = env
    copy(web, tx, [NOTE, TRU])
    do_import(web, cid, reply(cid, tx, TRU, "[ANSWER: 2]\nWill email it\n[ANSWER: 6]\nNot discussed"))
    panel = panel_of(web, cid, tx, TRU)
    assert "Not one of the options, so Clio cannot pick it." in panel
    assert "Answer 2 is not one of the options, so this box is kept in the list." in panel
    assert "Answer 6 is not settled, so this box is kept in the list." in panel and "not shown in Clio" not in panel


def test_the_edit_page_keeps_every_box_so_saving_it_never_clears_a_closed_answer(env):
    web, cid, tx, tmp = env
    copy(web, tx, [NOTE, TRU])
    do_import(web, cid, reply(cid, tx, TRU, "[ANSWER: 6]\nNo\n[ANSWER: 7]\nA family quarrel"))
    edit = web.get(f"/transcripts/{tx}/outputs/{TRU}/edit").text
    assert len(re.findall(r'name="answer_\d+"', edit)) == 9 and "A family quarrel" in edit
    assert "Clio does not show this box now, answer 6 is No." in edit
    do_import(web, cid, reply(cid, tx, TRU, "[ANSWER: 7]\nA different quarrel"))
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs&{TRU}=2&cmp-{TRU}=1").text
    assert "7. Please explain. (disagreements) (not shown in Clio)" in page.replace('<span class="qn">7.</span> ', "7. ")


def test_forms_are_never_ticked_unless_the_call_asked_for_them(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "n")
        s.add_output(cid, tx, PRO, forms.render(PRO, {1: "x"}))
        assert wf.preticked_outputs(s, [], []) == [] or PRO not in wf.preticked_outputs(s, [], [])
    copy(web, tx, [NOTE, PRO])
    page = web.get(f"/clients/{cid}?tx={tx}&view=transcript").text
    fields = page.split("<legend>Ask Claude for</legend>")[1].split("</fieldset>")[0]
    assert re.findall(r'value="([a-z-]+)"( checked)?', fields)[3:] == [(PRO, " checked"), (EST, ""), (GEN, ""), (TRU, "")]
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text         # both arrived, so nothing is waiting or ticked
    fields = page.split("<legend>Ask Claude for</legend>")[1].split("</fieldset>")[0]
    assert re.findall(r'value="([a-z-]+)"( checked)?', fields)[3:] == [(PRO, ""), (EST, ""), (GEN, ""), (TRU, "")]
    assert fields.count("on this page") == 2 and "waiting" not in fields


def test_only_what_was_asked_for_or_received_is_on_the_page_and_request_more_ticks_only_what_is_waiting(env):
    web, cid, tx, tmp = env
    copy(web, tx, [TRU])
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert 'class="board"' not in page and f'id="out-{TRU}"' in page and 'data-poll="/transcripts/' in page   # a form-only call still polls
    assert [b for b in re.findall(r'id="out-([a-z-]+)"', page)] == [TRU]
    assert "Waiting for Claude" in page and "Nothing asked for" not in page
    fields = page.split("<legend>Ask Claude for</legend>")[1].split("</fieldset>")[0]
    assert re.findall(r'value="([a-z-]+)"( checked)?', fields)[-1] == (TRU, " checked") and fields.count(" checked") == 1
    assert "waiting" in fields
    # a reply for an output nobody asked for is saved and then shows up, with the board sized to what is on the page
    do_import(web, cid, reply(cid, tx, NOTE, "A note."))
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    assert re.findall(r'<section class="col" id="out-([a-z-]+)">', page) == [NOTE] and '<div class="board" data-cols="1">' in page
    do_import(web, cid, reply(cid, tx, TEXT_SLUGS[1], "An overview."))
    assert '<div class="board" data-cols="2">' in web.get(f"/clients/{cid}?tx={tx}&view=outputs").text
    fields = web.get(f"/clients/{cid}?tx={tx}&view=outputs").text.split("<legend>Ask Claude for</legend>")[1].split("</fieldset>")[0]
    assert fields.count(" checked") == 1                                                    # still only the waiting form
    # asking for one more replaces the list, so the waiting one stays ticked and the received ones are not asked again
    assert wf.more_ticked([dict(slug=TRU, waiting=True), dict(slug=NOTE, waiting=False)]) == [TRU]


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
    for bad in ({"n": 17, "text": "x", "version": 2}, {"n": 1, "text": "[ANSWER: 3]\nx", "version": 2}, {"n": "1", "text": "x", "version": 2}):
        assert web.post_json(f"/transcripts/{tx}/outputs/{PRO}/answers", bad).status_code == 400
    assert web.post_json(f"/transcripts/{tx}/outputs/{NOTE}/answers", {"n": 1, "text": "x", "version": 1}).status_code == 400
    assert len(versions(web, tx, PRO)) == 2


def test_the_no_script_edit_page_has_one_box_per_question_and_clearing_a_box_clears_the_answer(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nAna\n[ANSWER: 2]\nYes"))
    page = web.get(f"/transcripts/{tx}/outputs/{PRO}/edit").text
    assert len(re.findall(r'name="answer_\d+"', page)) == 16
    data = {f"answer_{n}": "" for n in range(1, 17)} | {"answer_1": "Ana", "answer_5": "05/05/2026"}
    r = web.post(f"/transcripts/{tx}/outputs/{PRO}/edit?v=1", data, follow_redirects=False)
    assert r.status_code == 303
    assert forms.parse(PRO, versions(web, tx, PRO)[1]).answers == {1: "Ana", 5: "05/05/2026"}
    again = web.post(f"/transcripts/{tx}/outputs/{PRO}/edit?v=2", data)
    assert "Nothing changed" in again.text


# ---- scrub this and compare --------------------------------------------------------------------------

def test_scrub_this_keeps_the_markers_and_compare_lists_changed_questions(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 1]\nMaria Santos\n[ANSWER: 8]\nHer sister Lupita lives nearby"))
    do_import(web, cid, reply(cid, tx, PRO, "[ANSWER: 8]\nHer sister Lupita and brother live nearby"))
    page = web.get(f"/clients/{cid}?tx={tx}&view=outputs&{PRO}=2&cmp-{PRO}=prev").text
    assert "1 question changed, 15 unchanged" in page
    for v in versions(web, tx, PRO):
        assert forms.parse(PRO, v).unknown == [] and v.count("[ANSWER:") == 16


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
        assert "Quimby" not in got[-1]["content"] and got[-1]["content"].count("[ANSWER:") == 16
        assert forms.parse(PRO, got[-1]["content"]).unknown == []
        reg = s.load_registry(cid)
        n = next(e.n for e in reg.entities if e.type == "PERSON" and e.forms.get(None) == "Hartley Quimby")
        wf.delete_hidden_name(s, cid, "PERSON", n)
    with store_of(web) as s:
        got = s.list_outputs(tx2, PRO)
        assert got[-1]["source"] == "unhide" and "Hartley Quimby" in got[-1]["content"] and got[-1]["content"].count("[ANSWER:") == 16


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
