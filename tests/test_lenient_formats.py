"""Pasted transcripts come in many layouts. None of them may be refused, and none may leak the tagged names."""
import re

import pytest

from app.scrub.ner import NerModel
from app.scrub.parse import parse_lenient
from app.scrub.pipeline import scrub_transcript
from app.scrub.registry import Registry
from tests.fake_ner import FakeBackend


def model():
    """Stands in for the name model on the one thing the rules cannot see: a name with no speaker label."""
    return NerModel(backend_factory=lambda: FakeBackend({"Tomas Beltran": ("person", 0.95), "Beltran": ("person", 0.9)}))

BODY = [("Dana Whitaker", "Thanks for calling. Is this Tomas Beltran?"),
        ("Tomas Beltran", "Yes. I live at 418 Alder Street, Tacoma, WA 98402. My email is tomas@example.com."),
        ("Dana Whitaker", "Thank you, Tomas."), ("Tomas Beltran", "Thanks, Dana.")]

LAYOUTS = {
    "bullet split": lambda n, t, i: f"•\n{n}\n0:0{i}\n{t}\n",
    "bullet one line": lambda n, t, i: f"• {n} 0:0{i}\n{t}\n",
    "bullet time below": lambda n, t, i: f"• {n}\n0:0{i}\n{t}\n",
    "name and time": lambda n, t, i: f"{n}  0:0{i}\n{t}\n",
    "name, time in brackets": lambda n, t, i: f"{n} (0:0{i})\n{t}\n",
    "time first": lambda n, t, i: f"[0:0{i}] {n}: {t}\n",
    "colon": lambda n, t, i: f"{n}: {t}\n",
    "colon with blank lines": lambda n, t, i: f"{n}: {t}\n\n",
    "no speakers at all": lambda n, t, i: f"{t}\n",
    "other bullet": lambda n, t, i: f"● {n} 0:0{i}\n{t}\n",
}
SECRETS = ["Tomas Beltran", "Beltran", "418 Alder Street", "98402", "tomas@example.com"]


def build(layout) -> str:
    return "".join(LAYOUTS[layout](n, t, i) for i, (n, t) in enumerate(BODY))


@pytest.mark.parametrize("layout", LAYOUTS)
def test_every_layout_is_accepted_and_hides_the_identifiers(layout):
    res = scrub_transcript(build(layout), Registry(), ner=model())
    for secret in SECRETS:
        assert secret not in res.text, (layout, secret)
    assert re.search(r"\[PERSON_\d+", res.text)


@pytest.mark.parametrize("layout", [k for k in LAYOUTS if k != "no speakers at all"])
def test_speaker_names_are_known_in_every_layout_that_has_them(layout):
    reading = parse_lenient(build(layout))
    assert [t.speaker for t in reading.turns] == [n for n, _ in BODY]


def test_role_labels_are_not_treated_as_people():
    text = "Caller: Hi, I am Tomas Beltran.\nAgent: Hello Tomas.\nCaller: Thanks.\n"
    reading = parse_lenient(text)
    assert all(t.generic for t in reading.turns)
    res = scrub_transcript(text, Registry())
    assert "Caller" in res.text and "Agent" in res.text and "Beltran" not in res.text


def test_a_single_note_line_is_not_a_speaker():
    reading = parse_lenient("Note: the call went well.\nTomas Beltran said hello.\n")
    assert reading.turns == []


def test_text_before_the_first_speaker_is_still_scanned():
    res = scrub_transcript("Recorded for Tomas Beltran on 11/2\n•\nDana\n0:01\nHello.\n", Registry(), ner=model())
    assert "Beltran" not in res.text
