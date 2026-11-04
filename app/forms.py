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
    Question("Do they have special needs?", when=(8, "Yes"), limit=CLIO_TEXT),
    Question("Are they minors?", when=(8, "Yes"), limit=CLIO_TEXT),
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
    Question("Are you planning to sell the property?", when=(7, "Yes"), limit=CLIO_TEXT),
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
