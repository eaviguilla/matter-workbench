"""The outputs Claude produces for each transcript. This is the one place they are defined.

The slug names the output's file and is what Claude writes in an [OUTPUT: slug] line or passes to save_output.
Jordan is office staff, so the name in an output title is not scrubbed in the instructions.
"""
import re

OUTPUTS = (
    ("clio-note", "Clio Note"),
    ("jordan-calendar-overview", "Overview for Jordan's calendar notes"),
    ("clio-form-note", "Clio form note"),
)
SLUGS = tuple(slug for slug, _ in OUTPUTS)
NAMES = dict(OUTPUTS)
SHORT_NAMES = {"clio-note": "Note", "jordan-calendar-overview": "Overview", "clio-form-note": "Form note"}   # for tight lists

# Starter instructions. Settings can replace each one, and an empty saved value falls back to these.
DEFAULT_INSTRUCTIONS = {
    "clio-note": "Write a short note for the client's file in Clio. Use plain sentences. Say who called, why, what "
                 "was decided and what happens next. Keep dates as they were said.",
    "jordan-calendar-overview": "Write a short overview Jordan can use for calendar notes. List each date, deadline "
                                "and appointment mentioned, with one line on what it is for. Say so if a date is unclear.",
    "clio-form-note": "Write a note that fits a Clio form. Use short labelled lines such as Matter, Contact, Issue and "
                      "Next step. Leave a line out if the call did not cover it.",
}
MAX_INSTRUCTION = 4000
MARKER_RE = re.compile(r"^[ \t]*\[OUTPUT:[ \t]*(?P<slug>[^\]\n]*?)[ \t]*\][ \t]*$", re.M | re.I)


def is_slug(value) -> bool:
    return isinstance(value, str) and value in NAMES
