"""Restore real values in Claude's output. Values are returned as plain text, never HTML."""
import re
from dataclasses import dataclass, field

from .ids import find_header
from .scrub.regex_rules import has_cjk
from .scrub.registry import PLACEHOLDER_RE, Registry, norm


@dataclass
class RehydrationResult:
    text: str
    client_id: str | None = None
    tx_id: str | None = None
    unknown: list = field(default_factory=list)        # placeholders not in the registry, left as written
    unused: list = field(default_factory=list)         # registry entities never mentioned (info only)
    possible_real: list = field(default_factory=list)  # real values already in plain text (warning)


def rehydrate(text: str, registry: Registry, client_first_name: str | None = None,
              keep_first_names: bool = False, keep_last_names: bool = False) -> RehydrationResult:
    header = find_header(text)
    res = RehydrationResult(text, header["client"] if header else None, header["tx"] if header else None)
    used, out, last = set(), [], 0
    for m in PLACEHOLDER_RE.finditer(text):
        ent = registry.entity(m["type"].upper(), int(m["n"]))
        part = m["part"].lower() if m["part"] else None
        value = registry.surface(ent, part) if ent else None
        out.append(text[last:m.start()])
        if value is None:
            res.unknown.append(m.group())
            out.append(m.group())
        else:
            used.add((ent.type, ent.n))
            out.append(value)
        last = m.end()
    out.append(text[last:])
    res.text = "".join(out)
    res.unused = [e.placeholder() for e in registry.entities
                  if e.merged_into is None and (e.type, e.n) not in used]

    # Real values already visible in plain text: mask placeholders and the header, then search.
    masked = PLACEHOLDER_RE.sub(lambda m: " " * len(m.group()), text)
    if header:
        masked = masked[:header.start()] + " " * len(header.group()) + masked[header.end():]
    skip = {norm(client_first_name)} if client_first_name else set()
    seen = set()
    for f in registry.iter_forms():
        if norm(f.surface) in skip or (keep_first_names and f.part == "first") or (keep_last_names and f.part == "last") or norm(f.surface) in seen:
            continue
        flags = 0 if f.case_sensitive else re.I
        cjk = has_cjk(f.surface)                                           # CJK names have no word boundary
        before, after = ("", "") if cjk else (r"(?<!\w)", r"(?!\w)")
        if re.search(before + re.escape(f.surface) + after, masked, flags):
            seen.add(norm(f.surface))
            res.possible_real.append(f.surface)
    return res
