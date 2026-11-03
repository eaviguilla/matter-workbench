"""Every layout of a speaker turn the parser accepts, and the ones it must refuse."""
import pytest

from app.scrub.parse import parse_transcript

OK = {
    "one line": "• Dana Whitaker 0:01\nHi there.\n",
    "time on next line": "• Dana Whitaker\n0:01\nHi there.\n",
    "bullet, name, time each on a line": "•\nDana Whitaker\n0:01\nHi there.\n",
    "bullet alone, name and time together": "•\nDana Whitaker 0:01\nHi there.\n",
    "blank lines between parts": "•\n\nDana Whitaker\n\n0:01\nHi there.\n",
}


@pytest.mark.parametrize("name", OK)
def test_accepted_layouts(name):
    text = OK[name]
    p = parse_transcript(text)
    assert p.issues == []
    (turn,) = p.turns
    assert text[slice(*turn.speaker_span)] == "Dana Whitaker" and turn.timestamp == "0:01"
    assert text[slice(*turn.body_span)].strip() == "Hi there."


def test_two_turns_in_the_split_layout_keep_their_own_text():
    text = "•\nDana\n0:01\nOne.\n•\nTomas\n0:05\nTwo.\n"
    a, b = parse_transcript(text).turns
    assert text[slice(*a.body_span)].strip() == "One." and text[slice(*b.body_span)].strip() == "Two."


@pytest.mark.parametrize("text", ["•\n", "•\n0:01\nHi\n", "• \n\n", "hello"])
def test_refused_layouts_report_an_issue(text):
    assert parse_transcript(text).issues
