"""Transcript format parser.

A turn is a line starting with the bullet, the speaker's name, a timestamp, then the
spoken text. The name may share the bullet's line or sit on the next line, and the timestamp
may share the name's line or sit on the next line.
Input that does not match is reported as issues, never guessed.
"""
import re
from dataclasses import dataclass, field

TS = r"\d{1,2}:\d{2}(?::\d{2})?"
_TURN_LINE = re.compile(rf"^(?P<lead>\s*)•\s*(?P<name>\S.*?)(?:\s+(?P<ts>{TS}))?\s*$")
_NAME_LINE = re.compile(rf"^(?P<lead>\s*)(?P<name>\S.*?)(?:\s+(?P<ts>{TS}))?\s*$")
_TS_LINE = re.compile(rf"^\s*(?P<ts>{TS})\s*$")
_NAME_TOKEN = re.compile(r"^[^\W\d_][\w.'’-]*$")


class TranscriptFormatError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("; ".join(f"line {i.line}: {i.message}" for i in issues))


@dataclass(frozen=True)
class ParseIssue:
    line: int
    message: str


@dataclass
class Turn:
    speaker: str
    speaker_span: tuple[int, int]
    timestamp: str | None
    body_span: tuple[int, int]
    line: int
    generic: bool = False       # a role or channel label such as "Caller" or "Speaker 1", not a person's name


@dataclass
class ParsedTranscript:
    turns: list[Turn] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)


def parse_transcript(text: str) -> ParsedTranscript:
    out = ParsedTranscript()
    lines = text.splitlines(keepends=True)
    offsets, pos = [], 0
    for raw in lines:
        offsets.append(pos)
        pos += len(raw)
    cur: Turn | None = None
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\r\n")
        start = offsets[i]
        if line.lstrip().startswith("•"):
            if cur:
                cur.body_span = (cur.body_span[0], start)
            if line.strip() == "•":                      # the bullet stands alone, the name is on the next line
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j >= len(lines):
                    out.issues.append(ParseIssue(i + 1, "unreadable speaker line"))
                    cur = None
                    i += 1
                    continue
                i, line, start = j, lines[j].rstrip("\r\n"), offsets[j]
                m = _NAME_LINE.match(line)
            else:
                m = _TURN_LINE.match(line)
            if not m:
                out.issues.append(ParseIssue(i + 1, "unreadable speaker line"))
                cur = None
                i += 1
                continue
            name = m["name"]
            tokens = name.split()
            if not (1 <= len(tokens) <= 4 and all(_NAME_TOKEN.match(t) for t in tokens)):
                out.issues.append(ParseIssue(i + 1, f"speaker name not recognized: {name!r}"))
            ts, body_start = m["ts"], start + len(lines[i])
            if ts is None:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                nxt = _TS_LINE.match(lines[j].rstrip("\r\n")) if j < len(lines) else None
                if nxt:
                    ts, body_start = nxt["ts"], offsets[j] + len(lines[j])
                    i = j
                else:
                    out.issues.append(ParseIssue(i + 1, "missing timestamp"))
            cur = Turn(name, (start + m.start("name"), start + m.end("name")), ts, (body_start, len(text)), i + 1)
            out.turns.append(cur)
        elif line.strip() and cur is None:
            out.issues.append(ParseIssue(i + 1, "text before the first speaker line"))
        i += 1
    if not out.turns and not out.issues:
        out.issues.append(ParseIssue(1, "no speaker lines found"))
    return out


# ---- lenient reading ------------------------------------------------------------------------
#
# Scrubbing never needs the strict layout. Speaker lines only add certainty: a name used as a label is known
# to be a person before any model looks at the text. So the app reads whatever speaker lines it can recognize
# and treats everything else as plain text. Nothing is refused for its layout.

_BULLETS = "•●◦▪‣"
_GENERIC = re.compile(r"^(?:speaker|spk|unknown|caller|agent|client|customer|interviewer|interviewee|host|guest|"
                      r"participant|attorney|lawyer|paralegal|staff|q|a)[\s_.-]*\d*$", re.I)
_NOT_A_NAME = {"note", "notes", "email", "phone", "address", "date", "time", "subject", "summary", "topic",
               "re", "fwd", "from", "to", "cc", "bcc", "case", "matter", "file", "ref", "id"}
_CAP_TOKEN = r"[^\W\d_][\w.'’-]{0,60}"      # a name word is short, and the bound keeps a long run of dashes or dots from backtracking
_LABEL = rf"(?P<name>{_CAP_TOKEN}(?:\s+{_CAP_TOKEN}){{0,3}}(?:[\s_]\d+)?)"
_TS_FIRST = re.compile(rf"^(?P<lead>\s*)[\[(]?(?P<ts>{TS})[\])]?\s*[-–—]?\s*{_LABEL}\s*:?(?P<rest>\s*\S.*)?$")
_NAME_TS = re.compile(rf"^(?P<lead>\s*){_LABEL}\s*[\[(,-]*\s*(?P<ts>{TS})\s*[\])]*\s*:?(?P<rest>\s*\S.*)?$")
_COLON = re.compile(rf"^(?P<lead>\s*){_LABEL}\s*:(?P<rest>\s*\S.*)$")


@dataclass
class Reading:
    turns: list
    ranges: list                # (start, end) spans of the original to scan for names, emails and addresses
    notes: list
    info: list = field(default_factory=list)     # how the text was read, when that is normal and needs no warning


def _name_ok(name: str, *, loose: bool) -> bool:
    if _GENERIC.match(name.strip()):
        return True
    tokens = name.split()
    if not 1 <= len(tokens) <= 4 or not all(_NAME_TOKEN.match(t) for t in tokens):
        return False
    if name.strip().lower() in _NOT_A_NAME:
        return False
    return loose or all(t[0].isupper() for t in tokens)


def _candidates(text: str, lines: list, offsets: list) -> list:
    """Every line that could be a speaker line: (line index, name span, timestamp or None, body start, kind)."""
    out = []
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        start = offsets[i]
        if line.lstrip()[0] in _BULLETS:
            tail = line.lstrip()[1:]
            if not tail.strip():                     # a lone bullet: the name is on the next line
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                m = _NAME_LINE.match(lines[j].rstrip("\r\n")) if j < len(lines) else None
                if m and _name_ok(m["name"], loose=True):
                    out.append((j, (offsets[j] + m.start("name"), offsets[j] + m.end("name")), m["ts"],
                                offsets[j] + len(lines[j]), "bullet", i))
                continue
            m = _TURN_LINE.match(line.replace(line.lstrip()[0], "•", 1))
            if m and _name_ok(m["name"], loose=True):
                out.append((i, (start + m.start("name"), start + m.end("name")), m["ts"], start + len(raw), "bullet", i))
            continue
        for rx, kind in ((_TS_FIRST, "ts"), (_NAME_TS, "ts"), (_COLON, "colon")):
            m = rx.match(line)
            if m and _name_ok(m["name"], loose=False):
                body = start + m.start("rest") if m["rest"] else start + len(raw)
                out.append((i, (start + m.start("name"), start + m.end("name")), m.groupdict().get("ts"), body, kind, i))
                break
    return out


def parse_lenient(text: str) -> Reading:
    lines = text.splitlines(keepends=True)
    offsets, pos = [], 0
    for raw in lines:
        offsets.append(pos)
        pos += len(raw)
    cands = _candidates(text, lines, offsets)
    labels: dict = {}
    for c in cands:
        if c[4] == "colon":
            labels[norm_label(text[slice(*c[1])])] = labels.get(norm_label(text[slice(*c[1])]), 0) + 1
    # "Name: text" is also how notes and headings are written, so it counts as a speaker format only when some
    # label repeats. Then every label in that format is taken as a speaker.
    colon_format = any(n >= 2 for n in labels.values())
    if not colon_format:
        # Each speaker may also speak once. That is read as a transcript when there are at least two different labels
        # and enough of the text is made of such lines: a third or more when every label is a full name (two or more
        # words) or a role such as Caller, more than half when a label is a single word. A lone "Plan: call back" or a
        # single heading in a page of prose is still plain text.
        colon = [c for c in cands if c[4] == "colon"]
        nonblank = sum(1 for line in lines if line.strip())
        full = all(_GENERIC.match(text[slice(*c[1])].strip()) or len(text[slice(*c[1])].split()) >= 2 for c in colon)
        colon_format = len(colon) >= 2 and len(labels) >= 2 and (len(colon) * 3 >= nonblank if full else len(colon) * 2 > nonblank)
    chosen = [c for c in cands if c[4] != "colon" or colon_format]
    chosen.sort(key=lambda c: c[0])
    turns = []
    for k, (i, span, ts, body_start, kind, first_line) in enumerate(chosen):
        name = text[slice(*span)]
        # a timestamp alone on the next line belongs to this speaker
        if ts is None and kind in ("bullet", "ts") and i + 1 < len(lines):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            nxt = _TS_LINE.match(lines[j].rstrip("\r\n")) if j < len(lines) else None
            if nxt and not any(c[0] == j for c in chosen):
                ts, body_start = nxt["ts"], offsets[j] + len(lines[j])
        end = offsets[chosen[k + 1][5]] if k + 1 < len(chosen) else len(text)
        turns.append(Turn(name, span, ts, (min(body_start, end), end), i + 1, bool(_GENERIC.match(name.strip()))))
    notes, info = [], []
    if not turns:
        ranges = [(0, len(text))]
        notes.append("No speaker lines were recognized, so the whole text was scanned as plain text. Names are found "
                     "by the model alone, so read the review list closely.")
    else:
        first = offsets[chosen[0][5]]
        ranges = ([(0, first)] if text[:first].strip() else []) + [t.body_span for t in turns]
        strict = parse_transcript(text)
        if strict.issues and all(c[4] == "colon" for c in chosen):
            info.append(f"Read {len(turns)} speaker line{'s' if len(turns) != 1 else ''} (Name: text).")
        elif strict.issues:
            notes.append(f"The layout is not the expected one, so it was read loosely: {len(turns)} speaker lines found.")
    return Reading(turns, ranges, notes, info)


def norm_label(name: str) -> str:
    return " ".join(name.lower().split())
