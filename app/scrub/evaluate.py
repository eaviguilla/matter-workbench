"""Load annotated synthetic conversations and score the scrubber against them.

Source files (*.ann.txt) are written as bullet-and-text turns without timestamps, with the
sensitive values tagged inline as {P1:Maria Lopez}, {E1:maria@x.com}, {A1:12 Oak Street}.
The digit is an entity key, so two spans with the same key must get the same placeholder.
Timestamps are generated, so the scrubber is tested on the real transcript format.
"""
import re
from dataclasses import dataclass, field

from .pipeline import ScrubConfig, scrub_transcript
from .registry import Registry

TITLE_BEFORE = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Mister|Dr|Doctor|Officer|Judge|Deputy|Marshal)\.?[ ]$")
TAG = re.compile(r"\{([PEA])(\d+):([^}]*)\}")
TYPES = {"P": "PERSON", "E": "EMAIL", "A": "ADDRESS"}


@dataclass
class Annotated:
    name: str
    text: str
    spans: list = field(default_factory=list)   # (start, end, type, key)


def load_annotated(name: str, source: str) -> Annotated:
    out, spans, clock, words = [], [], 0.0, 0
    pos = 0

    def emit(line: str):
        nonlocal pos
        last = 0
        for m in TAG.finditer(line):
            out.append(line[last:m.start()])
            pos += m.start() - last
            spans.append((pos, pos + len(m[3]), TYPES[m[1]], f"{m[1]}{m[2]}"))
            out.append(m[3])
            pos += len(m[3])
            last = m.end()
        out.append(line[last:])
        pos += len(line) - last

    for raw in source.splitlines():
        if raw.startswith("#"):
            continue
        if raw.startswith("•"):
            clock += words / 2.6 + 1.5
            words = 0
            emit(raw)
            ts = f"{int(clock) // 60}:{int(clock) % 60:02d}"
            out.append(f" {ts}\n")
            pos += len(ts) + 2
        else:
            emit(raw)
            out.append("\n")
            pos += 1
            words += len(raw.split())
    return Annotated(name, "".join(out), spans)


@dataclass
class Report:
    name: str
    total: dict = field(default_factory=dict)
    auto_missed: list = field(default_factory=list)    # (type, text, caught_by_flag)
    inconsistent: list = field(default_factory=list)
    over_scrubbed: list = field(default_factory=list)
    flags: int = 0
    exempt: int = 0          # first names intentionally kept (keep_first_names only)
    scrubbed_text: str = ""

    @property
    def leaks_after_gate(self):
        return [m for m in self.auto_missed if not m[2]]


def _exempt_first(ann: Annotated, spans, i, config) -> bool:
    """With keep_first_names, a bare first name is intentionally left in plain text."""
    s, e, t, key = spans[i]
    if t != "PERSON" or not config.keep_first_names:
        return False
    text = ann.text[s:e]
    if TITLE_BEFORE.search(ann.text[:s]):
        return False         # a surname after a title is never a first name
    forms = [ann.text[a:b] for a, b, tt, k in spans if k == key]
    multi = [f for f in forms if len(f.split()) >= 2]
    if len(text.split()) != 1:
        return False
    if not multi:
        return True
    surname = max(multi, key=len).split()[-1]
    return text.replace("-", "").casefold() != surname.replace("-", "").casefold()


def evaluate(ann: Annotated, config: ScrubConfig = ScrubConfig(), ner=None) -> Report:
    reg = Registry()
    res = scrub_transcript(ann.text, reg, config, ner)
    rep = Report(ann.name, scrubbed_text=res.text, flags=len(res.flags))
    key_to_ph, ph_to_key = {}, {}
    for i, (s, e, t, key) in enumerate(ann.spans):
        rep.total[t] = rep.total.get(t, 0) + 1
        if _exempt_first(ann, ann.spans, i, config):
            rep.exempt += 1
            continue
        if t == "PERSON" and config.keep_first_names and len(ann.text[s:e].split()) == 2:
            s += len(ann.text[s:e].split()[0])     # the first name is meant to stay; check the rest
        hits = [a for a in res.applied if a.start < e and s < a.end]
        covered = sorted((max(a.start, s), min(a.end, e)) for a in hits)
        reach, ok = s, True
        for a, b in covered:
            if a > reach and ann.text[reach:a].strip():
                ok = False
            reach = max(reach, b)
        if ann.text[reach:e].strip() or not hits:
            ok = False
        if not ok:
            caught = any(f.start < e and s < f.end for f in res.flags)
            rep.auto_missed.append((t, ann.text[s:e], caught))
            continue
        if hits[0].placeholder.endswith(".last]"):
            continue          # relatives legitimately share one surname placeholder
        base = re.sub(r"\.(first|last|nick)\]$", "]", hits[0].placeholder)
        key_to_ph.setdefault(key, set()).add(base)
        ph_to_key.setdefault(base, set()).add(key)
    for key, phs in key_to_ph.items():
        if len(phs) > 1:
            rep.inconsistent.append(f"{key} got {sorted(phs)}")
    for ph, keys in ph_to_key.items():
        if len(keys) > 1:
            rep.inconsistent.append(f"{ph} shared by {sorted(keys)}")
    tagged = [(s, e) for s, e, *_ in ann.spans]
    for a in res.applied:
        if not any(a.start < e and s < a.end for s, e in tagged):
            rep.over_scrubbed.append(ann.text[a.start:a.end])
    return rep
