"""The same call in a different layout must scrub to the same placeholders, with the same registry."""
import re

import pytest

from app.rehydrate import PLACEHOLDER_RE
from app.scrub.evaluate import load_annotated
from app.scrub.parse import parse_transcript
from app.scrub.pipeline import scrub_transcript
from app.scrub.registry import Registry
from tests.webhelp import FIXTURES

PATHS = sorted(FIXTURES.glob("*.ann.txt"))


def original(path) -> str:
    return load_annotated(path.stem, path.read_text(encoding="utf-8")).text


def split_layout(text: str) -> str:
    """Rewrite every turn as bullet, name and time on separate lines."""
    parsed = parse_transcript(text)
    out = []
    for t in parsed.turns:
        name = text[slice(*t.speaker_span)]
        body = text[slice(*t.body_span)].strip("\n")
        out.append(f"•\n{name}\n{t.timestamp}\n{body}\n")
    return "".join(out)


def blank_lines(text: str) -> str:
    return split_layout(text).replace("\n", "\n\n")


def crlf(text: str) -> str:
    return split_layout(text).replace("\n", "\r\n")


def trailing_space(text: str) -> str:
    return split_layout(text).replace("\n", "  \n")


def placeholders(scrubbed: str) -> list:
    return [m.group().replace(" ", "") for m in PLACEHOLDER_RE.finditer(scrubbed)]


def run(text: str):
    reg = Registry()
    res = scrub_transcript(text, reg)
    return placeholders(res.text), reg.to_dict(), sorted(f.text for f in res.flags)


@pytest.mark.parametrize("variant", [split_layout, blank_lines, crlf, trailing_space])
@pytest.mark.parametrize("path", PATHS, ids=[p.stem[:12] for p in PATHS])
def test_layout_does_not_change_the_result(path, variant):
    base = original(path)
    assert run(variant(base)) == run(base)


def leaked(text: str, ann) -> list:
    """Tagged values that are still in the scrubbed text, whole."""
    scrubbed = scrub_transcript(text, Registry()).text
    return sorted({ann.text[s:e] for s, e, _, _ in ann.spans if ann.text[s:e] in scrubbed})


@pytest.mark.parametrize("path", PATHS, ids=[p.stem[:12] for p in PATHS])
def test_the_split_layout_leaks_no_more_than_the_one_line_layout(path):
    ann = load_annotated(path.stem, path.read_text(encoding="utf-8"))
    assert leaked(split_layout(ann.text), ann) == leaked(ann.text, ann)
