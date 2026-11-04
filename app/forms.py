"""The intake form outputs: a numbered list of questions with one answer each.

A form is stored like any other output, as one text per version, so versions, Compare, Import, Scrub this, Unscrub and
the connector all work on it unchanged. Inside the text each answer sits under a marker line, [ANSWER: 5], where the
number is the question's place in the list. The stored text is always in the canonical shape: every question's marker,
in order, with an empty answer when nothing was given.

The app does not tell Claude how to answer. It only reads what Claude sends back. The one thing it needs is the marker
line, and the person puts that in the Claude Project (Settings has the text to paste).
"""
import re
from dataclasses import dataclass, field

from .outputs import MARKER_RE

PROBATE = (
    "What was the name of your loved one?",
    "Did your loved one have any estate planning done?",
    "In what state was your loved one a resident at the time of their death?",
    "In what county was your loved one a resident at the time of their death?",
    "When did your loved one pass away?",
    "What assets did your loved one leave behind (e.g., a home, rental property, bank accounts, brokerage accounts)?",
    "Did your loved one own real estate when they died?",
    "What family members did your loved one leave behind?",
    "Are there any disagreements or unresolved matters among family members regarding your loved one's belongings or affairs?",
    "Was the probate process started?",
    "How did you hear about us?",
    "Is there anything else you would like us to know?",
)
ESTATE_PLAN = (
    "Are you legally married?",
    "Please provide your spouse's name.",
    "Are you a U.S. Citizen?",
    "(If applicable) Is your spouse a U.S. Citizen?",
    "Are you a California resident?",
    "Are you planning to move out of California soon?",
    "Do you have children?",
    "Do they have special needs?",
    "Are they minors?",
    "Do you currently own your home?",
    "Do you have any estate planning done?",
    "Any deadlines we need to know about? For example, are you going on vacation soon and want your plan done before then?",
    "Our main office is located in Santa Ana, off the 55/5 freeway. Does this work for you?",
    "How did you hear about us?",
    "Anything else you want us to know?",
)
QUESTIONS = {"probate-intake-form": PROBATE, "estate-plan-intake-form": ESTATE_PLAN}

ANSWER_RE = re.compile(r"^[ \t]*[*#>]*[ \t]*\[ANSWER:[ \t]*(?P<n>\d{1,3})[ \t]*\][ \t]*\**[ \t]*(?P<rest>.*)$", re.M | re.I)
NOT_DISCUSSED = "not discussed"


@dataclass
class Parsed:
    loose: str = ""                                       # text before the first marker, which is not saved
    answers: dict = field(default_factory=dict)           # question number -> answer, only those that have text
    blanks: list = field(default_factory=list)            # numbers whose marker has no answer under it
    dupes: list = field(default_factory=list)             # numbers answered twice
    unknown: list = field(default_factory=list)           # numbers that are not a question on this form
    found: bool = False                                   # at least one marker


def count(slug: str) -> int:
    return len(QUESTIONS[slug])


def parse(slug: str, text: str) -> Parsed:
    """Read the answers out of a reply or a stored version. A stray [OUTPUT: ...] line is ignored."""
    text = MARKER_RE.sub("", text)
    marks = list(ANSWER_RE.finditer(text))
    out = Parsed(found=bool(marks), loose=(text[:marks[0].start()] if marks else text).strip())
    seen = set()
    for k, m in enumerate(marks):
        n = int(m["n"])
        body = (m["rest"] + "\n" + text[m.end():marks[k + 1].start() if k + 1 < len(marks) else len(text)]).strip()
        if n < 1 or n > count(slug):
            out.unknown.append(n)
        elif n in seen:
            out.dupes.append(n)
        else:
            seen.add(n)
            if body:
                out.answers[n] = body
            else:
                out.blanks.append(n)
    return out


def render(slug: str, answers: dict) -> str:
    """The canonical stored text: every marker in order, an empty answer where there is none."""
    return "\n\n".join(f"[ANSWER: {n}]\n{answers.get(n, '').strip()}".rstrip("\n") for n in range(1, count(slug) + 1))


def merge(slug: str, old: str, new_answers: dict) -> str:
    """The new answers laid over the latest version. A question the reply did not answer keeps what it had, and an
    answer is cleared by writing something in it, such as Not discussed."""
    answers = dict(parse(slug, old).answers) if old else {}
    answers.update(new_answers)
    return render(slug, answers)


def missing(slug: str, answers: dict) -> list:
    """Question numbers with no answer."""
    return [n for n in range(1, count(slug) + 1) if n not in answers]


def rows(slug: str, content: str) -> list:
    """[(number, question, answer)] for display, from a stored version."""
    answers = parse(slug, content).answers
    return [(n, q, answers.get(n, "")) for n, q in enumerate(QUESTIONS[slug], 1)]


def numbers(values: list) -> str:
    """[2, 3, 4, 9] as "2 to 4 and 9" is not needed here, a plain list reads fine: "2, 3, 4 and 9"."""
    values = [str(v) for v in values]
    return values[0] if len(values) == 1 else ", ".join(values[:-1]) + " and " + values[-1]
