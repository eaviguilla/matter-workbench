"""The outputs Claude produces for each transcript. This is the one place they are defined.

The slug names the output's file and is what Claude writes in an [OUTPUT: slug] line or passes to save_output.
The app tells Claude only which outputs to write. How each one is written is set in the person's own Claude Project,
so no output instructions are kept here.

Text outputs are one block of text with one Copy button. Form outputs are a numbered list of questions with one answer
each (see app/forms.py), shown as one copy box per answer.
"""
import re

TEXT_OUTPUTS = (
    ("clio-note", "Clio Note"),
    ("jordan-calendar-overview", "Overview for Jordan's calendar notes"),
    ("clio-form-note", "Clio form note"),
)
FORM_OUTPUTS = (
    ("probate-intake-form", "Probate Intake Form"),
    ("estate-plan-intake-form", "Estate Plan - General Intake form"),
    ("general-intake-form", "General Intake Form"),
    ("trust-admin-intake-form", "Trust Admin Intake Form"),
)
OUTPUTS = TEXT_OUTPUTS + FORM_OUTPUTS
TEXT_SLUGS = tuple(slug for slug, _ in TEXT_OUTPUTS)
FORM_SLUGS = tuple(slug for slug, _ in FORM_OUTPUTS)
SLUGS = tuple(slug for slug, _ in OUTPUTS)
NAMES = dict(OUTPUTS)
SHORT_NAMES = {"clio-note": "Note", "jordan-calendar-overview": "Overview", "clio-form-note": "Form note",
               "probate-intake-form": "Probate", "estate-plan-intake-form": "Estate plan",
               "general-intake-form": "General", "trust-admin-intake-form": "Trust admin"}   # for tight lists
MARKER_RE = re.compile(r"^[ \t]*\[OUTPUT:[ \t]*(?P<slug>[^\]\n]*?)[ \t]*\][ \t]*$", re.M | re.I)


def is_slug(value) -> bool:
    return isinstance(value, str) and value in NAMES


def is_form(slug) -> bool:
    return slug in FORM_SLUGS
