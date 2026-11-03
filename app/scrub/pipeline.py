"""Orders the stages and returns the scrubbed text with every applied span.

Stages: parse, speaker harvest, regex and cue detection (registers values), registry
propagation over the whole text, span merge, replacement, review flags. All spans refer
to the original text and are merged before anything is replaced; the longest span wins,
so an email containing a registered name stays one EMAIL span.
"""
import bisect
import re
from dataclasses import dataclass, field

from ..ids import header_line
from . import regex_rules
from .ner import LABEL_TO_TYPE, NerModel, NerUnavailable
from .parse import ParseIssue, TranscriptFormatError, parse_lenient
from .registry import Registry, has_token, norm, token_spans
from .spans import Span

SOURCE_PRIORITY = {"speaker": 0, "exact": 0.5, "regex": 1, "spelled": 1.2, "ner": 1.5, "cue": 2, "registry": 3}

# Capitalized words that are not worth a review flag: dates, titles, and common sentence openers.
# A word never seen in lower case in the transcript is flagged unless it is listed here.
ALLOW_CAPS = {w.casefold() for w in """
Mr Mrs Ms Miss Mister Missus Dr
The A An My Your Our In On At To For With From By Of As Like Maybe Papa
Okay Yes No Well So Right Sure Thanks Thank Hello Hi Hey Mm Uh Um Oh Ah Yeah Please Sorry Alright Absolutely
Exactly Correct Great Good Fine Anyway Actually Perfect Understood Noted Lovely Totally Ha Not Can Best Tell
Take What Who Whom Whose Which Where When Why How Did Does Do Done Are Is Was Were Am Be Been Has Have Had
Would Could Should Shall Might Must Let Let's Got Get Go Going Gone Look Say Said Says See Seen Send Sent
Tell Told Talk Talked Think Thought Know Knew Want Wanted Need Needed Give Gave Make Made Keep Kept Ask Asked
First Second Third Last Next Then Than That This These Those There Here They Them Their She Her He Him His
We Us Our You Your It Its And But Or If Because Since Until While After Before Also Just Only Even Still Yet
All Any Some Every Each Both Many Much More Most Less Few One Two Three Four Five Six Seven Eight Nine Ten
Sixty Forty Fifty Thirty Twenty Ninety Eighty Seventy Hundred Thousand Nineteen Everyone Everybody Anything
Something Nothing Everything Someone Anyone Nobody Maybe Probably Honestly Literally Seemed Signed Hold
Could Now Today Tomorrow Yesterday Tonight Always Never Sometimes Often Usually Really Very Too Yes
""".split()}
# Plain request verbs. In a change request or a direction they open a sentence ("Shorten it."), so they are not
# flagged there. A word that is also a common name (Mark, Will, Bill, Grant, Rob, Chase, Frank, May) never goes here.
REQUEST_OPENERS = frozenset("shorten add remove change use make rewrite fix keep delete include replace move update "
                            "explain list please try mention write avoid focus highlight clarify limit".split())
# Plain words that people capitalize in an instruction ("Next, mention the deadline", "- Summary of the call"). In a
# change request or a direction they are not flagged anywhere. Nothing that is also a first name goes here (Grant,
# Will, Mark, Rob, Chase, Frank, May, June, April, August, Hope, Joy, Rose, Page, Art, Pat, Sandy).
REQUEST_WORDS = frozenset("next also then finally step steps note notes summary overview form contact issue matter date "
                          "dates deadline deadlines section heading title list bullets sentence paragraph".split())
ALLOW_MID = {w.casefold() for w in """
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February July September October November
December Mr Mrs Ms Miss Mister Missus Dr Doctor
""".split()}
_CONTRACTION = re.compile(r"^(?:I|It|We|You|He|She|They|That|There|Here|What|Who|Let|How|Where|When|Don|Can|Won|Didn|"
                          r"Doesn|Isn|Wasn|Couldn|Wouldn|Shouldn|Haven|Hasn)['’][a-z]+$")


@dataclass(frozen=True)
class ScrubConfig:
    keep_first_names: bool = False   # leave first names in plain text, scrub only last names
    types: frozenset = frozenset({"PERSON", "EMAIL", "ADDRESS"})   # what to scrub; anything else is left as written
    require_ner: bool = False        # block scrubbing when the model is missing (the web app sets this)


@dataclass(frozen=True)
class Applied:
    start: int
    end: int
    type: str
    placeholder: str
    source: str


@dataclass(frozen=True)
class Flag:
    start: int
    end: int
    text: str
    reason: str
    code: str = ""       # set when the word is a name hidden for one transcript only, written here at a place not yet decided


@dataclass
class ScrubResult:
    text: str
    applied: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    notes: list = field(default_factory=list)      # things the user should know about how the text was read
    info: list = field(default_factory=list)       # how the text was read when that is normal, shown without a warning

    def for_claude(self, client_id: str, tx_id: str) -> str:
        """Header line + scrubbed text. The header is built from IDs and is never scrubbed."""
        return f"{header_line(client_id, tx_id)}\n{self.text}"


def _propagation(text: str, registry: Registry):
    """Find every known form in the text. Returns (Span, (entity, part)) pairs."""
    found = []
    for case_sensitive in (True, False):
        forms = {}
        for f in registry.iter_forms():
            if f.case_sensitive == case_sensitive:
                forms.setdefault(norm(f.surface) if not case_sensitive else " ".join(f.surface.split()), f)
        # Names in Chinese, Japanese or Korean sit inside a sentence with no space around them, so they are
        # searched without word boundaries.
        for spaced in (True, False):
            group = {k: f for k, f in forms.items() if regex_rules.has_cjk(k) != spaced}
            if not group:
                continue
            alts = "|".join(r"[ ]+".join(map(re.escape, k.split())) for k in sorted(group, key=len, reverse=True))
            pattern = rf"(?<!\w)(?:{alts})(?!\w)" if spaced else rf"(?:{alts})"
            for m in re.finditer(pattern, text, 0 if case_sensitive else re.I):
                key = " ".join(m.group().split())
                f = group[key if case_sensitive else norm(key)]
                found.append((Span(m.start(), m.end(), f.entity.type, "registry", m.group()), (f.entity, f.part)))
    return found


def local_matches(text: str, locals_) -> list:
    """(start, end, entity) for every whole-word, case-sensitive place where a name hidden in one transcript only
    (a local entity) is written in this text. Used for text typed for Claude about that transcript."""
    found = []
    forms = {" ".join(e.forms[None].split()): e for e in locals_ if e.forms.get(None) and not has_token(e.forms[None])}
    if not forms:
        return found
    alts = "|".join(r"[ ]+".join(map(re.escape, k.split())) for k in sorted(forms, key=len, reverse=True))
    for m in re.finditer(rf"(?<!\w)(?:{alts})(?!\w)", text):
        found.append((m.start(), m.end(), forms[" ".join(m.group().split())]))
    return found


def _merge(spans: list[Span]) -> list[Span]:
    """Longest span first, then source priority. A span is dropped when it overlaps one already chosen. The
    chosen spans never overlap, so they stay sorted by start and a bisect finds the only two that could clash."""
    chosen: list[Span] = []
    starts: list[int] = []
    for sp in sorted(spans, key=lambda s: (-s.length, SOURCE_PRIORITY.get(s.source, 9), s.start)):
        i = bisect.bisect_right(starts, sp.start)
        if (i > 0 and chosen[i - 1].end > sp.start) or (i < len(chosen) and chosen[i].start < sp.end):
            continue
        chosen.insert(i, sp)
        starts.insert(i, sp.start)
    return chosen


class _Covered:
    """Sorted, merged intervals with a fast overlap test, for the flag pass over a long transcript."""

    def __init__(self, intervals):
        self.starts, self.ends = [], []
        for s, e in sorted(intervals):
            if self.starts and s <= self.ends[-1]:
                self.ends[-1] = max(self.ends[-1], e)
            else:
                self.starts.append(s)
                self.ends.append(e)

    def hits(self, s: int, e: int) -> bool:
        i = bisect.bisect_left(self.ends, s + 1)          # first interval ending after s
        return i < len(self.starts) and self.starts[i] < e


def _sentence_start(text: str, i: int, lo: int, loose: bool = False) -> bool:
    """loose: an instruction, where a dash, bullet or semicolon also starts a new phrase ("- Next, ...")."""
    j = i - 1
    skip = " \t\"'“‘(-\u2013\u2014\u2022*" if loose else " \t\"'“‘("
    while j >= lo and text[j] in skip:
        j -= 1
    return j < lo or text[j] in (".?!:\n;" if loose else ".?!:\n")


_WHOLE_WORD = re.compile(r"[\w'’-]+")


def _flags(text: str, ranges, covered, openers=frozenset(), anywhere=frozenset()) -> list[Flag]:
    """Capitalized words no span covers. A capitalized word in mid-sentence is always flagged
    (except days, months and titles), so a name that is also a common word cannot hide. At the
    start of a sentence only a short list of ordinary openers is skipped."""
    flags = []
    covered = _Covered(covered)
    start = re.compile(rf"\b[{regex_rules._UP}][a-zà-ÿ'’-]+")
    for lo, hi in ranges:
        pos = lo
        while m := start.search(text, pos, hi):
            # The flag is the whole word. A piece of one ("Met" in MetLife, "Tri-" in Tri-State) could never be
            # cleared, because known values only match whole words.
            s, e = m.start(), m.start() + len(_WHOLE_WORD.match(text, m.start(), hi).group().rstrip("'’-"))
            word = text[s:e].casefold()
            if covered.hits(s, e):        # a known name inside a joined word, so look at what follows it
                pos = m.end()
                continue
            pos = e
            if _CONTRACTION.match(text[s:e]):
                continue
            opening = _sentence_start(text, s, lo, bool(openers))
            allowed = ALLOW_CAPS if opening else ALLOW_MID
            if word not in allowed and not (opening and word in openers) and word not in anywhere:
                flags.append(Flag(s, e, text[s:e], "capitalized word not covered by a placeholder"))
    return flags


def _learn_surnames(text: str, registry: Registry) -> None:
    """"Denise" is known; "Denise Brooks-Hall" appears. Learn the surname."""
    lower = {m.group().casefold() for m in re.finditer(r"\b[a-zà-ÿ][\w'’-]*", text)}
    for ent in [e for e in registry.entities if e.type == "PERSON" and e.merged_into is None and not e.local
                and "last" not in e.forms]:
        first = ent.forms[None]
        if len(first.split()) != 1:
            continue
        pat = rf"(?<!\w){re.escape(first)}[ ]+(?P<s>[{regex_rules._UP}][\w-]*)(?!\w)"
        for m in re.finditer(pat, text):
            cand = m["s"]
            if cand.casefold() not in lower and cand.casefold() not in regex_rules.NOT_NAMES \
                    and cand.casefold() not in ALLOW_CAPS:
                registry.add_surname(ent, cand)
                break


def _shrink_address(sp: Span, registry: Registry) -> Span:
    """The model's address span often runs on ("2250 Pine Ridge exit"). Cut it back to a known form."""
    best = ""
    for ent in registry.entities:
        if ent.type == "ADDRESS":
            for form in [ent.forms[None], *ent.aliases]:
                if sp.value.casefold().startswith(form.casefold()) and len(form) > len(best):
                    best = form
    return Span(sp.start, sp.start + len(best), sp.type, sp.source, sp.value[:len(best)]) if best else sp


def _bare(hit) -> bool:
    return bool(hit) and hit[1] is None and set(hit[0].forms) == {None}


def _merge_known_part(registry: Registry, tokens: list) -> bool:
    """"Joy Oyelaran" where "Joy" (or "Oyelaran") is already a lone name: same person, so add the
    other half to that entity instead of creating a second one. Word-level propagation then
    replaces each half, which keeps every earlier placeholder valid."""
    first, last = registry.lookup("PERSON", tokens[0]), registry.lookup("PERSON", tokens[-1])
    if first and last:
        return True                 # both halves already resolve; each is replaced on its own
    if _bare(first) and not last:
        return registry.add_surname(first[0], tokens[-1])
    if _bare(last) and not first:
        return registry.add_firstname(last[0], tokens[0])
    return False


def _register(registry: Registry, sp: Span, turns, prev):
    """Register a detected span. A nickname ("everybody calls me TJ") joins the speaker's entity."""
    if sp.source == "alias" and not registry.lookup("PERSON", sp.value):
        for t in turns:
            if not t.generic and t.body_span[0] <= sp.start < t.body_span[1]:
                return registry.add_nickname(registry.add_person(t.speaker)[0], sp.value)
    if sp.source == "alias_prev" and prev is not None and not registry.lookup("PERSON", sp.value):
        return registry.add_nickname(prev, sp.value)
    if sp.type == "PERSON" and len(sp.value.split()) >= 2 and not registry.lookup("PERSON", sp.value):
        if _merge_known_part(registry, sp.value.split()):
            return None
    known = sp.type != "PERSON" or registry.lookup("PERSON", sp.value)
    if sp.type == "PERSON" and not known and len(sp.value.split()) == 1:
        longer = registry.longer_entity_for(sp.value)
        if longer is not None:                       # "Jess" after "Jessica Tran"
            ent = registry.add_person(sp.value)[0]
            registry.link_nickname(longer, ent)
            return registry.lookup("PERSON", sp.value)
    hit = registry.add_value(sp.type, sp.value)
    if sp.type == "PERSON" and not known and len(sp.value.split()) >= 2:
        for short in registry.shorter_forms_of(sp.value.split()[0]):      # "Rich" before "Richard Tolliver"
            registry.link_nickname(hit[0], short)
    if sp.source == "title" and hit[1] is None and set(hit[0].forms) == {None}:
        hit[0].surname_only = True
    return hit


_PRONOUNS = set("i me my mine myself you your yours yourself she her hers he him his we us our they them their "
                "it its who whom whose this that these those".split())
_DETERMINERS = {"the", "a", "an", "some", "another", "any", "no"}
_PARTICLES = {"de", "del", "della", "la", "le", "van", "von", "der", "den", "bin", "ibn", "al", "el", "da", "di", "dos"}
_RELATION = {w.casefold() for w in regex_rules._REL.split("|")} | {
    "papa", "papá", "mama", "mamá", "mom", "dad", "mommy", "daddy", "grandma", "grandpa", "auntie", "aunt", "uncle"}
_NOT_A_NAME = _PRONOUNS | _RELATION | ALLOW_CAPS | regex_rules.NOT_NAMES


def _clean_person(text: str, s: int, e: int):
    """The model also labels pronouns, relation words and phrases as people ("I", "my father").
    Keep only spans that still hold a name-like word after stripping those. Returns (s, e) or None."""
    toks = list(re.finditer(r"\S+", text[s:e]))
    while toks and (toks[0].group().casefold() in _PRONOUNS | _DETERMINERS
                    or toks[0].group().casefold().rstrip(".") in regex_rules.TITLE_WORDS):
        toks.pop(0)
    words = [t.group().strip(".,;:!?\"“”") for t in toks]
    if not words or any(w and w[0].islower() and w.casefold() not in _PARTICLES for w in words):
        return None
    if all(w.casefold() in _NOT_A_NAME or not w for w in words):
        return None
    return s + toks[0].start(), s + toks[-1].end()


def _clean_value(kind: str, value: str) -> bool:
    low = value.lower()
    if kind == "EMAIL":
        return "@" in value or (" at " in low and " dot " in low)
    if kind == "ADDRESS":
        return any(w[0].isdigit() or (w[0].isupper() and w.casefold() not in _NOT_A_NAME) for w in value.split())
    return True


def _ner_spans(text: str, ranges, ner: NerModel):
    """Model hits become spans; hits just below the threshold become review flags."""
    spans, near = [], []
    for lo, hi in ranges:
        res = ner.detect(text[lo:hi])
        for h in res.hits:
            s, e, t = lo + h.start, lo + h.end, LABEL_TO_TYPE.get(h.label)
            if t == "PERSON" and re.fullmatch(r"(?:[A-Za-z]-)+[A-Za-z]", text[s:e]):
                spans.append(Span(s, e, "PERSON", "spelled", text[s:e].replace("-", "")))
                continue
            if t == "PERSON":
                cleaned = _clean_person(text, s, e)
                trimmed = regex_rules._trim_name(text, *cleaned) if cleaned else None
                if not trimmed:
                    continue
                s, e = trimmed
            if t and _clean_value(t, text[s:e]):
                value = text[s:e]
                if t == "EMAIL" and "@" not in value and " at " in value.lower():
                    value = regex_rules.spoken_to_email(value)
                spans.append(Span(s, e, t, "ner", value))
        for h in res.near_misses:      # same clean-up as hits, so "you" and "my mother" do not become flags
            s, e, t = lo + h.start, lo + h.end, LABEL_TO_TYPE.get(h.label)
            if t == "PERSON":
                cleaned = _clean_person(text, s, e)
                trimmed = regex_rules._trim_name(text, *cleaned) if cleaned else None
                if not trimmed:
                    continue
                s, e = trimmed
            if t and _clean_value(t, text[s:e]):
                near.append(Flag(s, e, text[s:e], f"model score {h.score:.2f}, below the threshold"))
    return spans, near


def _scrub(text: str, registry: Registry, config: ScrubConfig, review_ranges, turns=(), ner=None,
           openers=frozenset(), exact=(), skip=(), anywhere=frozenset(), local=(), ask=()) -> ScrubResult:
    """exact: (start, end, entity) places hidden with that entity's placeholder, whatever the registry knows.
    skip: (start, end) places the reviewer chose to keep, which known-value matching must leave as written and the
    flag pass must not raise again. local: entities hidden in one transcript only; their name is hidden wherever it is
    written in this text (text typed about that transcript), even with the keep-first-names option. ask: entities of
    that kind whose word is also written elsewhere in the transcript as plain text (a month, say). Each place of the
    word in this text is flagged with the entity's code, and is hidden only where `exact` says so."""
    tokens = code_cover = _Covered(token_spans(text))            # [PERSON_1] and the like are codes already: never a value or a flag
    detected = regex_rules.detect(text)
    near_flags = []
    if ner is not None:
        found, near_flags = _ner_spans(text, review_ranges, ner)
        detected = sorted(detected + found, key=lambda sp: (sp.start, -sp.length))
    detected = [sp for sp in detected if sp.type in config.types and not tokens.hits(sp.start, sp.end)]
    here = local_matches(text, local) if "PERSON" in config.types else []
    asked_all = local_matches(text, ask) if "PERSON" in config.types else []
    if here or asked_all:        # a name hidden for this transcript wins over the model's guess at the same words, which would make it known
        place = _Covered([(s, e) for s, e, _ in here + asked_all])
        detected = [sp for sp in detected if not place.hits(sp.start, sp.end)]
    if "PERSON" not in config.types:
        near_flags = []
    candidates, prev = [], None
    for i, sp in enumerate(detected):
        if sp.source == "ner" and sp.type == "ADDRESS":
            sp = detected[i] = _shrink_address(sp, registry)
        hit = _register(registry, sp, turns, prev)
        if hit is None:                  # merged into an existing person; word-level spans cover it
            continue
        candidates.append((sp, hit))
        if sp.type == "PERSON" and not sp.source.startswith("alias"):
            prev = hit[0]
    _learn_surnames(text, registry)
    candidates = [(sp, registry.lookup(sp.type, sp.value) or hit) for sp, hit in candidates]   # surnames may have moved
    skip_cover = _Covered(skip)
    candidates += [(sp, hit) for sp, hit in _propagation(text, registry)
                   if sp.type in config.types and not skip_cover.hits(sp.start, sp.end) and not tokens.hits(sp.start, sp.end)]
    candidates += [(Span(s, e, ent.type, "exact", text[s:e]), (ent, None)) for s, e, ent in exact
                   if not tokens.hits(s, e)]
    candidates += [(Span(s, e, ent.type, "exact", text[s:e]), (ent, None)) for s, e, ent in here
                   if not tokens.hits(s, e)]
    by_span = {id(sp): hit for sp, hit in candidates}
    merged = _merge([sp for sp, _ in candidates])

    out, applied, kept, last = [], [], [], 0
    for sp in merged:
        ent, part = by_span[id(sp)]
        s, e, ph = sp.start, sp.end, ent.placeholder(part)
        if sp.type == "PERSON" and config.keep_first_names:
            tokens = list(re.finditer(r"\S+", text[s:e]))
            if sp.source != "exact" and (part in ("first", "nick")
                                         or (part is None and "last" not in ent.forms and not ent.surname_only)):
                kept.append((s, e))
                continue
            if sp.source != "exact" and part is None and len(tokens) == 2:     # "Maria Lopez" -> "Maria [PERSON_2.last]"
                kept.append((s, s + tokens[0].end()))     # the first name stays on purpose, so it is not a flag
                s, ph = s + tokens[1].start(), ent.placeholder("last")
        out.append(text[last:s])
        out.append(ph)
        last = e
        applied.append(Applied(s, e, sp.type, ph, sp.source))
    out.append(text[last:])
    covered = [(a.start, a.end) for a in applied] + kept + [tuple(p) for p in skip] + token_spans(text)
    flags = _flags(text, review_ranges, covered, openers, anywhere) if "PERSON" in config.types else []
    near_cover = _Covered(covered)
    near = [f for f in near_flags if not near_cover.hits(f.start, f.end)]
    flags = [f for f in flags if not any(f.start < n.end and n.start < f.end for n in near)] + near
    decided = {(s, e) for s, e, _ in exact} | {(s, e) for s, e in skip}
    asks = [Flag(s, e, text[s:e], "also hidden as a name elsewhere in this transcript", ent.placeholder())
            for s, e, ent in asked_all if (s, e) not in decided and not code_cover.hits(s, e)]
    if asks:
        flags = [f for f in flags if not any(f.start < a.end and a.start < f.end for a in asks)] + asks
    return ScrubResult("".join(out), applied, sorted(flags, key=lambda f: f.start))


def _check_ner(config: ScrubConfig, ner: NerModel | None) -> None:
    if config.require_ner and (ner is None or not ner.available):
        raise NerUnavailable("The NER model is not installed. Scrubbing is blocked; run scripts/export_onnx.py.")


def scrub_transcript(text: str, registry: Registry, config: ScrubConfig = ScrubConfig(),
                     ner: NerModel | None = None, exact=(), skip=()) -> ScrubResult:
    """Scrub a call transcript. Speaker lines are used when they can be recognized. Any other layout, or none at
    all, is read as plain text, so a transcript is never refused for its format."""
    _check_ner(config, ner)
    if not text.strip():
        raise TranscriptFormatError([ParseIssue(0, "Nothing was pasted.")])
    reading = parse_lenient(text)
    for turn in reading.turns:
        if not turn.generic and "PERSON" in config.types and not token_spans(turn.speaker):
            registry.add_person(turn.speaker)
    res = _scrub(text, registry, config, reading.ranges, reading.turns, ner, exact=exact, skip=skip)
    res.notes = reading.notes
    res.info = reading.info
    return res


def scrub_message(text: str, registry: Registry, config: ScrubConfig = ScrubConfig(),
                  ner: NerModel | None = None, plain_requests: bool = False, local=(), ask=(), exact=(),
                  skip=()) -> ScrubResult:
    """Outgoing corrections and comments: same detection, no transcript format required. plain_requests: the text is
    an instruction to Claude (a change request or directions), so a plain verb that opens a sentence is not flagged.
    Known names are still hidden there, and a capital in the middle of a sentence is still flagged. local: names hidden
    in one transcript only, which are hidden here too and never flagged. ask: such names whose word is also plain text
    in that transcript; every place is flagged (with the code) until `exact` (start, end, entity) hides it or `skip`
    (start, end) sends it as written."""
    _check_ner(config, ner)
    return _scrub(text, registry, config, [(0, len(text))], (), ner,
                  openers=REQUEST_OPENERS if plain_requests else frozenset(),
                  anywhere=REQUEST_WORDS if plain_requests else frozenset(), local=local, ask=ask,
                  exact=exact, skip=skip)
