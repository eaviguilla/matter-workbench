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

@dataclass(frozen=True)
class Question:
    """One entry of a form, as it is on the Clio page. A follow-up that Clio shows only after a Yes or No is its own
    entry, with `when` naming the earlier answer that opens it."""
    text: str
    kind: str = "text"                      # text, textarea, date, yesno, radio (pick one option) or checkbox
    when: tuple | None = None               # (question number, answer) that makes Clio show this one
    options: tuple = ()                     # checkbox: the exact option texts
    clio: str = ""                          # the title on the Clio page, when it is not the same as text
    limit: int | None = None                # characters the Clio box takes


CLIO_TEXT = 255
PLAN_DONE = (
    "Yes! A full estate plan (a trust, will, health care directive, power of attorney, etc.)",
    "A little! We have some documents done.",
    "None!",
)
ESTATE_PLAN_FORM = (
    Question("Are you legally married?", "yesno"),
    Question("Please provide your spouse's name.", when=(1, "Yes"), limit=CLIO_TEXT),
    Question("Please advise if you are single, widowed, or divorced.", when=(1, "No"), limit=CLIO_TEXT),
    Question("Are you a U.S. Citizen?", "yesno"),
    Question("(If applicable) Is your spouse a U.S. Citizen?", "yesno"),
    Question("Are you a California resident?", "yesno"),
    Question("Are you planning to move out of California soon?", "yesno"),
    Question("Do you have children?", "yesno"),
    Question("Do they have special needs?", "yesno", when=(8, "Yes")),
    Question("Are they minors?", "yesno", when=(8, "Yes")),
    Question("Do you currently own your home?", "yesno"),
    Question("Do you have any estate planning done?", "checkbox", options=PLAN_DONE),
    Question("Any deadlines we need to know about? For example, are you going on vacation soon and want your plan "
             "done before then?", "yesno"),
    Question("Please explain. (deadlines)", when=(13, "Yes"), clio="Please explain.", limit=CLIO_TEXT),
    Question("Our main office is located in Santa Ana, off the 55/5 freeway. Does this work for you?", "yesno"),
    Question("Please share your concern with the location.", when=(15, "No"), limit=CLIO_TEXT),
    Question("How did you hear about us?", limit=CLIO_TEXT),
    Question("Anything else you want us to know?", "yesno"),
    Question("Please explain. (anything else)", when=(18, "Yes"), clio="Please explain.", limit=CLIO_TEXT),
)
ESTATE_PLAN = tuple(q.text for q in ESTATE_PLAN_FORM)

PROBATE_DONE = (
    "Yes! A full estate plan (a trust, will, health care directive, power of attorney, etc.)",
    "A little. Looks like some documents were done.",
    "None.",
    "Not sure.",
)
FAMILY = ("Spouse", "Children", "Parent", "Sibling")
DATE_FORMAT = "MM/DD/YYYY"
PROBATE_FORM = (
    Question("What was the name of your loved one?", limit=CLIO_TEXT),
    Question("Did your loved one have any estate planning done?", "checkbox", options=PROBATE_DONE),
    Question("In what state was your loved one a resident at the time of their death?", limit=CLIO_TEXT),
    Question("In what county was your loved one a resident at the time of their death?", limit=CLIO_TEXT),
    Question("When did your loved one pass away?", "date"),
    Question("What assets did your loved one leave behind (e.g., a home, rental property, bank accounts, brokerage "
             "accounts)?", "textarea"),
    Question("Did your loved one own real estate when they died?", "yesno"),
    Question("Please share the full address.", when=(7, "Yes"), limit=CLIO_TEXT),
    Question("Are you planning to sell the property?", "yesno", when=(7, "Yes")),
    Question("What family members did your loved one leave behind?", "checkbox", options=FAMILY),
    Question("Are there any disagreements or unresolved matters among family members regarding your loved one's "
             "belongings or affairs?", "yesno",
             clio="Are there any disagreements or unresolved matters among family members regarding your loved one’s "
                  "belongings or affairs?"),
    Question("Please explain. (disagreements)", when=(11, "Yes"), clio="Please explain.", limit=CLIO_TEXT),
    Question("Was the probate process started?", "yesno"),
    Question("Please provide case number and county where it was filed.", when=(13, "Yes"), limit=CLIO_TEXT),
    Question("How did you hear about us?", limit=CLIO_TEXT),
    Question("Is there anything else you would like us to know?", "textarea"),
)
PROBATE = tuple(q.text for q in PROBATE_FORM)

GENERAL_FORM = (
    Question("Matter Type:", "checkbox", options=("Estate Planning", "Probate", "Trust Administration", "Other")),
    Question("Brief Description of the Situation:", limit=CLIO_TEXT),
    Question("Preferred Method of Communication:", "radio", options=("Phone Call", "Email", "Text Message")),
    Question("How did you hear about us?", "checkbox", options=("Referral", "Online", "Other")),
    Question("Next Steps: The lead attorney, Jordan, will review this information, and we will follow up within one "
             "business day. Thank you again for calling!", limit=CLIO_TEXT),
)
GENERAL = tuple(q.text for q in GENERAL_FORM)

DELIVERY = ("Mail", "Drop Off", "Email", "Not available")
TRUST_ADMIN_FORM = (
    Question("What was the name of your loved one?", limit=CLIO_TEXT),
    Question("Do you have a copy of the estate plan you can email, mail, or drop off to us (trust, will, etc.)?",
             "radio", options=DELIVERY),
    Question("When will it be available? (estate plan)", when=(2, "Not available"), clio="When will it be available?",
             limit=CLIO_TEXT),
    Question("Do you have a copy of the death certificate you can email, mail, or drop off to us (trust, will, etc.)?",
             "radio", options=DELIVERY),
    Question("When will it be available? (death certificate)", when=(4, "Not available"),
             clio="When will it be available?", limit=CLIO_TEXT),
    Question("Are there any disagreements or unresolved matters among family members regarding your loved one's "
             "belongings or affairs?", "yesno",
             clio="Are there any disagreements or unresolved matters among family members regarding your loved one’s "
                  "belongings or affairs?"),
    Question("Please explain. (disagreements)", when=(6, "Yes"), clio="Please explain.", limit=CLIO_TEXT),
    Question("How did you hear about us?", limit=CLIO_TEXT),
    Question("Is there anything else you would like us to know?", "textarea"),
)
TRUST_ADMIN = tuple(q.text for q in TRUST_ADMIN_FORM)

QUESTIONS = {"probate-intake-form": PROBATE, "estate-plan-intake-form": ESTATE_PLAN, "general-intake-form": GENERAL,
             "trust-admin-intake-form": TRUST_ADMIN}
DETAILS = {"probate-intake-form": PROBATE_FORM, "estate-plan-intake-form": ESTATE_PLAN_FORM,
           "general-intake-form": GENERAL_FORM, "trust-admin-intake-form": TRUST_ADMIN_FORM}

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


def hint(slug: str, n: int) -> str:
    """The short line under a question: when Clio shows it, what kind of answer it takes, how long it may be."""
    q = DETAILS[slug][n - 1]
    parts = []
    if q.when:
        parts.append(f"Only if answer {q.when[0]} is {q.when[1]}.")
    if q.kind == "yesno":
        parts.append("Yes or No.")
    elif q.kind == "checkbox":
        parts.append("Any of: " + " | ".join(q.options))
    elif q.kind == "radio":
        parts.append("One of: " + " | ".join(q.options))
    elif q.kind == "date":
        parts.append(f"A date as {DATE_FORMAT}.")
    elif q.limit:
        parts.append(f"{q.limit} characters at most.")
    return " ".join(parts)


def over(slug: str, n: int, text: str) -> int:
    """How many characters the answer is over what the Clio box takes (0 when it fits or has no limit)."""
    limit = DETAILS[slug][n - 1].limit
    return max(0, len(text) - limit) if limit else 0


def settled(text: str) -> bool:
    """True when an answer says something a follow-up can depend on: it is not empty and not Not discussed."""
    return bool(text.strip()) and text.strip(" .").lower() != NOT_DISCUSSED


def _norm(x: str) -> str:
    return re.sub(r"\s+", " ", x).strip(" \t.!,;").casefold()


def choice(slug: str, n: int, text: str):
    """The options an answer names, as (options, exact), or None when it names none. Yes or No takes a leading Yes or
    No word ("Yes, two homes" names Yes but is not exact). A pick-one question takes exactly one option, and a checkbox
    question takes options separated by " | "."""
    q = DETAILS[slug][n - 1]
    options = ("Yes", "No") if q.kind == "yesno" else q.options
    if not options or not settled(text):
        return None
    wanted = {_norm(o): o for o in options}
    parts = [_norm(x) for x in text.split("|")] if q.kind == "checkbox" else [_norm(text)]
    if parts and all(x in wanted for x in parts):
        return tuple(wanted[x] for x in parts), True
    if q.kind == "yesno":
        first = re.match(r"[a-z]+", _norm(text))
        if first and first[0] in wanted:
            return (wanted[first[0]],), False
    return None


def choice_problem(slug: str, n: int, text: str) -> str:
    """A short warning when a Yes or No, pick-one or checkbox answer is not what Clio can pick, else an empty text."""
    q = DETAILS[slug][n - 1]
    if q.kind not in ("yesno", "radio", "checkbox") or not settled(text):
        return ""
    got = choice(slug, n, text)
    if got is None:
        return "Not one of the options, so Clio cannot pick it."
    return "" if got[1] else "Has extra words. Clio takes only Yes or No, so the rest is dropped on the next save."


def visibility(slug: str, answers: dict) -> dict:
    """For every entry, {number: (state, parent, reason)}. The state is always (no condition), open (the parent answer
    opens it), closed (the parent answer is a different one, or the parent is itself closed) or unset (the parent has no
    usable answer yet, so nothing can be said and the entry is never hidden)."""
    out = {}
    for n, q in enumerate(DETAILS[slug], 1):
        if not q.when:
            out[n] = ("always", None, "")
            continue
        parent, wanted = q.when
        if out[parent][0] == "closed":
            out[n] = ("closed", parent, f"answer {parent} is closed")
            continue
        text = answers.get(parent, "")
        if not settled(text):
            out[n] = ("unset", parent, f"answer {parent} is not answered yet")
            continue
        got = choice(slug, parent, text)
        if got is None:
            out[n] = ("unset", parent, f"answer {parent} is not one of the options")
        elif wanted in got[0]:
            out[n] = ("open", parent, "")
        else:
            out[n] = ("closed", parent, f"answer {parent} is {' | '.join(got[0])}")
    return out


def strict(slug: str, answers: dict) -> tuple[dict, list]:
    """The answers as Clio can take them, and what was changed to get there, as [(number, kind, text)]. A Yes or No
    entry holds exactly Yes or No (a leading Yes or No word is kept and the rest dropped, anything else is cleared).
    An entry that Clio does not show, because the answer that opens it is not the named one or is not given yet, holds
    nothing. Not discussed and empty stay as they are on an entry that is shown."""
    clean = {n: t for n, t in answers.items() if 1 <= n <= count(slug)}
    notes = []
    for n, q in enumerate(DETAILS[slug], 1):
        text = clean.get(n, "")
        if q.kind != "yesno" or not settled(text):
            continue
        got = choice(slug, n, text)
        if got is None:
            clean.pop(n)
            notes.append((n, "option", "is not Yes or No, so it is left empty"))
        else:
            if not got[1]:
                notes.append((n, "words", f"has extra words, so only {got[0][0]} is saved"))
            clean[n] = got[0][0]
    while True:
        gone = [n for n, v in visibility(slug, clean).items() if v[0] in ("closed", "unset") and clean.get(n)]
        if not gone:
            return clean, notes
        for n in gone:
            if settled(clean[n]):
                parent, wanted = DETAILS[slug][n - 1].when
                notes.append((n, "closed", f"is not saved, because answer {parent} is not {wanted}"))
            del clean[n]


def schema(slug: str) -> list:
    """The form as plain data, for the Clio extension and for tests."""
    return [dict(n=n, text=q.text, clio=q.clio or q.text, kind=q.kind, options=list(q.options),
                 when=list(q.when) if q.when else None, limit=q.limit) for n, q in enumerate(DETAILS[slug], 1)]


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
    """The new answers laid over the latest version, made strict (see strict). A question the reply did not answer keeps
    what it had, and an answer is cleared by writing something in it, such as Not discussed."""
    answers = dict(parse(slug, old).answers) if old else {}
    answers.update(new_answers)
    return render(slug, strict(slug, answers)[0])


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
