"""What the web app does, without any web code: intake, review, outgoing messages, import, registry edits.

Nothing here keeps an original transcript. The intake preview and the final save each scrub the text the
browser sends, and only the scrubbed result reaches storage.
"""
import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

from .store import Store
from .ids import CLIENT_ID_RE, HEADER_RE, TX_ID_RE, find_header, header_line
from .outputs import DEFAULT_INSTRUCTIONS, MARKER_RE, MAX_INSTRUCTION, NAMES as OUTPUT_NAMES, OUTPUTS, SHORT_NAMES, SLUGS as OUTPUT_SLUGS
from .rehydrate import PLACEHOLDER_RE, rehydrate
from .scrub.ner import NerModel
from .scrub.parse import ParseIssue, TranscriptFormatError, parse_lenient
from .scrub.pipeline import ScrubConfig, _propagation, local_matches, scrub_message, scrub_transcript
from .scrub.registry import Registry, has_token, norm, token_spans

CONTEXT = 48
MAX_PASTE = 400_000
EARLIEST_CALL = date(1990, 1, 1)


def clean_text(text: str) -> str:
    """The pasted text as the scrubber should read it. Invisible format characters (zero-width spaces, a byte
    order mark from a saved file) would split a name in two, and a decomposed accent would not match the same
    name typed with a composed one. Applied before scrubbing and before any offset is computed, so the review
    page and the scrubber always see the same characters."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")      # browsers send CRLF
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def local_time(stamp: str) -> str:
    """A stored UTC timestamp as the user's own date and time. Unreadable values are shown as they are."""
    try:
        return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(stamp)


def local_day(stamp: str) -> str:
    return local_time(stamp)[:10]


def _same_call_text(text: str) -> str:
    """Scrubbed text with the spacing that does not change the call removed, to spot a repeated paste."""
    return "\n".join(line.rstrip() for line in text.strip().split("\n"))


SUMMARY_PROMPT = ("Please write a running summary of everything we have covered for this client so far: who the "
                  "people are (using the placeholders exactly as written), the facts and dates, what has been "
                  "decided, what is open, and what I still need to ask. Keep every placeholder unchanged. I will "
                  "paste this summary at the start of a new chat.")


COPY_INTRO_START = ("Keep every placeholder, such as [PERSON_1] or [EMAIL_1], exactly as written, and never guess the real "
                    "value. Use the call transcript after the header line to write the outputs below, one per output.")
COPY_TOOL = ("If you have the save_output tool, call it once for each output with the client ID, the transcript ID, "
             "the output ID and the full text. If you do not have it, reply")
COPY_REPLY = ("with each output under a line that reads exactly like [OUTPUT: {example}], using the output ID from the "
              "list, with nothing else on that line.")


PROJECT_INSTRUCTIONS = """You help a law office with client intake. Every message starts with a header line, [CLIENT: <client ID> | TX: <transcript ID>].

Personal data has been replaced with placeholders such as [PERSON_1], [PERSON_1.first], [PERSON_1.last], [PERSON_1.rest], [EMAIL_1] and [ADDRESS_1].

Rules
- Copy placeholders exactly as written. Never change their case or format, never invent new ones, and never guess the real values.
- The same placeholder always means the same person or thing across this chat.
- Do only the outputs listed in the message, using the instructions given with each. Do not write the others.
- Start every output with the header line of the transcript it is based on.
{saving}
Changes
- A message that says "Revise only the output named below", or starts with [CORRECTION], revises one output for the transcript named in its header. Return the full revised output, not only the changes, and save it the same way as above.

Summaries
- If asked for a running summary of the chat, keep every placeholder exactly as written."""

PROJECT_SAVE_TOOL = ("- Saving. When you have the save_output tool, call it once for each output with the client ID, the transcript ID, "
                     "the output ID (clio-note, jordan-calendar-overview or clio-form-note) and the full text. If you cannot call it, "
                     "reply with each output under a line that reads exactly like [OUTPUT: clio-note], with nothing else on that line.")
PROJECT_SAVE_REPLY = ("- Saving. Reply with each output under a line that reads exactly like [OUTPUT: clio-note], using the output ID "
                      "(clio-note, jordan-calendar-overview or clio-form-note), with nothing else on that line. The person saves your "
                      "reply into the app.")


def project_instructions(connector_on: bool) -> str:
    """The standing text for the claude.ai Project instructions box. It names the save_output tool only when the
    connector is switched on, like Copy for Claude does. The wording for each output comes with every copy."""
    return PROJECT_INSTRUCTIONS.format(saving=PROJECT_SAVE_TOOL if connector_on else PROJECT_SAVE_REPLY)


def copy_intro(example: str, connector_on: bool) -> str:
    """The opening of Copy for Claude. The save_output tool is mentioned only when the connector is switched on in
    Settings, because Claude cannot use a tool the user has not connected."""
    reply = COPY_REPLY.format(example=example)
    return f"{COPY_INTRO_START} " + (f"{COPY_TOOL} {reply}" if connector_on else f"Reply {reply}")


class ReviewIncomplete(Exception):
    """Some flagged words have no decision yet."""


class DirectionsFlagged(Exception):
    """The directions hold capitalized words that might be names. `words` are the ones not yet confirmed."""

    def __init__(self, words, groups=()):
        super().__init__(", ".join(words))
        self.words = list(words)
        self.groups = list(groups)      # the open flag groups, so the page can show the places that need a choice


class ImportProblem(Exception):
    """The pasted reply cannot be imported as it is. The message says what to do."""


ALL_TYPES = ("PERSON", "EMAIL", "ADDRESS")
STATUS_LABELS = {"draft": "Not reviewed", "reviewed": "Ready to copy", "copied": "Copied, waiting for Claude"}
TYPE_LABELS = {"PERSON": "Names", "EMAIL": "Email addresses", "ADDRESS": "Street addresses"}


@dataclass
class Settings:
    threshold: float = 0.5
    idle_minutes: int = 10
    keep_first_names: bool = False
    mcp_enabled: bool = False
    types: frozenset = frozenset(ALL_TYPES)       # what to scrub; a client can narrow this, never the global setting
    keep_last_names: bool = False                 # per client only, applied when a call is copied or shown


@dataclass
class ClientOptions:
    """What is scrubbed for one client. first_names: 'inherit' uses the global setting."""
    types: frozenset = frozenset(ALL_TYPES)
    first_names: str = "inherit"                  # inherit, scrub or keep
    last_names: str = "scrub"                     # scrub or keep; everything after the first word of a name


def load_client_options(store: Store, client_id: str) -> ClientOptions:
    raw = store.get_setting(f"client.{client_id}.types")
    types = frozenset(t for t in (raw or "").split(",") if t in ALL_TYPES) if raw is not None else frozenset(ALL_TYPES)
    first = store.get_setting(f"client.{client_id}.first_names", "inherit")
    last = store.get_setting(f"client.{client_id}.last_names", "scrub")
    return ClientOptions(types, first if first in ("inherit", "scrub", "keep") else "inherit",
                         last if last in ("scrub", "keep") else "scrub")


def save_client_options(store: Store, client_id: str, opts: ClientOptions) -> None:
    if not opts.types:
        raise ValueError("Choose at least one thing to scrub.")
    if (not set(opts.types) <= set(ALL_TYPES) or opts.first_names not in ("inherit", "scrub", "keep")
            or opts.last_names not in ("scrub", "keep")):
        raise ValueError("Unknown scrub option.")
    store.set_setting(f"client.{client_id}.types", ",".join(t for t in ALL_TYPES if t in opts.types))
    store.set_setting(f"client.{client_id}.first_names", opts.first_names)
    store.set_setting(f"client.{client_id}.last_names", opts.last_names)
    store.audit("client_options", client_id)


def client_settings(store: Store, client_id: str, base: Settings) -> Settings:
    """The global settings with this client's own scrub options applied on top."""
    o = load_client_options(store, client_id)
    keep = base.keep_first_names if o.first_names == "inherit" else o.first_names == "keep"
    return Settings(base.threshold, base.idle_minutes, keep, base.mcp_enabled, o.types, o.last_names == "keep")


def lone_name_is_first(ent) -> bool:
    """For a code with no part whose full form is one word: is that word a first name? The word is a surname when a
    first name is known beside it or it was seen after a title, and a first name when a last name is known beside it.
    A word seen alone counts as a first name, as the scrubber does when first names are kept."""
    if ent.surname_only or "first" in ent.forms:
        return False
    return True


def name_hidden(cs: Settings) -> tuple[bool, bool]:
    """(first names hidden, last names hidden) for this client. With names switched off, neither is."""
    on = "PERSON" in cs.types
    return on and not cs.keep_first_names, on and not cs.keep_last_names


def person_pieces(ent, part: str | None, hide_first: bool, hide_last: bool):
    """The pieces of one name code, as [(text, code or None)], or None when the code has no known value. A piece with a
    code is hidden from Claude, and the code is what it is sent as. The first name is the first word, and the last name
    is everything after it, so "Maria Elena Lopez" with only the first name hidden is "[PERSON_1.first] Elena Lopez"."""
    full = ent.forms.get(None) or ""
    words = full.split()
    if part in ("first", "nick", "last"):
        value = ent.forms.get(part) or (words[0] if part == "first" and len(words) > 1 else None)
        return [(value, ent.placeholder(part) if (hide_last if part == "last" else hide_first) else None)] if value else None
    if part == "rest":
        value = " ".join(words[1:]) if len(words) > 1 else None
        return [(value, ent.placeholder("rest") if hide_last else None)] if value else None
    if not words:
        return None
    if len(words) == 1:                  # one word: a first name or a surname, by what else is known about the person
        return [(full, ent.placeholder() if (hide_first if lone_name_is_first(ent) else hide_last) else None)]
    if hide_first and hide_last:
        return [(full, ent.placeholder())]
    if not hide_first and not hide_last:
        return [(full, None)]
    if (ent.forms.get("first") or words[0]) != words[0]:     # a first name that is not the first word: leave the name whole
        return [(full, ent.placeholder())]
    rest = " ".join(words[1:])
    last_code = ent.placeholder("last") if len(words) == 2 and ent.forms.get("last") == rest else ent.placeholder("rest")
    if hide_first:
        return [(words[0], ent.placeholder("first")), (" " + rest, None)]
    return [(words[0] + " ", None), (rest, last_code)]


def hide_known_now(store: Store, client_id: str, tx_id: str, text: str, registry: Registry | None = None) -> tuple[str, int]:
    """Saved call text with every real value the client's hidden names know now replaced by its code. A name hidden
    after the call was saved (from another call, from a message, or added by hand) is caught here, so no copy or view
    depends on the list as it stood at the first save. A word the reviewer chose to keep on this call stays as written,
    and so do the client's own first name and the name parts the options send as written. Returns (text, places)."""
    client = store.get_client(client_id)
    registry = registry or store.load_registry(client_id)
    keep_plain = _keep_plain(client, *keep_flags(store, client_id))
    if any(d["decision"] == "keep" for d in store.list_review_decisions(tx_id)):
        keep_plain |= {norm(f.surface) for f in registry.iter_forms() if store.decided_keep(tx_id, f.surface)}
    return mask_known_values(text, registry, keep_plain)


def restore_switched_off(store: Store, client_id: str, text: str, registry: Registry | None = None) -> str:
    """Scrubbed call text as it should leave for Claude under this client's scrubbing options. A code of a kind switched
    off, or a name part the options leave visible, is replaced by its real value, so the options hold for calls saved
    before they were changed. A name hidden in part is split ("Maria [PERSON_1.rest]"). A code with no known value stays
    as written."""
    cs = client_settings(store, client_id, load_settings(store))
    hide_first, hide_last = name_hidden(cs)
    if set(ALL_TYPES) <= cs.types and hide_first and hide_last:
        return text
    registry = registry or store.load_registry(client_id)

    def swap(m):
        type_ = m["type"].upper()
        ent = registry.entity(type_, int(m["n"]))
        part = m["part"].lower() if m["part"] else None
        if ent is None:
            return m.group()
        if type_ == "PERSON":
            pieces = person_pieces(ent, part, hide_first, hide_last)
            return "".join(code or t for t, code in pieces) if pieces else m.group()
        if type_ not in cs.types:
            return registry.surface(ent, part) or m.group()
        return m.group()
    return PLACEHOLDER_RE.sub(swap, text)


def load_settings(store: Store) -> Settings:
    d = Settings()
    return Settings(
        threshold=float(store.get_setting("threshold", d.threshold)),
        idle_minutes=int(store.get_setting("idle_minutes", d.idle_minutes)),
        keep_first_names=False,          # no global box any more: each client's options row decides (an old stored value is ignored)
        mcp_enabled=store.get_setting("mcp_enabled", "0") == "1")


def save_settings(store: Store, s: Settings) -> None:
    if not 0.05 <= s.threshold <= 0.99:
        raise ValueError("The threshold must be between 0.05 and 0.99.")
    if not 1 <= s.idle_minutes <= 240:
        raise ValueError("Idle unload must be between 1 and 240 minutes.")
    store.set_setting("threshold", s.threshold)
    store.set_setting("idle_minutes", s.idle_minutes)
    store.set_setting("mcp_enabled", "1" if s.mcp_enabled else "0")


def apply_settings(ner: NerModel, s: Settings) -> None:
    ner.config.threshold = s.threshold
    ner.config.idle_seconds = s.idle_minutes * 60


def scrub_config(s: Settings) -> ScrubConfig:
    return ScrubConfig(keep_first_names=s.keep_first_names, require_ner=True, types=frozenset(s.types))


# ---- display helpers ------------------------------------------------------------------------

def segments(text: str, spans) -> list:
    """[(text, type or None)] for the original text, given (start, end, type) spans."""
    out, last = [], 0
    for s, e, t in sorted(spans):
        if s < last:
            continue
        out.append((text[last:s], None))
        out.append((text[s:e], t))
        last = e
    out.append((text[last:], None))
    return [(t, ty) for t, ty in out if t]


def real_segments(store: Store, client_id: str, scrubbed: str, tx_id: str | None = None) -> list:
    """[(text, type or None)] for the Transcript tab: each placeholder shows its real value. A value keeps its tag while
    Claude does not get it, and is plain when the options send it as written. A name hidden in part is shown in pieces.
    A code with no known value stays as the code, tagged."""
    registry = store.load_registry(client_id)
    if tx_id:                      # what a copy would hide now, so a name hidden later shows as hidden here too
        scrubbed = hide_known_now(store, client_id, tx_id, scrubbed, registry)[0]
    cs = client_settings(store, client_id, load_settings(store))
    hide_first, hide_last = name_hidden(cs)
    out, last = [], 0
    for m in PLACEHOLDER_RE.finditer(scrubbed):
        if m.start() > last:
            out.append((scrubbed[last:m.start()], None))
        type_ = m["type"].upper()
        ent = registry.entity(type_, int(m["n"]))
        part = m["part"].lower() if m["part"] else None
        if type_ == "PERSON" and ent is not None:
            pieces = person_pieces(ent, part, hide_first, hide_last)
            out.extend((t, "PERSON" if code else None) for t, code in pieces) if pieces else out.append((m.group(), type_))
        else:
            value = registry.surface(ent, part) if ent else None
            out.append((value if value is not None else m.group(), None if value is not None and type_ not in cs.types else type_))
        last = m.end()
    if last < len(scrubbed):
        out.append((scrubbed[last:], None))
    return out


def tag_segments(scrubbed: str) -> list:
    """[(text, type or None)] for scrubbed text: each placeholder becomes a tagged piece."""
    out, last = [], 0
    for m in PLACEHOLDER_RE.finditer(scrubbed):
        out.append((scrubbed[last:m.start()], None))
        out.append((m.group(), m["type"].upper()))
        last = m.end()
    out.append((scrubbed[last:], None))
    return [(t, ty) for t, ty in out if t]


def client_full_name(client_first: str, registry: Registry) -> str:
    """The real full name of the client as seen locally: the person whose first name matches."""
    want = norm(client_first)
    best = ""
    for e in registry.entities:
        if e.type == "PERSON" and e.merged_into is None:
            full = e.forms.get(None, "")
            tokens = full.split()
            if tokens and norm(tokens[0]) == want and len(tokens) > len(best.split()):
                best = full
    return best or client_first


def client_rows(store: Store, include_archived: bool = False) -> list:
    activity = store.client_activity()
    rows = []
    for c in store.list_clients(include_archived):
        reg = store.load_registry(c["id"])
        rows.append({"id": c["id"], "first_name": c["first_name"], "archived": bool(c["archived"]),
                     "full_name": client_full_name(c["first_name"], reg), "last": activity.get(c["id"], "")})
    rows.sort(key=lambda r: r["last"], reverse=True)
    return rows


# ---- who is the client ----------------------------------------------------------------------

@dataclass
class Person:
    full: str
    first: str
    mentions: int
    speaker: bool
    likely_staff: bool          # the office speaker of the call: known from other clients, else the first speaker


@dataclass
class Detection:
    people: list                # Person, best client guess first
    suggested: str              # first name to offer for a new client ("" when nobody suitable was found)
    matches: list               # existing clients this transcript seems to belong to, best first


@dataclass
class KnownNames:
    """What every client's hidden names say about who is who, read once for a match."""
    clients: dict               # norm(full name) -> set of client IDs that store it
    office: set                 # norm(full name) of people marked as office staff in the client that stores them
    registries: dict            # client ID -> Registry

    def shared(self, full: str) -> bool:
        return len(self.clients.get(norm(full), ())) > 1

    def staff(self, full: str) -> bool:
        """Office staff by a mark, or stored for more than one client, which only office staff are."""
        return norm(full) in self.office or self.shared(full)


def known_names(store: Store) -> KnownNames:
    clients: dict = {}
    office: set = set()
    registries: dict = {}
    for c in store.list_clients(include_archived=True):
        reg = registries[c["id"]] = store.load_registry(c["id"])
        for e in reg.entities:
            full = e.forms.get(None, "") if e.type == "PERSON" and e.merged_into is None and not e.local else ""
            if len(full.split()) >= 2:
                clients.setdefault(norm(full), set()).add(c["id"])
                if e.office:
                    office.add(norm(full))
    return KnownNames(clients, office, registries)


def office_speaker(turns, registry: Registry, names: KnownNames | None = None, client_first: str | None = None):
    """The entity that answers the calls, from the speaker lines of one call, or None when that cannot be told.
    Someone known as office staff wins. Otherwise the first speaker, unless that is the client (when the client is
    known) or the call has only one speaker (when it is not)."""
    order: list = []
    for turn in turns:
        if turn.generic:
            continue
        hit = registry.lookup("PERSON", turn.speaker)
        if hit and hit[0] not in order:
            order.append(hit[0])

    def is_client(e) -> bool:
        return client_first is not None and norm((e.forms.get(None) or "").split(" ")[0]) == norm(client_first)
    others = [e for e in order if not is_client(e)]
    if names is not None:
        for e in others:
            if names.staff(e.forms.get(None, "")):
                return e
    if others and others[0] is order[0] and (len(order) >= 2 or client_first is not None):
        return others[0]
    return None


def detect_client(store: Store, text: str, ner: NerModel, settings: Settings) -> Detection:
    """Look at a pasted transcript before any client is chosen. Scrubs against an empty registry, so nothing is
    stored and no client is created. The result is a suggestion the user can change. The office speaker is left out
    of the matching and of the suggested name: someone known as office staff, else the first speaker."""
    if len(text) > MAX_PASTE:
        raise TranscriptFormatError([ParseIssue(0, f"The pasted text is over {MAX_PASTE // 1000} KB.")])
    text = clean_text(text)
    apply_settings(ner, settings)
    registry = Registry()
    res = scrub_transcript(text, registry, scrub_config(settings), ner)
    counts: dict = {}
    for a in res.applied:
        m = PLACEHOLDER_RE.search(a.placeholder)
        if m and m["type"].upper() == "PERSON":
            counts[int(m["n"])] = counts.get(int(m["n"]), 0) + 1
    turns = parse_lenient(text).turns
    speaker_order: list = []
    for turn in turns:
        if turn.generic:
            continue
        hit = registry.lookup("PERSON", text[turn.speaker_span[0]:turn.speaker_span[1]])
        if hit and hit[0].n not in speaker_order:
            speaker_order.append(hit[0].n)
    names = known_names(store)
    staff = office_speaker([t for t in turns if not t.generic], registry, names)
    people = []
    for e in registry.entities:
        if e.type != "PERSON" or e.merged_into is not None:
            continue
        full = e.forms.get(None, "")
        if full:
            people.append(Person(full, full.split()[0], counts.get(e.n, 0), e.n in speaker_order,
                                 (staff is not None and e is staff) or names.staff(full)))

    def rank(p: Person):
        return (p.likely_staff, not p.speaker, -p.mentions)
    people.sort(key=rank)
    matches = _client_matches(names, [p for p in people if not p.likely_staff], store)
    matched = {m["via"] for m in matches}
    # A name already stored for another client is never offered as a new client.
    fresh = [p for p in people if not p.likely_staff and p.full not in matched and not names.clients.get(norm(p.full))]
    return Detection(people, fresh[0].first if fresh else "", matches)


def _client_matches(names: KnownNames, people: list, store: Store) -> list:
    """Existing clients that one of these non-office people belongs to. A full-name hit is strong, unless that name
    is also stored for another client or is marked as office staff there. A first name that equals the client's own
    first name is weak, because two clients can share one. People who spoke rank before people only mentioned, then
    by mentions. Each row names the person it matched."""
    found: dict = {}
    for c in store.list_clients(include_archived=True):
        reg = names.registries[c["id"]]
        for rank_, p in enumerate(people):
            hit = reg.lookup("PERSON", p.full) if len(p.full.split()) >= 2 else None
            strong = (hit is not None and norm(hit[0].forms.get(None, "")) == norm(p.full)
                      and not names.staff(p.full))
            weak = norm(p.first) == norm(c["first_name"]) and not names.staff(p.full)
            if not (strong or weak):
                continue
            score = (not strong, not p.speaker, -p.mentions, rank_)
            calls = [t["call_date"] for t in store.list_transcripts(c["id"]) if t.get("call_date")]
            row = found.setdefault(c["id"], {"id": c["id"], "name": client_full_name(c["first_name"], reg),
                                              "strong": strong, "via": p.full, "archived": bool(c["archived"]),
                                              "last_call": max(calls) if calls else "", "calls": len(calls),
                                              "score": score})
            if score < row["score"]:
                row.update(strong=strong, via=p.full, score=score)
    return sorted(found.values(), key=lambda r: (r["score"], r["id"]))


# ---- intake and review ----------------------------------------------------------------------

@dataclass
class FlagGroup:
    text: str
    reason: str
    occurrences: list = field(default_factory=list)      # dicts: start, end, before, after


@dataclass
class Intake:
    scrubbed: str
    applied: list
    registry: Registry
    groups: list                 # flag groups that still need a decision
    original_segments: list
    scrubbed_segments: list
    notes: list = field(default_factory=list)      # how the text was read, when that is worth telling the user
    info: list = field(default_factory=list)       # how it was read when that is normal (shown as plain information)
    cleaned: str = ""            # the text the offsets refer to. The review page posts this back, so spans stay valid


def _groups(text: str, flags, keep: set) -> list:
    by_text: dict = {}
    for f in flags:
        if f.text in keep:
            continue
        g = by_text.setdefault(f.text, FlagGroup(f.text, f.reason))
        g.occurrences.append({"start": f.start, "end": f.end,
                              "before": text[max(0, f.start - CONTEXT):f.start].replace("\n", " "),
                              "after": text[f.end:f.end + CONTEXT].replace("\n", " "),
                              **({"code": f.code} if f.code else {})})
    return list(by_text.values())


def is_ask(group) -> bool:
    """The word is a name hidden for this transcript only, and also written there as plain text, so each place in the
    typed text needs its own choice. Nothing here is hidden or sent as written until the person chooses."""
    return any(o.get("code") for o in group.occurrences)


def ask_list(groups) -> list:
    """The places that need a choice, for the page: [{word, code, places: [{start, end, before, after}]}]."""
    return [{"word": g.text, "code": next(o["code"] for o in g.occurrences if o.get("code")),
             "places": [{k: o[k] for k in ("start", "end", "before", "after")} for o in g.occurrences if o.get("code")]}
            for g in groups if is_ask(g)]


def open_groups(groups, confirmed) -> list:
    """The flag groups still waiting: a word ticked as written is settled, but a place that needs a choice is not
    settled by a tick."""
    done = set(confirmed)
    return [g for g in groups if is_ask(g) or g.text not in done]


@dataclass
class Plan:
    """What the reviewer decided, as the scrubber needs it."""
    scrub_all: list = field(default_factory=list)      # words hidden at every place (and remembered for this client)
    keep_all: set = field(default_factory=set)         # words left as written at every place
    exact: list = field(default_factory=list)          # (start, end, word) hidden at this place only
    skip: list = field(default_factory=list)           # (start, end) left as written at this place only


def place_ok(cleaned: str, d: dict, span) -> bool:
    """A per-place span still points at the word it was chosen for. Offsets refer to the cleaned text the review page
    holds, so a span that no longer lines up with its word is dropped and the place is asked about again."""
    s, e = span
    return 0 <= s < e <= len(cleaned) and cleaned[s:e] == clean_text(d["text"])


def plan_decisions(cleaned: str, decisions) -> Plan:
    """decisions: dicts with text, decision ('scrub' or 'keep'), spans, and each=True when the choice is for those
    places only. Without `each` the choice covers every place."""
    plan = Plan()
    for d in decisions:
        word = clean_text(d["text"])
        if d.get("each"):
            places = [(s, e) for s, e in d.get("spans", []) if place_ok(cleaned, d, (s, e))]
            if d["decision"] == "scrub":
                plan.exact += [(s, e, word) for s, e in places]
            else:
                plan.skip += places
        elif d["decision"] == "scrub":
            plan.scrub_all.append(word)
        else:
            plan.keep_all.add(word)
    return plan


def run_intake(store: Store, client_id: str, text: str, ner: NerModel, settings: Settings,
               extras=(), keep=(), decisions=()) -> Intake:
    """Scrub the pasted transcript against a copy of the client's registry. Saves nothing. decisions: the reviewer's
    choices (see plan_decisions); extras and keep are values to hide and words to leave, for every place."""
    if len(text) > MAX_PASTE:
        raise TranscriptFormatError([ParseIssue(0, f"The pasted text is over {MAX_PASTE // 1000} KB.")])
    text = clean_text(text)
    plan = plan_decisions(text, decisions)
    registry = store.load_registry(client_id)
    settings = client_settings(store, client_id, settings)
    for type_, value in [*extras, *[("PERSON", w) for w in plan.scrub_all]]:
        registry.add_value(type_, clean_text(value))
    exact = [(s, e, registry.add_local_person(w)) for s, e, w in plan.exact]
    apply_settings(ner, settings)
    res = scrub_transcript(text, registry, scrub_config(settings), ner, exact=exact, skip=plan.skip)
    kept = {clean_text(k) for k in keep} | plan.keep_all
    return Intake(res.text, res.applied, registry, _groups(text, res.flags, kept),
                  segments(text, [(a.start, a.end, a.type) for a in res.applied]), tag_segments(res.text), res.notes, res.info, text)


MAX_TITLE = 120


def clean_title(title: str) -> str:
    """The call title as it is stored: the text as typed, with invisible characters and extra spaces removed. A title
    is shown on screen only and is never part of any text sent to Claude, so nothing in it is scrubbed."""
    title = " ".join(clean_text(title).split())
    if len(title) > MAX_TITLE:
        raise ImportProblem(f"The title is over {MAX_TITLE} characters.")
    return title


def local_names(registry: Registry, text: str, tx_id: str | None = None, extra=()) -> list:
    """Entities hidden in one transcript only: chosen place by place at review (the transcript's text holds their
    code), or hidden from a typed box for that transcript (tx_id is in `only`). Text typed about that transcript knows
    them. They are not known for any other text, so a transcript that does not hold them never hides the word."""
    used = {int(m["n"]) for m in PLACEHOLDER_RE.finditer(text or "") if m["type"].upper() == "PERSON"}
    return [e for e in registry.entities if e.local and e.type == "PERSON" and e.merged_into is None
            and (e.n in used or (tx_id and tx_id in e.only) or e in extra)]


def _plain_word(text: str, word: str) -> bool:
    """The word is written in the transcript as plain text, whole word and same case, outside any code."""
    bare = PLACEHOLDER_RE.sub(" ", text or "")
    return bool(word) and re.search(rf"(?<!\w){re.escape(word)}(?!\w)", bare) is not None


def local_scope(registry: Registry, text: str, tx_id: str | None = None, extra=()) -> tuple[list, list]:
    """(auto, ask) for text typed about one transcript. auto: names hidden in this transcript only whose word no longer
    appears as plain text in it, so every place was scrubbed and the word is replaced by its code. ask: such names whose
    word still appears as plain text (a month kept at review, say), so each typed place needs its own choice."""
    auto, ask = [], []
    for e in local_names(registry, text, tx_id, extra):
        (ask if _plain_word(text, e.forms.get(None, "")) else auto).append(e)
    return auto, ask


def clean_places(places) -> list:
    """Choices for the places that need one, as sent by the page: [{start, word, choice}] with choice hide or send."""
    out = []
    for p in places if isinstance(places, (list, tuple)) else []:
        if isinstance(p, dict) and type(p.get("start")) is int and isinstance(p.get("word"), str) \
                and p.get("choice") in ("hide", "send"):
            out.append((p["start"], p["word"], p["choice"]))
    return out


def scrub_typed(text: str, registry: Registry, settings: Settings, ner: NerModel, scope, kept, places=(),
                plain: bool = True):
    """Scrub text typed for Claude about one transcript. scope: (auto, ask) from local_scope. kept: a function telling
    whether a word was already decided Keep for that transcript, so it is not flagged again (unless it is a place that
    needs a choice). places: the choices made for those places, each checked against the text. Returns the ScrubResult."""
    auto, ask = scope
    apply_settings(ner, settings)
    chosen = {(s, w): c for s, w, c in clean_places(places)}
    exact, skip = [], []
    for s, e, ent in local_matches(text, ask):
        choice = chosen.get((s, text[s:e]))
        if choice == "hide":
            exact.append((s, e, ent))
        elif choice == "send":
            skip.append((s, e))
    res = scrub_message(text, registry, scrub_config(settings), ner, plain_requests=plain, local=auto, ask=ask,
                        exact=exact, skip=skip)
    res.flags = [f for f in res.flags if f.code or not kept(f.text)]
    return res


def stored_scope(store: Store, registry: Registry, client_id: str, tx_id: str | None):
    """(auto, ask) and the Keep test for text typed about a saved transcript. Nothing for another client's or no call."""
    tx = store.get_transcript(tx_id) if tx_id else None
    if tx is None or tx["client_id"] != client_id:
        return ([], []), (lambda word: False)
    return local_scope(registry, tx["scrubbed_text"], tx_id), (lambda word: store.decided_keep(tx_id, word))


def hide_word_ok(value: str) -> str:
    """A word to hide in a message being sent, tidied, or ImportProblem."""
    value = " ".join(clean_text(value).split())
    if not value:
        raise ImportProblem("Select or type the text to hide.")
    if len(value) > MAX_HIDE:
        raise ImportProblem(f"That text is over {MAX_HIDE} characters. Hide one name at a time.")
    if "[" in value or "]" in value:
        raise ImportProblem("That text overlaps a hidden name. Select the text outside the brackets.")
    return value


def _review_scope(registry, scrubbed, mine):
    return local_scope(registry, scrubbed, None, extra=mine)


def _kept_in_review(decisions, keep=()):
    words = {norm(clean_text(d["text"])) for d in decisions if d["decision"] == "keep"} | {norm(clean_text(k)) for k in keep}
    return lambda word: norm(word) in words


def review_directions_groups(store: Store, client_id: str, text: str, ner: NerModel, settings: Settings,
                             extras=(), decisions=(), directions: str = "", here=(), wide=(), places=()) -> list:
    """The flag groups in directions typed on the review page, for the review as it stands now: the choices made so
    far (including Choose each place) decide which names are hidden in this transcript, and a word kept at review is
    not flagged. Nothing is stored."""
    intake = run_intake(store, client_id, text, ner, settings, extras, (), decisions)
    reg = intake.registry
    _, groups, _, _ = _scrub_review_directions(reg, intake, directions, ner, client_settings(store, client_id, settings),
                                               decisions, places, here, wide)
    return groups


def review_directions_flags(store: Store, client_id: str, text: str, ner: NerModel, settings: Settings,
                            extras=(), decisions=(), directions: str = "", here=(), wide=(), places=()) -> list:
    return [g.text for g in review_directions_groups(store, client_id, text, ner, settings, extras, decisions,
                                                     directions, here, wide, places)]


def _scrub_review_directions(reg, intake, directions, ner, settings, decisions, places, here, wide):
    """Directions typed on the review page, scrubbed like a change request against the registry this review holds
    (which may learn values). here: words hidden with Hide for this transcript only, each its own transcript-only entry.
    wide: words hidden for this client from now on. Neither rescans the transcript. Returns the scrubbed text, the flag
    groups, the new transcript-only entries and the new client-wide ones, so the save can tie them to the transcript it
    creates."""
    cleaned = clean_text(directions).strip()
    mine_words = [hide_word_ok(w) for w in here if not reg.lookup("PERSON", hide_word_ok(w))]
    ents = []
    for word in wide:
        word = hide_word_ok(word)
        if not reg.lookup("PERSON", word):
            ents.append(("wide", reg.add_value("PERSON", word)[0]))
    for word in mine_words:
        ents.append(("here", reg.add_local_person(word, new=True)))
    mine = [e for k, e in ents if k == "here"]
    wider = [e for k, e in ents if k == "wide"]
    if len(directions) > MAX_PASTE:
        raise ImportProblem(f"The directions are over {MAX_PASTE // 1000} KB.")
    if not cleaned:
        return "", [], mine, wider
    scope = _review_scope(reg, intake.scrubbed, mine)
    res = scrub_typed(cleaned, reg, settings, ner, scope, _kept_in_review(decisions), places)
    return res.text, _groups(cleaned, res.flags, set()), mine, wider


def save_transcript(store: Store, client_id: str, text: str, call_date: date, ner: NerModel, settings: Settings,
                    decisions=(), extras=(), title: str = "", outputs=(), directions: str = "", confirm=(),
                    here=(), wide=(), places=()) -> str:
    """Re-scrub with the reviewer's decisions and store the scrubbed result. decisions: dicts with
    text, decision ('scrub' or 'keep'), spans [(start, end)] and each (True when the choice is for those places
    only). title: an optional call title, stored as typed (see clean_title). outputs: the slugs ticked on the review
    page, kept as the call's plan (not as a request). directions: optional text for Claude, scrubbed here with the
    registry this save builds, so the call's own names become hidden names. Flagged words in it raise
    DirectionsFlagged until each is in `confirm` (and each place that needs a choice has one in `places`), and then
    nothing is saved. here: words hidden for this transcript only. wide: words hidden for this client from now on."""
    # Scrubbing can take many seconds on a long paste, so it runs outside the write lock: the connector, which is a
    # separate process, must not be refused while a save is thinking. A fingerprint of the registry taken first is
    # checked again inside the transaction. If another copy of the app changed the registry meanwhile, the scrub
    # runs again against the current one, so the save never overwrites that change.
    fingerprint = store.registry_fingerprint(client_id)
    intake = run_intake(store, client_id, text, ner, settings, extras, (), decisions)
    if intake.groups:
        raise ReviewIncomplete(", ".join(g.text for g in intake.groups))
    title_text = clean_title(title)
    planned = planned_outputs(outputs)
    names = known_names(store)
    client_first = store.get_client(client_id)["first_name"]
    dir_settings = client_settings(store, client_id, settings)
    made = {"here": [], "wide": []}

    def scrubbed_directions(intake_) -> str:
        text_, groups, mine, wider = _scrub_review_directions(intake_.registry, intake_, directions, ner, dir_settings,
                                                              decisions, places, here, wide)
        made["here"], made["wide"] = mine, wider
        wait = open_groups(groups, confirm)
        if wait:
            raise DirectionsFlagged([g.text for g in wait], groups)
        return text_
    scrubbed_dirs = scrubbed_directions(intake)
    # All the writes commit together, so a failure part way leaves no draft call without its registry and no hidden
    # client.
    with store.transaction():
        if store.registry_fingerprint(client_id) != fingerprint:
            intake = run_intake(store, client_id, text, ner, settings, extras, (), decisions)
            if intake.groups:
                raise ReviewIncomplete(", ".join(g.text for g in intake.groups))
            scrubbed_dirs = scrubbed_directions(intake)
        office = office_speaker(parse_lenient(intake.cleaned).turns, intake.registry, names, client_first)
        if office is not None:
            office.office = True
        store.set_archived(client_id, False)       # a call saved to an archived client brings them back to the sidebar
        # A double click or a repeated paste of the same call must not store the call twice.
        iso, same = call_date.isoformat(), _same_call_text(intake.scrubbed)
        for row in store.list_transcripts(client_id):
            if row["call_date"] == iso and _same_call_text(row["scrubbed_text"]) == same:
                return row["id"]
        tx = store.add_transcript(client_id, intake.scrubbed, call_date, title_text)
        for ent in made["here"]:        # a word hidden here belongs to this transcript, and was added from its directions
            ent.only, ent.via = [tx], tx
        for ent in made["wide"]:
            ent.via = tx
        store.save_registry(client_id, intake.registry, tx)
        for d in decisions:
            spans = [p for p in d["spans"] if place_ok(intake.cleaned, d, p)] if d.get("each") else d["spans"]
            for s, e in spans:
                store.save_review_decision(tx, (s, e), d["text"], d["decision"])
        store.set_transcript_status(tx, "reviewed")
        store.set_planned_outputs(tx, planned)
        store.set_transcript_directions(tx, scrubbed_dirs, [w for w in confirm if w in scrubbed_dirs])
        if planned:                 # unticking everything is no choice, so the last real choice stays
            store.set_setting("last_outputs", ",".join(planned))
        store.activate_client(client_id)
    return tx


def set_title(store: Store, client_id: str, tx_id: str, title: str) -> str:
    """Change the call title of a saved call. Returns the stored title, which is empty when it was cleared."""
    tx = store.get_transcript(tx_id)
    if tx is None or tx["client_id"] != client_id:
        raise ImportProblem("Unknown transcript for this client.")
    text = clean_title(title)
    with store.transaction():
        store.set_transcript_title(tx_id, text)
    return text


def output_instruction(store: Store, slug: str) -> str:
    """What Claude is told to produce for this output: the text saved in Settings, or the starter text."""
    return (store.get_setting(f"instructions.{slug}") or "").strip() or DEFAULT_INSTRUCTIONS[slug]


def save_output_instructions(store: Store, texts: dict) -> None:
    """texts: slug -> instruction. An empty text goes back to the starter text. Instructions are sent to Claude as
    written, so they are for staff and the task, never for client names."""
    clean = {}
    for slug in OUTPUT_SLUGS:
        text = clean_text(str(texts.get(slug, ""))).strip()
        if len(text) > MAX_INSTRUCTION:
            raise ValueError(f"The instructions for {OUTPUT_NAMES[slug]} are over {MAX_INSTRUCTION} characters.")
        clean[slug] = text
    with store.transaction():
        for slug, text in clean.items():
            store.set_setting(f"instructions.{slug}", text)


def chosen_outputs(values) -> list[str]:
    """The known output slugs among the ticked values, in the app's order. Refuses none and refuses unknown ones."""
    values = [str(v) for v in values or []]
    if not values:
        raise ImportProblem("Tick at least one output.")
    if any(v not in OUTPUT_NAMES for v in values):
        raise ImportProblem("Unknown output.")
    return [slug for slug in OUTPUT_SLUGS if slug in values]


def planned_outputs(values) -> list[str]:
    """The known output slugs ticked on the review page, in the app's order. None ticked is allowed there."""
    values = [str(v) for v in values or []]
    if any(v not in OUTPUT_NAMES for v in values):
        raise ImportProblem("Unknown output.")
    return [slug for slug in OUTPUT_SLUGS if slug in values]


def preticked_outputs(store: Store, requested, planned=()) -> list[str]:
    """What the checklist starts with: this call's last copy, else what was ticked when it was saved, else the last
    choice made anywhere in the app (which is what a brand-new client starts from)."""
    if requested:
        return list(requested)
    if planned:
        return list(planned)
    last = (store.get_setting("last_outputs") or "").split(",")
    return [slug for slug in OUTPUT_SLUGS if slug in last]


def prepare_directions(store: Store, client_id: str, directions: str, ner: NerModel,
                       settings: Settings, tx_id: str | None = None, places=()) -> tuple[str, list, Registry]:
    """The optional directions typed beside Copy for Claude, scrubbed like a change request. Returns the scrubbed
    text, the flag groups and the registry (which may have learned new values). Names hidden in this transcript only
    are replaced by their code, or asked about place by place when the same word is also plain text in the transcript.
    A word decided Keep at review is not flagged. Nothing is stored here."""
    if len(directions) > MAX_PASTE:
        raise ImportProblem(f"The directions are over {MAX_PASTE // 1000} KB.")
    directions = clean_text(directions).strip()
    registry = store.load_registry(client_id)
    if not directions:
        return "", [], registry
    settings = client_settings(store, client_id, settings)
    scope, kept = stored_scope(store, registry, client_id, tx_id)
    res = scrub_typed(directions, registry, settings, ner, scope, kept, places)
    return res.text, _groups(directions, res.flags, set()), registry


def hide_for_request(store: Store, client_id: str, value: str, tx_id: str | None = None, client_wide: bool = False) -> dict:
    """Hide a flagged word in text being sent. By default it is hidden for this transcript only: a transcript-only
    entry, tied to that transcript, that later typed text about it recognises and that no other text, import or
    transcript ever matches. client_wide: it joins the client's hidden names from now on. Nothing stored is rewritten
    (the transcript and the outputs keep their text) and no version is made. With no transcript the word can only be
    hidden for the client. Returns {"code", "scope"} with scope "transcript" or "client"."""
    value = hide_word_ok(value)
    if tx_id is not None:
        tx = store.get_transcript(tx_id)
        if tx is None or tx["client_id"] != client_id:
            raise ImportProblem("Unknown transcript for this client.")
    else:
        client_wide = True
    with store.transaction():
        registry = store.load_registry(client_id)
        known = registry.lookup("PERSON", value)
        mine = next((e for e in registry.entities if e.local and not known and tx_id in e.only
                     and e.forms.get(None) == value), None)
        if known:
            ent = known[0]
            scope = "transcript" if ent.local else "client"
            code = ent.placeholder(known[1])
        elif client_wide:
            if mine is not None and registry.make_client_wide(mine):
                ent = mine
            else:
                ent = registry.add_value("PERSON", value)[0]
                ent.via = ent.via or (tx_id or "")
            scope, code = "client", ent.placeholder()
        else:
            ent = mine or registry.add_local_person(value, new=True)
            if tx_id not in ent.only:
                ent.only.append(tx_id)
            ent.via = ent.via or tx_id
            scope, code = "transcript", ent.placeholder()
        store.save_registry(client_id, registry, tx_id)
    return {"code": code, "scope": scope}


def copy_for_claude(store: Store, client_id: str, tx_id: str, outputs, directions: str = "", ner: NerModel | None = None,
                    settings: Settings | None = None, confirm=(), places=()) -> str:
    """The text the user pastes into claude.ai. Records the copy and the ticked outputs. Refuses until the review is
    done, and when no output is ticked. Directions are scrubbed like a change request. Flagged words in them stop the
    copy (DirectionsFlagged) until each is in `confirm`. Order: intro, ticked outputs, directions, header line,
    transcript."""
    tx = store.get_transcript(tx_id)
    if tx is None or tx["client_id"] != client_id:
        raise ImportProblem("Unknown transcript for this client.")
    if tx["status"] == "draft":
        raise ReviewIncomplete("The review is not finished.")
    slugs = chosen_outputs(outputs)
    blocks = [f"{n}. {slug} ({OUTPUT_NAMES[slug]})\n{output_instruction(store, slug)}" for n, slug in enumerate(slugs, 1)]
    scrubbed, registry = "", None
    if directions.strip():
        if ner is None or settings is None:
            raise ImportProblem("Directions need the scrubber.")
        scrubbed, groups, registry = prepare_directions(store, client_id, directions, ner, settings, tx_id, places)
        wait = open_groups(groups, confirm)
        if wait:
            raise DirectionsFlagged([g.text for g in wait], groups)
    text = (f"{copy_intro(slugs[0], load_settings(store).mcp_enabled)}\n\nOutputs to write:\n\n" + "\n\n".join(blocks) + "\n\n"
            + (f"Specific directions:\n{scrubbed}\n\n" if scrubbed else "")
            + f"{header_line(client_id, tx_id)}\n")
    current, caught = hide_known_now(store, client_id, tx_id, tx["scrubbed_text"])
    stored, text = text + current, text + restore_switched_off(store, client_id, current)
    with store.transaction():           # the copy record, the status and the ticked outputs change together
        if caught:                      # a name hidden after the call was saved is now hidden in the saved call too
            store.update_scrubbed_text(tx_id, current)
            store.audit("transcript_hidden", client_id, tx_id, len(current.encode("utf-8")))
        store.add_message(client_id, "transcript", stored, tx_id)
        if scrubbed:
            store.save_registry(client_id, registry, tx_id)
            store.add_message(client_id, "comment", scrubbed, tx_id)
        store.set_transcript_status(tx_id, "copied")
        store.set_requested_outputs(tx_id, slugs)
        store.set_setting("last_outputs", ",".join(slugs))
        # The directions stay with the call, in scrubbed form, until the user clears the box and copies again.
        store.set_transcript_directions(tx_id, scrubbed, [w for w in confirm if w in scrubbed])
    return text


# ---- outgoing messages ----------------------------------------------------------------------

@dataclass
class Outgoing:
    text: str                    # exactly what gets copied
    scrubbed: str
    groups: list
    registry: Registry
    segments: list


def prepare_message(store: Store, client_id: str, text: str, kind: str, tx_id: str | None, ner: NerModel,
                    settings: Settings, places=()) -> Outgoing:
    if kind not in ("correction", "comment"):
        raise ImportProblem("Choose correction or comment.")
    if not text.strip():
        raise ImportProblem("Type a message first.")
    if len(text) > MAX_PASTE:
        raise ImportProblem(f"The message is over {MAX_PASTE // 1000} KB.")
    text = clean_text(text)
    if kind == "correction" and not tx_id:
        raise ImportProblem("A correction needs the transcript it revises.")
    if tx_id:
        tx = store.get_transcript(tx_id)
        if tx is None or tx["client_id"] != client_id:
            raise ImportProblem("Unknown transcript for this client.")
    registry = store.load_registry(client_id)
    settings = client_settings(store, client_id, settings)
    scope, kept = stored_scope(store, registry, client_id, tx_id)
    res = scrub_typed(text, registry, settings, ner, scope, kept, places, plain=False)
    parts = []
    if tx_id:
        parts.append(header_line(client_id, tx_id))
    body = f"[CORRECTION] {res.text}" if kind == "correction" else res.text
    parts.append(body)
    return Outgoing("\n".join(parts), res.text, _groups(text, res.flags, set()), registry, tag_segments("\n".join(parts)))


def commit_message(store: Store, client_id: str, out: Outgoing, kind: str, tx_id: str | None,
                   output: str | None = None) -> str:
    store.save_registry(client_id, out.registry, tx_id)
    store.add_message(client_id, kind, out.text, tx_id, output=output)
    return out.text


def last_change_output(store: Store, client_id: str, tx_id: str) -> str | None:
    """The output the most recent change request for this call was about, if any."""
    for m in reversed(store.list_messages(client_id)):
        if m["kind"] == "correction" and m["transcript_id"] == tx_id and m.get("output") in OUTPUT_NAMES:
            return m["output"]
    return None


# ---- asking Claude to change one output -----------------------------------------------------

CHANGE_START = ("Revise only the output named below, {name} (output ID {slug}). Keep every placeholder, such as "
                "[PERSON_1] or [EMAIL_1], exactly as written, and never guess the real value. Return the full revised "
                "text, not only the changes.")
CHANGE_TOOL = ("If you have the save_output tool, call it with the client ID, the transcript ID, the output ID {slug} "
               "and the full revised text. If you do not have it, reply")
CHANGE_REPLY = "with the revised text under a line that reads exactly [OUTPUT: {slug}], with nothing else on that line."


def change_intro(name: str, slug: str, connector_on: bool) -> str:
    """The opening of a change request. The save_output tool is mentioned only when the connector is on."""
    start, reply = CHANGE_START.format(name=name, slug=slug), CHANGE_REPLY.format(slug=slug)
    return f"{start} " + (f"{CHANGE_TOOL.format(slug=slug)} {reply}" if connector_on else f"Reply {reply}")


class StaleVersion(ImportProblem):
    """The page was built before another version of this output was saved."""


def prepare_change_request(store: Store, client_id: str, tx_id: str, slug: str, version, request: str, ner: NerModel,
                           settings: Settings, latest=None, places=()) -> Outgoing:
    """The text to copy when the user asks Claude to change one output. The typed request is scrubbed with the
    client's registry like any outgoing message, so a known real value never reaches the clipboard. The parts, in
    order: what to do, the output's standing instructions, the header line, the scrubbed request, the chosen version
    with placeholders, and the scrubbed transcript. latest: the newest version number the page knew when it was built.
    If the output has a newer one now, the request is refused (StaleVersion), so the text never names a version the
    person is not looking at. Nothing is stored here."""
    if not request.strip():
        raise ImportProblem("Describe the change first.")
    if len(request) > MAX_PASTE:
        raise ImportProblem(f"The request is over {MAX_PASTE // 1000} KB.")
    tx = store.get_transcript(tx_id)
    if tx is None or tx["client_id"] != client_id:
        raise ImportProblem("Unknown transcript for this client.")
    if slug not in OUTPUT_NAMES:
        raise ImportProblem("Unknown output.")
    versions = store.list_outputs(tx_id, slug)
    if not versions:
        raise ImportProblem("This output has no version to change yet.")
    if latest not in (None, "") and (type(latest) is not int or latest != versions[-1]["version"]):
        raise StaleVersion(f"This output has changed since the page was loaded (it is now at version "
                           f"{versions[-1]['version']}). Reload the page, then ask again.")
    if version in (None, ""):
        chosen = versions[-1]
    else:
        chosen = next((o for o in versions if type(version) is int and o["version"] == version), None)
        if chosen is None:
            raise ImportProblem("That version does not exist.")
    request = clean_text(request)
    registry = store.load_registry(client_id)
    settings = client_settings(store, client_id, settings)
    scope, kept = stored_scope(store, registry, client_id, tx_id)
    res = scrub_typed(request, registry, settings, ner, scope, kept, places)
    text = "\n\n".join([
        change_intro(OUTPUT_NAMES[slug], slug, load_settings(store).mcp_enabled),
        output_instruction(store, slug),
        header_line(client_id, tx_id),
        f"Change requested:\n{res.text}",
        f"Current text of {OUTPUT_NAMES[slug]}, version {chosen['version']}, with placeholders:\n{placeholder_text(store, client_id, chosen['content'], registry)}",
        f"Transcript:\n{restore_switched_off(store, client_id, hide_known_now(store, client_id, tx_id, tx['scrubbed_text'], registry)[0], registry)}"])
    return Outgoing(text, res.text, _groups(request, res.flags, set()), registry, tag_segments(text))


def short_day(stamp: str) -> str:
    """A stored UTC timestamp as the user's own day and month, such as 3 Nov."""
    try:
        d = datetime.fromisoformat(stamp).astimezone()
    except (TypeError, ValueError):
        return str(stamp)
    return f"{d.day} {d:%b}"


SOURCE_WORDS = {"mcp": "Claude", "import": "Pasted", "edit": "Hand edit", "hide": "Name hidden", "unhide": "Name restored"}


def long_day(stamp: str) -> str:
    """2026-11-02 as 2 Nov 2026. Anything else is shown as it is."""
    try:
        d = date.fromisoformat(str(stamp)[:10])
    except ValueError:
        return str(stamp)
    return f"{d.day} {d:%b %Y}"


# ---- import ---------------------------------------------------------------------------------

@dataclass
class OutputPiece:
    """One output taken from a reply, checked on its own."""
    slug: str
    content: str                 # what would be stored: known real values already replaced by placeholders
    rehydrated: str = ""
    unknown: list = field(default_factory=list)
    unused: list = field(default_factory=list)
    possible_real: list = field(default_factory=list)
    segments: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return OUTPUT_NAMES[self.slug]


@dataclass
class ImportCheck:
    header_client: str | None
    header_tx: str | None
    tx_id: str | None            # the transcript this reply will be saved under, if known
    needs_pick: bool             # no usable header: the user must choose
    problem: str | None
    content: str                 # what would be stored (known real values already replaced by placeholders)
    masked: int                  # how many real values were replaced
    rehydrated: str = ""
    unknown: list = field(default_factory=list)
    unused: list = field(default_factory=list)
    possible_real: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    pieces: list = field(default_factory=list)          # OutputPiece, one per output in the reply
    bad_markers: list = field(default_factory=list)     # [OUTPUT: ...] lines whose name is not a known output
    empty_markers: list = field(default_factory=list)   # known outputs that have a marker and no text
    loose_text: bool = False     # text before the first marker, which is not saved
    needs_output: bool = False   # no markers and no output chosen
    replaced: list = field(default_factory=list)        # (real text, code, times): shown on the check page only, never stored


def mask_known_values(text: str, registry: Registry, keep_plain: set, only=None, found: list | None = None) -> tuple[str, int]:
    """Replace real values the registry knows with their placeholders, so the stored output never holds them.
    only: replace the values of that one entity and leave the rest. A placeholder token already in the text is a code,
    never a real value, so nothing inside one is replaced. found: when a list is given, each replacement is added as
    (the real text, the code it became). That list is for the page that asks, and is never stored."""
    in_token = token_spans(text)
    hits = []
    for sp, (ent, part) in _propagation(text, registry):
        if only is not None and ent is not only:
            continue
        if norm(sp.value) in keep_plain or (part in ("first", "last") and part in keep_plain):
            continue
        if any(sp.start < e and s < sp.end for s, e in in_token):
            continue
        hits.append((sp, ent.placeholder(part)))
    hits.sort(key=lambda h: (h[0].start, -(h[0].end - h[0].start)))
    out, last, n = [], 0, 0
    for sp, ph in hits:
        if sp.start < last:
            continue
        out += [text[last:sp.start], ph]
        last, n = sp.end, n + 1
        if found is not None:
            found.append((text[sp.start:sp.end], ph))
    out.append(text[last:])
    return "".join(out), n


def placeholder_text(store: Store, client_id: str, content: str, registry: Registry | None = None) -> str:
    """Stored output text as it may leave the app as placeholder text (a change request, the raw copy target, the
    edit form). Known real values are masked again with the same masking an import uses, so a word hidden after this
    version was saved never leaves, whichever version it is. The stored file is not rewritten."""
    registry = registry if registry is not None else store.load_registry(client_id)
    keep = _keep_plain(store.get_client(client_id), *keep_flags(store, client_id))
    return mask_known_values(content, registry, keep)[0]


def _keep_plain(client: dict, keep_first_names: bool, keep_last_names: bool = False) -> set:
    keep_plain = {norm(client["first_name"])}
    if keep_first_names:
        keep_plain.add("first")
    if keep_last_names:
        keep_plain.add("last")
    return keep_plain


def keep_flags(store: Store, client_id: str, keep_first_names: bool | None = None) -> tuple[bool, bool]:
    """(first names, last names) that reach Claude as written for this client, so a reply that holds them is not masked
    or warned about. keep_first_names is the caller's global value, used while the client follows the global setting."""
    o = load_client_options(store, client_id)
    if "PERSON" not in o.types:
        return True, True
    first = (load_settings(store).keep_first_names if keep_first_names is None else keep_first_names) \
        if o.first_names == "inherit" else o.first_names == "keep"
    return first, o.last_names == "keep"


def split_markers(text: str) -> tuple[str, list]:
    """The text before the first [OUTPUT: name] line, and [(name as written, section text)] for each marker."""
    found = list(MARKER_RE.finditer(text))
    sections = [(m["slug"].strip().lower(), text[m.end():found[k + 1].start() if k + 1 < len(found) else len(text)].strip("\n"))
                for k, m in enumerate(found)]
    return (text[:found[0].start()] if found else text), sections


def strip_header_lines(text: str) -> str:
    """Remove valid [CLIENT: .. | TX: ..] headers from an output's text and trim blank lines around what is left.
    The header only identifies the reply, so it must never be stored or copied into Clio."""
    def drop(m):
        return "" if CLIENT_ID_RE.match(m["client"]) and TX_ID_RE.match(m["tx"]) else m.group()
    lines = []
    for line in text.split("\n"):
        new = HEADER_RE.sub(drop, line)
        if new != line and not new.strip():
            continue
        lines.append(new.rstrip() if new != line else line)
    out = "\n".join(lines)
    out = re.sub(r"\A(?:[ \t]*\n)+", "", out)
    return re.sub(r"(?:\n[ \t]*)+\Z", "", out)


def check_import(store: Store, client_id: str, text: str, tx_id: str | None, keep_first_names: bool,
                 output: str | None = None, markers: bool = True) -> ImportCheck:
    """Check a reply before it is saved. A reply with [OUTPUT: name] lines is split into one piece per marker. One
    without them is a single piece for `output`. markers=False reads the text as one piece even if it holds markers."""
    if not text.strip():
        raise ImportProblem("Paste Claude's reply first.")
    if len(text.encode("utf-8")) > 200_000:
        raise ImportProblem("The reply is over 200 KB.")
    if output and output not in OUTPUT_NAMES:
        raise ImportProblem("Choose one of the listed outputs.")
    text = clean_text(text)
    client = store.get_client(client_id)
    registry = store.load_registry(client_id)
    header = find_header(text)
    h_client, h_tx = (header["client"], header["tx"]) if header else (None, None)
    chosen, problem, needs_pick = None, None, False
    if header:
        if h_client != client_id:
            problem = f"This reply is for client {h_client}, not {client_id}. Open that client to import it."
        else:
            row = store.get_transcript(h_tx)
            if row is None or row["client_id"] != client_id:
                problem, needs_pick = f"Transcript {h_tx} is not in this client's list. Pick the right one.", True
            else:
                chosen = h_tx
    else:
        needs_pick = True
    if needs_pick and tx_id:
        row = store.get_transcript(tx_id)
        if row and row["client_id"] == client_id:
            chosen, needs_pick, problem = tx_id, False, None
    keep_first_names, keep_last_names = keep_flags(store, client_id, keep_first_names)
    keep_plain = _keep_plain(client, keep_first_names, keep_last_names)
    swaps: list = []
    content, masked = mask_known_values(text.strip("\n"), registry, keep_plain, found=swaps)
    result = rehydrate(content, registry, client["first_name"], keep_first_names, keep_last_names)
    # The header line only identifies the reply: it is not part of what is saved, so it is not part of the preview.
    shown = rehydrate(strip_header_lines(content), registry, client["first_name"], keep_first_names, keep_last_names)
    check = ImportCheck(h_client, h_tx, chosen, needs_pick, problem, content, masked, result.text, result.unknown,
                        result.unused, result.possible_real, rehydrated_segments(shown.text, shown.unknown))
    counts: dict = {}
    for real, code in swaps:
        counts[(real, code)] = counts.get((real, code), 0) + 1
    check.replaced = [(real, code, n) for (real, code), n in counts.items()]

    def piece(slug: str, body: str) -> OutputPiece:
        body = strip_header_lines(body)
        res = rehydrate(body, registry, client["first_name"], keep_first_names, keep_last_names)
        return OutputPiece(slug, body, res.text, res.unknown, res.unused, res.possible_real,
                           rehydrated_segments(res.text, res.unknown))

    loose, sections = split_markers(content) if markers else (content, [])
    if sections:
        check.loose_text = bool(HEADER_RE.sub("", loose).strip())
        for slug, body in sections:
            if slug not in OUTPUT_NAMES:
                check.bad_markers.append(slug[:60])
            elif not strip_header_lines(body).strip():
                check.empty_markers.append(slug)
            else:
                check.pieces.append(piece(slug, body))
        if len({(m["client"], m["tx"]) for m in HEADER_RE.finditer(content)}) > 1:
            check.problem, check.tx_id, check.needs_pick = "The reply names more than one transcript.", None, True
    elif output:
        if strip_header_lines(content).strip():
            check.pieces.append(piece(output, content))
        else:
            check.empty_markers.append(output)
    else:
        check.needs_output = True
    return check


def rehydrated_segments(text: str, unknown) -> list:
    """Pieces of rehydrated text; unknown placeholders are marked so the page can highlight them."""
    if not unknown:
        return [(text, None)]
    pat = re.compile("|".join(re.escape(u) for u in sorted(set(unknown), key=len, reverse=True)))
    out, last = [], 0
    for m in pat.finditer(text):
        out += [(text[last:m.start()], None), (m.group(), "UNKNOWN")]
        last = m.end()
    out.append((text[last:], None))
    return [(t, ty) for t, ty in out if t]


def save_import(store: Store, client_id: str, check: ImportCheck, kind: str = "output", source: str = "import") -> str:
    """Save a checked reply. Every output in it becomes a new version in one transaction, or none does."""
    if check.problem and not check.tx_id and not (kind == "summary" and check.header_client in (None, client_id)):
        raise ImportProblem(check.problem)
    if kind == "summary":
        content = strip_header_lines(check.content)       # the header only identifies the reply, as with outputs
        if not content.strip():
            raise ImportProblem("The summary is empty.")
        store.add_message(client_id, "summary", content, None, copied=False)
        store.audit("summary_imported", client_id, None, len(content.encode("utf-8")))
        return "summary"
    if not check.tx_id:
        raise ImportProblem("Pick the transcript this reply belongs to.")
    if check.bad_markers:
        raise ImportProblem("These output names are not known: " + ", ".join(check.bad_markers) + ". Nothing was saved.")
    if check.empty_markers:
        raise ImportProblem("These outputs have no text: " + ", ".join(check.empty_markers) + ". Nothing was saved.")
    if not check.pieces:
        raise ImportProblem("Choose which output this reply is.")
    with store.transaction():
        saved = [f"{p.slug} v{store.add_output(client_id, check.tx_id, p.slug, p.content, source)}" for p in check.pieces]
    return ", ".join(saved)


def edit_output(store: Store, client_id: str, tx_id: str, slug: str, text: str, keep_first_names: bool) -> tuple[int, int]:
    """Save a hand edit of an output as a new version. The text is placeholder text, and known real values typed into
    it are replaced like in an import. Returns (version, how many values were replaced)."""
    row = store.get_transcript(tx_id)
    if row is None or row["client_id"] != client_id or slug not in OUTPUT_NAMES:
        raise ImportProblem("Unknown output for this transcript.")
    text = strip_header_lines(clean_text(text).strip("\n"))
    if not text.strip():
        raise ImportProblem("The output is empty.")
    if len(text.encode("utf-8")) > 200_000:
        raise ImportProblem("The output is over 200 KB.")
    content, masked = mask_known_values(text, store.load_registry(client_id),
                                        _keep_plain(store.get_client(client_id), *keep_flags(store, client_id, keep_first_names)))
    with store.transaction():
        versions = store.list_outputs(tx_id, slug)
        if versions and versions[-1]["content"] == content:
            raise ImportProblem("Nothing changed, so no new version was saved.")
        return store.add_output(client_id, tx_id, slug, content, "edit"), masked


MAX_HIDE = 200


@dataclass
class HideResult:
    places: int            # places changed in the transcript
    outputs: int           # outputs that got a new version with the text masked
    seen: bool             # Claude already received this call, so what it holds cannot be changed here


def claude_has_seen(store: Store, tx: dict) -> bool:
    """The call was copied for Claude, or an output exists, so Claude has the text as it was."""
    return tx["status"] == "copied" or any(store.list_outputs(tx["id"], slug) for slug in OUTPUT_SLUGS)


def delete_transcript(store: Store, client_id: str, tx_id: str) -> bool:
    """Delete one call with its outputs and the messages copied for it. Names hidden for this call only go too, unless
    another call of the client still uses them. Names hidden for the whole client stay. There is no undo."""
    tx = store.get_transcript(tx_id)
    if tx is None or tx["client_id"] != client_id:
        return False
    with store.transaction():
        registry = store.load_registry(client_id)
        others = [store.get_transcript(t["id"]) for t in store.list_transcripts(client_id) if t["id"] != tx_id]
        changed = False
        for ent in local_names(registry, tx["scrubbed_text"], tx_id):
            still = [o["id"] for o in others if o and (tx_id != o["id"]) and ((o["id"] in ent.only) or any(
                int(m["n"]) == ent.n and m["type"].upper() == "PERSON" for m in PLACEHOLDER_RE.finditer(o["scrubbed_text"])))]
            if still:
                ent.only = [t for t in ent.only if t != tx_id]
            else:
                registry.remove(ent)
            changed = True
        if changed:
            store.save_registry(client_id, registry)
        return store.delete_transcript(client_id, tx_id)


def _put_back(text: str, registry: Registry, ent) -> tuple[str, int]:
    """The text with every code that resolves to this entry replaced by its real words. Codes of other entries, and
    codes with no known value, stay as written."""
    count = 0

    def swap(m):
        nonlocal count
        found = registry.entity(m["type"].upper(), int(m["n"]))
        value = registry.surface(found, m["part"].lower() if m["part"] else None) if found is ent else None
        if value is None:
            return m.group()
        count += 1
        return value

    return PLACEHOLDER_RE.sub(swap, text), count


def delete_hidden_name(store: Store, client_id: str, type_: str, n: int) -> int:
    """Delete a hidden name and put its real words back where its codes stand. Every saved call of the client gets its
    text back, and an output that holds the code gets a new version with the words restored (source "unhide"), so
    history stays. Without this the code would stay in the saved text for good with nothing to turn it back into the
    name. Returns the number of places restored. One transaction, in the usual save order: client.json, then the texts."""
    with store.transaction():
        registry = store.load_registry(client_id)
        ent = find_entity(registry, type_, n)
        texts, outputs, places = [], [], 0
        for row in store.list_transcripts(client_id):
            tx = store.get_transcript(row["id"])
            if tx is None:
                continue
            text, count = _put_back(tx["scrubbed_text"], registry, ent)
            if count:
                texts.append((tx["id"], text))
                places += count
            for slug in OUTPUT_SLUGS:
                versions = store.list_outputs(tx["id"], slug)
                if versions:
                    content, found = _put_back(versions[-1]["content"], registry, ent)
                    if found:
                        outputs.append((tx["id"], slug, content))
        registry.remove(ent)
        store.save_registry(client_id, registry)
        for tx_id, text in texts:
            store.update_scrubbed_text(tx_id, text)
        for tx_id, slug, content in outputs:
            store.add_output(client_id, tx_id, slug, content, "unhide")
        store.audit("registry_delete", client_id, None, places)
    return places


def hide_in_transcript(store: Store, client_id: str, tx_id: str, type_: str, value: str,
                       allow_absent: bool = False) -> HideResult:
    """Hide a word in a saved call. The value joins the client's registry, every whole-word place in the transcript
    becomes its placeholder, and an output that holds it gets a new version with it masked (source edit), so history
    stays and the new copy is safe. One transaction, in the usual save order: client.json, then the text and outputs.
    Refuses empty text, long text and text that overlaps a placeholder. allow_absent: still remember the value when the
    transcript and its outputs do not hold it, as when a typed request holds a name the call never mentioned."""
    if type_ not in ALL_TYPES:
        raise ImportProblem("Choose Person, Email or Address.")
    value = " ".join(clean_text(value).split())
    if not value:
        raise ImportProblem("Select or type the text to hide.")
    if len(value) > MAX_HIDE:
        raise ImportProblem(f"That text is over {MAX_HIDE} characters. Hide one name, email or address at a time.")
    if "[" in value or "]" in value:
        raise ImportProblem("That text overlaps a hidden name. Select the text outside the brackets.")
    with store.transaction():
        tx = store.get_transcript(tx_id)
        if tx is None or tx["client_id"] != client_id:
            raise ImportProblem("Unknown transcript for this client.")
        text = tx["scrubbed_text"]
        low = value.casefold()
        if any(low in m.group().casefold() for m in PLACEHOLDER_RE.finditer(text)):
            raise ImportProblem("That text overlaps a hidden name. Select a different piece of the line.")
        registry = store.load_registry(client_id)
        ent = registry.add_value(type_, value)[0]
        masked, places = mask_known_values(text, registry, set(), only=ent)
        updates = []
        for slug in OUTPUT_SLUGS:
            versions = store.list_outputs(tx_id, slug)
            if versions:
                content, n = mask_known_values(versions[-1]["content"], registry, set(), only=ent)
                if n:
                    updates.append((slug, content))
        if not places and not updates and not allow_absent:
            raise ImportProblem("That text is not in this transcript or its outputs, so nothing was changed.")
        seen = claude_has_seen(store, tx)
        store.save_registry(client_id, registry, tx_id)
        if places:
            store.update_scrubbed_text(tx_id, masked)
        for slug, content in updates:
            store.add_output(client_id, tx_id, slug, content, "hide")
        store.audit("transcript_hidden", client_id, tx_id, len(masked.encode("utf-8")))
    return HideResult(places, len(updates), seen)


def view_output(store: Store, client_id: str, content: str):
    client = store.get_client(client_id)
    registry = store.load_registry(client_id)
    res = rehydrate(content, registry, client["first_name"], *keep_flags(store, client_id))
    return res, rehydrated_segments(res.text, res.unknown)


_TOKEN_RE = re.compile(r"\s+|[^\s]+")


def _bare(token: str) -> str:
    """A word without its punctuation, so "Friday," and "Friday" count as the same word when comparing."""
    return re.sub(r"[^\w]+", "", token)


def _word_marks(old: str, new: str) -> tuple[list, list]:
    """Two lines as [(text, changed)] pieces, with the words that differ marked, from difflib on words. A difference in
    punctuation alone (a comma, a full stop, a dash) is not marked."""
    a, b = _TOKEN_RE.findall(old), _TOKEN_RE.findall(new)
    left, right = [], []

    def piece(tokens, changed):
        return ("".join(tokens), changed)

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            left.append(piece(a[i1:i2], False))
            right.append(piece(b[j1:j2], False))
            continue
        x, y = a[i1:i2], b[j1:j2]
        words_x, words_y = [t for t in x if _bare(t)], [t for t in y if _bare(t)]
        if [_bare(t) for t in words_x] == [_bare(t) for t in words_y]:      # only punctuation or spacing differs
            left.append(piece(x, False))
            right.append(piece(y, False))
            continue
        if x:
            left.append(piece(x, True))
        if y:
            right.append(piece(y, True))
    return left, right


def diff_rows(old: str, new: str) -> list:
    """[(kind, [(text, changed)])] with kind in same / add / del. Lines that were changed rather than replaced are
    paired, and only the words that differ are marked, so a one-word edit does not light up the whole paragraph. The
    page prints every piece as escaped text."""
    a, b = old.splitlines(), new.splitlines()
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out += [("same", [(line, False)]) for line in a[i1:i2]]
        elif tag == "delete":
            out += [("del", [(line, True)]) for line in a[i1:i2]]
        elif tag == "insert":
            out += [("add", [(line, True)]) for line in b[j1:j2]]
        else:
            dels, adds = [], []
            for k in range(max(i2 - i1, j2 - j1)):
                x = a[i1 + k] if i1 + k < i2 else None
                y = b[j1 + k] if j1 + k < j2 else None
                if x is not None and y is not None and difflib.SequenceMatcher(None, x, y, autojunk=False).ratio() >= 0.4:
                    left, right = _word_marks(x, y)
                    dels.append(("del", left))
                    adds.append(("add", right))
                else:
                    if x is not None:
                        dels.append(("del", [(x, True)]))
                    if y is not None:
                        adds.append(("add", [(y, True)]))
            out += dels + adds
    return out


def diff_lines(old: str, new: str) -> list:
    """[(kind, line)] with kind in same / add / del, for the version comparison."""
    out = []
    for line in difflib.ndiff(old.splitlines(), new.splitlines()):
        if line.startswith("? "):
            continue
        out.append(({"+": "add", "-": "del"}.get(line[0], "same"), line[2:]))
    return out


# ---- registry editor ------------------------------------------------------------------------

def transcript_name(tx: dict) -> str:
    """How a call is named on screen: its title, else its date such as 3 Nov 2026."""
    return tx.get("title") or long_day(tx["call_date"])


def registry_rows(registry: Registry, transcripts=()) -> list:
    """One row per hidden name. A name hidden in one transcript only says which one ("Only in <title or date>"), found
    by the code that transcript's text holds or by the transcript it was hidden for. A name added from a message or
    directions says where ("Added from a message on <title or date>")."""
    named = {t["id"]: transcript_name(t) for t in transcripts}
    rows = []
    for e in sorted(registry.entities, key=lambda e: (e.type, e.n)):
        forms = [(part or "full", e.placeholder(part), value) for part, value in e.forms.items() if value]
        forms.sort(key=lambda f: ("full", "first", "last", "nick").index(f[0]) if f[0] in ("full", "first", "last", "nick") else 9)
        rows.append({"type": e.type, "n": e.n, "placeholder": e.placeholder(), "forms": forms,
                     "aliases": list(e.aliases), "merged_into": e.merged_into, "office": e.office, "local": e.local,
                     "lead": forms[0][2] if forms else "", "is_code": any(has_token(v) for _, _, v in forms),
                     "only_in": ("Only in " + (", ".join(transcript_name(t) for t in transcripts
                                                         if e in local_names(registry, t["scrubbed_text"], t["id"])) or "one transcript"))
                     if e.local else "",
                     "added_from": f"Added from a message on {named[e.via]}" if e.via in named and not e.local else ""})
    return rows


def save_entity_forms(registry: Registry, ent, values: dict, office: bool | None = None) -> None:
    """Apply the edited forms of one hidden name together. values: part ('full', 'first', 'last', 'nick') -> text.
    Only a form the entry already has is changed, and only when the text differs. Raises ValueError on an empty value
    or one that belongs to another entry, before anything is saved. office: mark or unmark a person as office staff."""
    for part, value in values.items():
        key = None if part == "full" else part
        if key not in ent.forms:
            continue
        value = " ".join(clean_text(str(value)).split())
        if value != ent.forms[key]:
            registry.set_form(ent, key, value)
    if office is not None and ent.type == "PERSON":
        ent.office = bool(office)


def directions_for_display(registry: Registry, scrubbed: str, local=()) -> str:
    """Saved directions (stored with codes) as they are shown in the box, with real names, because Copy for Claude
    scrubs whatever the box holds. A code is restored only when the same name would be hidden as the same code again;
    anything else stays a code, which scrubbing leaves alone. local: names hidden in this transcript only, shown as
    their words too because typed text about this transcript hides them again. Display only, never stored or sent."""
    def swap(m):
        ent = registry.entity(m["type"].upper(), int(m["n"]))
        part = m["part"].lower() if m["part"] else None
        value = registry.surface(ent, part) if ent else None
        if value and ent is not None and ent.local and ent in local and part is None and not has_token(value):
            return value
        if not value or ent.local or has_token(value):
            return m.group()
        hit = registry.lookup(ent.type, value)
        return value if hit and hit[0] is ent and hit[1] == part else m.group()
    return PLACEHOLDER_RE.sub(swap, scrubbed or "")


def hidden_name_code(registry: Registry, value: str) -> str:
    """The code a hidden person is written as in text for Claude, such as [PERSON_3]. Empty when not hidden."""
    hit = registry.lookup("PERSON", value)
    return hit[0].placeholder(hit[1]) if hit else ""


def find_entity(registry: Registry, type_: str, n: int):
    for e in registry.entities:
        if e.type == type_ and e.n == n:
            return e
    raise ImportProblem("That entry does not exist.")


# ---- export ---------------------------------------------------------------------------------

def export_markdown(store: Store, client_id: str) -> str:
    """The client's history with real values restored. Handed to the browser as a download, never stored."""
    client = store.get_client(client_id)
    registry = store.load_registry(client_id)
    keep = load_settings(store).keep_first_names
    lines = [f"# {client_full_name(client['first_name'], registry)} ({client_id})", ""]
    for tx in reversed(store.list_transcripts(client_id)):
        lines += [f"## {tx['id']} ({tx['call_date']})", "", "### Transcript", "",
                  rehydrate(tx["scrubbed_text"], registry, client["first_name"], keep).text, ""]
        for slug, name in OUTPUTS:
            for out in store.list_outputs(tx["id"], slug):
                label = out["created_at"] + (f", {SOURCE_WORDS[out['source']].lower()}" if out["source"] in ("hide", "unhide") else "")
                lines += [f"### {name} v{out['version']} ({label})", "",
                          rehydrate(out["content"], registry, client["first_name"], keep).text, ""]
    summaries = [m for m in store.list_messages(client_id) if m["kind"] == "summary"]
    if summaries:
        lines += ["## Summaries", ""]
        for m in summaries:
            lines += [rehydrate(m["scrubbed_text"], registry, client["first_name"], keep).text, ""]
    return "\n".join(lines)


def valid_ids(client_id: str, tx_id: str | None = None) -> bool:
    return bool(CLIENT_ID_RE.match(client_id)) and (tx_id is None or bool(TX_ID_RE.match(tx_id)))
