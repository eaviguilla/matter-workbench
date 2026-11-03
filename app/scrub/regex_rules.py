"""Cheap, certain rules. A new entity type is one more entry in RULES.

Every rule returns Spans over the original text. Cue rules find names that follow a
phrase such as "my father" or "Dr."; they register the name so the registry then
replaces it everywhere else in the transcript.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass

from .spans import Span

_UP = "A-ZÀ-ÖØ-Þ"
# Scripts written without spaces between words. A name there has no word boundary around it.
CJK = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯"
_CJK_RE = re.compile(f"[{CJK}]")


def has_cjk(value: str) -> bool:
    return _CJK_RE.search(value) is not None
_TOKEN = rf"[{_UP}][\w-]*(?:['’][\w-]+)?"
NAME = rf"(?P<name>{_TOKEN}(?:[ ]+{_TOKEN}){{0,2}})"

# Capitalized words that follow a cue but are not people.
NOT_NAMES = {w.casefold() for w in """
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July
August September October November December Insurance Mutual Company Corporation Hospital Clinic Center
Medicare Medicaid Social Security Department Bureau Court Police Sheriff County State Federal Life Auto
Health Home Homeowners Allstate Progressive MetLife Geico Farmers Walgreens Walmart Target Amazon
God Lord Mr Mrs Ms Miss Mister Missus Mx Dr Judge Christmas Thanksgiving Easter Sunday Canadian American Mexican Catholic Methodist
""".split()}


@dataclass(frozen=True)
class Rule:
    type: str
    pattern: re.Pattern
    source: str
    group: str | int = 0
    normalize: Callable[[str], str] | None = None   # optional callable: matched text -> value to register


# --- emails -----------------------------------------------------------------------------
_UNITS = "one two three four five six seven eight nine".split()
_TEENS = "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_NUMW = {"zero": 0, "oh": 0, **{w: i for i, w in enumerate(_UNITS, 1)}, **{w: 10 + i for i, w in enumerate(_TEENS)},
         **{w: 20 + 10 * i for i, w in enumerate(_TENS)}}
_SPOKEN = {"dot": ".", "period": ".", "underscore": "_", "dash": "-", "hyphen": "-"}
_NUM = "|".join(sorted(_NUMW, key=len, reverse=True))
_TLD = "com|net|org|edu|gov|io|co|us|uk|info|biz|me"
_W = rf"(?:[a-z0-9]+(?:\s+(?:{_NUM}))*)"
_SEP = r"\s+(?:dot|period|underscore|dash|hyphen)\s+"
_UNIT = rf"(?:(?:[a-z0-9]\s+){{2,}}[a-z0-9]|{_W})"
_LOCAL = rf"{_UNIT}(?:{_SEP}{_UNIT})*"
_DOMAIN = rf"[a-z0-9]+(?:\s+dot\s+[a-z0-9]+)*\s+dot\s+(?:{_TLD})"

EMAIL_WRITTEN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
EMAIL_SPOKEN = re.compile(rf"(?<![\w'’]){_LOCAL}\s+at\s+{_DOMAIN}\b", re.I)


def spoken_to_email(spoken: str) -> str:
    """'juan dot cruz seventy one at yahoo dot com' -> 'juan.cruz71@yahoo.com'; spelled letters are joined."""
    toks, out, i = spoken.lower().split(), [], 0
    while i < len(toks):
        t = toks[i]
        if t in _NUMW and t != "oh":
            if t in _TENS and i + 1 < len(toks) and toks[i + 1] in _UNITS:
                out.append(str(_NUMW[t] + _NUMW[toks[i + 1]]))
                i += 1
            else:
                out.append(str(_NUMW[t]))
        else:
            out.append("@" if t == "at" else _SPOKEN.get(t, t))
        i += 1
    return "".join(out)


# --- addresses --------------------------------------------------------------------------
_STREET = (r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Way|Place|Pl|"
           r"Terrace|Circle|Highway|Hwy|Parkway|Pkwy|Trail)")
_CITY_STATE_ZIP = rf"(?:,[ ]*[{_UP}][a-z]+(?:[ ]+[{_UP}][a-z]+)?,?[ ]+[A-Z]{{2}}\b(?:[ ]+\d{{5}}(?:-\d{{4}})?)?)?"
ADDRESS = re.compile(
    rf"\b\d{{1,6}}[ ]+(?:[NSEW]\.?[ ]+)?(?:[{_UP}][\w'’-]*[ ]+){{0,3}}{_STREET}\b"
    rf"(?:,?[ ]+(?i:apt|apartment|unit|suite|ste|#)\.?[ ]*\w+)?" + _CITY_STATE_ZIP
)
POBOX = re.compile(rf"\b(?i:P\.?[ ]?O\.?[ ]+Box)[ ]+\d{{1,8}}\b" + _CITY_STATE_ZIP)

# --- cue names --------------------------------------------------------------------------
_REL = ("father|dad|daddy|papa|mother|mom|mommy|mama|mum|wife|husband|spouse|partner|fiance|fiancee|fiancée|"
        "brother|sister|son|daughter|uncle|aunt|cousin|grandfather|grandmother|grandpa|grandma|grandson|"
        "granddaughter|nephew|niece|neighbor|neighbour|friend|boss|coworker|supervisor|doctor|lawyer|attorney|"
        "adjuster|examiner|agent|investigator|nurse|surgeon|pastor|landlord|roommate|girlfriend|boyfriend|"
        "stepfather|stepmother|stepdad|stepmom|father-in-law|mother-in-law|brother-in-law|sister-in-law|manager|"
        "caseworker|case worker|caretaker|aide|administrator|executor|representative|rep|officer|clerk|teacher|"
        "pharmacist|principal|man|woman|lady|gentleman|guy|girl|boy|kid|one|report|youngest|oldest|trustee|"
        "notary|witness|driver|owner|secretary|receptionist|technician|inspector|salesman|salesperson|broker|"
        "advisor|adviser|dentist|therapist|counselor|worker|director|foreman|cashier|cleaner|janitor|"
        "contractor|plumber|electrician|accountant|banker")
_DET = r"my|his|her|our|their|the|your|a|an|one|another|some|[A-Za-z]+['’]s"
_TITLES = ("Mr|Mrs|Ms|Miss|Mister|Missus|Mx|Dr|Doctor|Judge|Officer|Detective|Deputy|Marshal|Sergeant|Sgt|"
           "Attorney|Pastor|Reverend|Father|Aunt|Auntie|Uncle")
# Leading words dropped from a captured name ("Deputy Marshal Ignatius Pell" -> "Ignatius Pell").
TITLE_WORDS = {t.casefold() for t in _TITLES.split("|")} | {"grandma", "grandpa"}
_REL_HEAD = rf"(?i:{_DET})[ ]+(?i:late[ ]+)?(?:[A-Za-z'’]+[ ]+){{0,2}}(?i:{_REL})"
_ALIAS = r"(?i:call me|calls me|they call me|everybody calls me|everyone calls me|known as|go by|goes by)"
CUES = [
    rf"(?:{_TITLES})\.?[ ]+{NAME}",
    rf"(?i:name is|name's|name was|this is|i am|i'm|named|called|nicknamed|"
    rf"report (?:says|lists|names))[ ]+{NAME}",
    rf"{_REL_HEAD},?[ ]+(?:(?i:was|is)[ ]+)?(?:(?i:named|called)[ ]+)?{NAME}",
    rf"{_REL_HEAD}(?:,?[ ]+[a-z'’]+){{1,5}},[ ]+{NAME}",
    rf"(?:Mom|Dad|Papa|Mama|Mother|Father|Grandma|Grandpa)[ ]+(?i:is|was)[ ]+{NAME}",
    rf"(?i:spoke (?:with|to)|talked (?:with|to)|speak (?:with|to)|talk (?:with|to)|met with|represented by|"
    rf"handled by|signed by|witnessed by|assigned to|texted|emailed|phoned)[ ]+{NAME}",
]
TITLE_RULE = Rule("PERSON", re.compile(CUES[0]), "title", "name")   # "Mrs. Okafor": a surname, not a first name
CUE_RULES = [Rule("PERSON", re.compile(c), "cue", "name") for c in CUES[1:]]
ALIAS_PREV_RULE = Rule("PERSON", re.compile(rf"(?i:called (?:him|her|them))[ ]+{NAME}"), "alias_prev", "name")
ALIAS_RULE = Rule("PERSON", re.compile(rf"{_ALIAS}[ ]+{NAME}"), "alias", "name")
SPELLED_NAME = Rule("PERSON", re.compile(r"(?<![\w-])(?:[A-Z]-){2,}[A-Z](?![\w-])"), "spelled",
                    normalize=lambda t: t.replace("-", ""))

RULES = [Rule("PERSON", re.compile(c), "cue", "name") for c in CUES]

RULES = [
    Rule("EMAIL", EMAIL_WRITTEN, "regex"),
    Rule("EMAIL", EMAIL_SPOKEN, "regex", normalize=spoken_to_email),
    Rule("ADDRESS", ADDRESS, "regex"),
    Rule("ADDRESS", POBOX, "regex"),
    TITLE_RULE,
    *CUE_RULES,
    ALIAS_RULE,
    ALIAS_PREV_RULE,
    SPELLED_NAME,
]


def _trim_name(text: str, start: int, end: int):
    """Drop trailing non-name words, a possessive 's, and bail if the name starts with one."""
    tokens = list(re.finditer(r"\S+", text[start:end]))
    while tokens and tokens[0].group().casefold().rstrip(".") in TITLE_WORDS:
        tokens = tokens[1:]
    keep = []
    for t in tokens:
        if t.group().casefold().rstrip("'’s") in NOT_NAMES or t.group().casefold() in NOT_NAMES:
            break
        keep.append(t)
    if not keep:
        return None
    s, e = start + keep[0].start(), start + keep[-1].end()
    m = re.search(r"['’][sS]$", text[s:e])
    if m:
        e -= len(m.group())
    return (s, e) if e > s else None


def detect(text: str) -> list[Span]:
    spans = []
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            s, e = m.span(rule.group)
            if rule.source in ("cue", "title", "alias", "alias_prev"):
                trimmed = _trim_name(text, s, e)
                if not trimmed:
                    continue
                s, e = trimmed
            value = rule.normalize(text[s:e]) if rule.normalize else text[s:e]
            spans.append(Span(s, e, rule.type, rule.source, value))
    return sorted(spans, key=lambda sp: (sp.start, -sp.length))
