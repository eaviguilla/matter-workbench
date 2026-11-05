"""The checker that says whether a Claude reply follows the Project instructions, tried on good and bad replies."""
import pytest

from app import forms
from app.outputs import FORM_SLUGS, TEXT_SLUGS
from scripts.check_claude_reply import check_reply

NOTE, CAL, FORM = TEXT_SLUGS
PRO, EST, GEN, TRU = FORM_SLUGS
HEAD = "[CLIENT: Maria-20261102-1 | TX: TX-20261102-1]"


def section(slug, body):
    return f"[OUTPUT: {slug}]\n{HEAD}\n{body}\n"


def answers(slug, given):
    return "\n".join(f"[ANSWER: {n}]\n{given.get(n, 'Not discussed')}" for n in range(1, forms.count(slug) + 1))


GOOD_NOTE = "DECEDENT\n- [PERSON_1] died in 2024\nNEXT STEPS\n- Jordan to review"
GOOD_CAL = "[PERSON_1] - probate. Referral from a friend, house in Irvine, wants to sell. Prefers phone."
GOOD_FORM = "[PERSON_1] - probate. House in Irvine, wants to sell, family agrees. Prefers phone."
PROBATE = {1: "[PERSON_2]", 2: "None.", 5: "09/14/2026", 7: "Yes", 8: "[ADDRESS_1]", 9: "Yes", 10: "Spouse | Children",
           11: "No", 13: "No", 16: "[PERSON_1] - probate."}


def good():
    return section(NOTE, GOOD_NOTE) + section(CAL, GOOD_CAL) + section(FORM, GOOD_FORM) + section(PRO, answers(PRO, PROBATE))


def test_a_correct_reply_has_no_problems():
    assert check_reply(good(), [NOTE, CAL, FORM, PRO]) == []


@pytest.mark.parametrize("old, new, expect", [
    (GOOD_CAL, GOOD_CAL + "\nSecond line.", "not one paragraph"),
    (GOOD_CAL, "**" + GOOD_CAL + "**", "not plain text"),
    (GOOD_CAL, GOOD_CAL.replace(". Referral", " — referral"), "em dash"),
    (GOOD_CAL, GOOD_CAL + " Call 949-555-0182.", "phone number"),
    (GOOD_CAL, GOOD_CAL + " [PERSON_9.nickname]", "not in the right format"),
    (GOOD_FORM, GOOD_FORM + " " + "x" * 200, "over 250"),
    (GOOD_NOTE, "decedent\n- died", "no CAPS section header"),
])
def test_text_output_rules(old, new, expect):
    assert any(expect in p for p in check_reply(good().replace(old, new), [NOTE, CAL, FORM, PRO])), expect


@pytest.mark.parametrize("given, expect", [
    ({7: "Yes, two homes"}, "extra words"),
    ({7: "N/A"}, "write Not discussed"),
    ({7: "not discussed."}, "exactly Not discussed"),
    ({5: "September 14, 2026"}, "Not a date"),
    ({2: "Maybe"}, "Not one of the options"),
    ({10: "Cousins"}, "Not one of the options"),
    ({1: "x" * 260}, "over 250"),
    ({1: "Answer: [PERSON_2]"}, "starts with a label"),
    ({1: "line one\nline two"}, "line break"),
    ({7: "No", 8: "[ADDRESS_1]"}, "is not saved"),
])
def test_form_answer_rules(given, expect):
    body = answers(PRO, {**PROBATE, **given})
    assert any(expect in p for p in check_reply(section(PRO, body), [PRO])), (given, expect)


def test_a_first_version_must_answer_every_question_and_a_change_need_not():
    body = "[ANSWER: 1]\n[PERSON_2]\n[ANSWER: 7]\nYes"
    assert any("no answer for" in p for p in check_reply(section(PRO, body), [PRO]))
    assert check_reply(section(PRO, body), [PRO], first_version=False) == []


def test_missing_extra_unknown_and_repeated_outputs_are_reported():
    text = section(NOTE, GOOD_NOTE) + section(NOTE, GOOD_NOTE) + section("clio-memo", "x")
    problems = " | ".join(check_reply(text, [NOTE, CAL]))
    assert "written 2 times" in problems and "unknown output id" in problems and f"{CAL} is missing" in problems


def test_an_output_must_start_with_the_header_line_and_use_only_placeholders_from_the_message():
    text = good().replace(HEAD + "\n", "", 1)
    assert any("header line" in p for p in check_reply(text, [NOTE, CAL, FORM, PRO]))
    assert any("[PERSON_2] is not in the message" in p for p in check_reply(good(), [NOTE, CAL, FORM, PRO], message="[PERSON_1] [ADDRESS_1]"))


def test_estate_form_follow_ups_follow_their_parent():
    ok = answers(EST, {1: "Yes", 2: "[PERSON_2]", 4: "Yes", 12: "None!"})
    assert check_reply(section(EST, ok), [EST]) == []
    bad = answers(EST, {1: "Yes", 3: "Single"})
    assert any("answer 3" in p and "not saved" in p for p in check_reply(section(EST, bad), [EST]))


def test_a_note_for_jules_below_a_marker_is_reported_because_the_app_would_save_it_as_output():
    text = good() + "Note for Jules: the caller gave a phone number."
    assert any("Note for Jules" in p for p in check_reply(text, [NOTE, CAL, FORM, PRO]))
    assert check_reply("Could not save.\nNote for Jules: nothing.\n" + good(), [NOTE, CAL, FORM, PRO]) == []


def test_a_note_or_answer_that_reports_a_gap_is_reported_but_the_exact_words_in_an_answer_are_not():
    problems = check_reply(good().replace(GOOD_CAL, GOOD_CAL + " What she wants was not stated."), [NOTE, CAL, FORM, PRO])
    assert any("reports a gap" in p for p in problems)
    notes = {**PROBATE, 16: "[PERSON_1] - probate. Entry 5 left Not discussed because no date was given."}
    assert any("reports a gap" in p for p in check_reply(section(PRO, answers(PRO, notes)), [PRO]))
    assert check_reply(section(PRO, answers(PRO, PROBATE)), [PRO]) == []
