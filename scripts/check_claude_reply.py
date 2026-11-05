"""Check a Claude reply against the format the app and the Project instructions ask for.

  python scripts/check_claude_reply.py reply.txt [--outputs clio-note,probate-intake-form] [--message message.txt]

The reply is read the way the Import page reads it: `[OUTPUT: id]` sections, each holding one output. With --message, the
Copy for Claude text the reply answers, every placeholder in the reply must also be in that message. Exit code 1 when a
problem is found. This checks the format only. Whether every fact came from the call has to be read by a person.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import forms, outputs, workflow as wf  # noqa: E402
from app.ids import HEADER_RE  # noqa: E402

PLACEHOLDER = re.compile(r"\[(?:PERSON|EMAIL|ADDRESS)_\d+(?:\.(?:first|last|rest|nick))?\]")
BRACKETED = re.compile(r"\[[A-Z]+_\d+[^\]]*\]")
PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")
DASHES = "—–"
# Words that report a gap. Only a form answer says Not discussed, and nothing else says what was left out.
GAP = re.compile(r"(?i)\bnot (?:stated|said|discussed|mentioned|given|specified|provided)\b|\b(?:never|did not|didn't|no) (?:said|say|state|stated|mention|mentioned)\b|\bno [a-z ]{3,30} (?:stated|given|mentioned)\b")
FORM_NOTE_LIMIT = 250
TEXT_LIMITS = {outputs.TEXT_SLUGS[2]: FORM_NOTE_LIMIT}      # the Clio form note


def plain_problems(label: str, text: str) -> list[str]:
    """Rules for every output: plain text, no dashes of the long kind, no phone numbers, only well formed placeholders."""
    found = []
    if any(c in text for c in DASHES):
        found.append(f"{label}: has an em dash or en dash")
    if re.search(r"\*\*|__|^#{1,6} |`|^\s*\|.*\|\s*$", text, re.M):
        found.append(f"{label}: is not plain text (bold, heading, code or table marks)")
    if "*" in text:
        found.append(f"{label}: has an asterisk")
    if GAP.search(text):
        found.append(f"{label}: reports a gap ({GAP.search(text).group().strip()!r}), leave it out")
    if PHONE.search(text):
        found.append(f"{label}: has a phone number")
    for tag in set(BRACKETED.findall(text)) - set(PLACEHOLDER.findall(text)):
        found.append(f"{label}: placeholder {tag} is not in the right format")
    return found


def text_output_problems(slug: str, body: str) -> list[str]:
    name = outputs.NAMES[slug]
    found = plain_problems(name, body)
    lines = [l for l in body.split("\n") if l.strip()]
    if not lines:
        return found + [f"{name}: is empty"]
    if slug == outputs.TEXT_SLUGS[0]:      # clio-note: CAPS headers with bullets underneath
        if not any(l.strip().isupper() and any(c.isalpha() for c in l) for l in lines):
            found.append(f"{name}: has no CAPS section header")
    else:                                   # the overview and the form note are one paragraph
        if len(lines) > 1:
            found.append(f"{name}: is not one paragraph (it has {len(lines)} lines)")
        if re.match(r"^\s*[-*•]", lines[0]):
            found.append(f"{name}: starts with a bullet")
        if " - " not in lines[0][:80]:
            found.append(f"{name}: does not start with the client, a dash and the matter type")
    limit = TEXT_LIMITS.get(slug)
    if limit and len(" ".join(lines)) > limit:
        found.append(f"{name}: is {len(' '.join(lines))} characters, over {limit}")
    return found


def form_problems(slug: str, body: str, first_version: bool = True) -> list[str]:
    name = outputs.NAMES[slug]
    got = forms.parse(slug, body)
    found = []
    if not got.found:
        return [f"{name}: no [ANSWER: n] lines"]
    if got.dupes:
        found.append(f"{name}: question {sorted(set(got.dupes))} is answered twice")
    if got.unknown:
        found.append(f"{name}: has no question {sorted(set(got.unknown))}")
    if first_version:
        missing = [n for n in range(1, forms.count(slug) + 1) if n not in got.answers]
        if missing:
            found.append(f"{name}: no answer for {missing}, a first version answers every question")
    if got.loose and HEADER_RE.sub("", got.loose).strip():
        found.append(f"{name}: has text before the first [ANSWER: n] line")
    _, changes = forms.strict(slug, got.answers)
    for n, _, why in changes:
        found.append(f"{name}: answer {n} {why}")
    visible = forms.visibility(slug, got.answers)
    for n, text in sorted(got.answers.items()):
        q = forms.DETAILS[slug][n - 1]
        label = f"{name} answer {n}"
        if re.match(r"(?i)\s*(n/?a|none given|unknown|-+)\s*$", text):
            found.append(f"{label}: is {text.strip()!r}, write Not discussed")
        if forms.not_discussed(text):
            if text.strip() != "Not discussed":
                found.append(f"{label}: is {text.strip()!r}, write exactly Not discussed")
            continue
        if not text.strip():
            found.append(f"{label}: is empty, write Not discussed")
            continue
        found += plain_problems(label, text)
        if re.match(r"(?i)\s*(answer|a)\s*[:.]", text):
            found.append(f"{label}: starts with a label")
        if q.kind != "textarea" and "\n" in text.strip():
            found.append(f"{label}: has a line break in a single-line box")
        if q.kind in ("yesno", "radio", "checkbox", "date"):
            why = forms.choice_problem(slug, n, text)
            if why:
                found.append(f"{label}: {why}")
        if q.kind in ("radio", "yesno"):
            got_options = forms.choice(slug, n, text)
            if got_options and len(got_options[0]) > 1:
                found.append(f"{label}: names more than one option")
        if q.limit and len(text.strip()) > FORM_NOTE_LIMIT:
            found.append(f"{label}: is {len(text.strip())} characters, over {FORM_NOTE_LIMIT}")
        if visible[n][0] == "closed":
            found.append(f"{label}: answers a follow-up that Clio does not show ({visible[n][2]})")
    return found


def check_reply(text: str, expected: list[str] | None = None, message: str | None = None, first_version: bool = True) -> list[str]:
    """Every problem in a reply, as short sentences. An empty list means the format is right."""
    _, sections = wf.split_markers(text)
    found = []
    slugs = [s for s, _ in sections]
    for s in slugs:
        if s not in outputs.SLUGS:
            found.append(f"unknown output id {s!r}")
    for s in set(slugs):
        if slugs.count(s) > 1:
            found.append(f"{s} is written {slugs.count(s)} times")
    if expected is not None:
        for s in expected:
            if s not in slugs:
                found.append(f"{s} is missing")
        for s in slugs:
            if s not in expected and s in outputs.SLUGS:
                found.append(f"{s} was not asked for")
    for slug, body in sections:
        if slug not in outputs.SLUGS:
            continue
        if not HEADER_RE.search(body.split("\n", 1)[0] if body else ""):
            found.append(f"{slug}: does not start with the [CLIENT: .. | TX: ..] header line")
        clean = wf.strip_header_lines(body)
        if re.search(r"(?im)^\W*note for jules", clean):
            found.append(f"{slug}: holds a Note for Jules, which belongs above the first [OUTPUT: ...] line")
        found += form_problems(slug, clean, first_version) if slug in outputs.FORM_SLUGS else text_output_problems(slug, clean)
        if message is not None:
            for tag in set(PLACEHOLDER.findall(clean)) - set(PLACEHOLDER.findall(message)):
                found.append(f"{slug}: placeholder {tag} is not in the message")
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("reply")
    ap.add_argument("--outputs", help="comma separated output ids the message asked for")
    ap.add_argument("--message", help="the Copy for Claude text this reply answers")
    ap.add_argument("--change", action="store_true", help="a change request, so a form needs not answer every question")
    a = ap.parse_args()
    expected = [s.strip() for s in a.outputs.split(",")] if a.outputs else None
    message = Path(a.message).read_text(encoding="utf-8") if a.message else None
    problems = check_reply(Path(a.reply).read_text(encoding="utf-8"), expected, message, first_version=not a.change)
    print("\n".join(problems) if problems else "The format is right.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
