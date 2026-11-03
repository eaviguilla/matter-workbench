"""Per-client placeholder registry.

The same real value always maps to the same placeholder for a client. A person has one
entity number and up to three forms: the full name, the first name and the last name,
rendered as [PERSON_2], [PERSON_2.first] and [PERSON_2.last].
"""
import re
from dataclasses import dataclass, field


# A placeholder token as written in text for Claude: [PERSON_1], [EMAIL_2], [PERSON_3.first]. A token is a code, never a
# name, so nothing here may take one as a real value.
PLACEHOLDER_RE = re.compile(
    r"\[\s*(?P<type>[A-Za-z]+)\s*_\s*(?P<n>\d+)(?:\s*\.\s*(?P<part>first|last|nick|rest))?\s*\]", re.I)


class PlaceholderValue(ValueError):
    """The value is, or contains, a placeholder token such as [PERSON_1]."""


def has_token(value: str) -> bool:
    return bool(PLACEHOLDER_RE.search(value or ""))


def token_spans(text: str) -> list:
    """(start, end) of every placeholder token in the text."""
    return [(m.start(), m.end()) for m in PLACEHOLDER_RE.finditer(text)]


def _no_token(value: str) -> None:
    if has_token(value):
        raise PlaceholderValue("That is a hidden-name code, not a real name or value, so it cannot be added.")


def norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def canonical_email(value: str) -> str:
    return "".join(value.split()).casefold()


_SUFFIX = re.compile(r"[ ]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Way|Place|Pl|"
                     r"Terrace|Circle|Highway|Hwy|Parkway|Pkwy|Trail)$")


def address_street(value: str) -> str:
    """'1450 Bluebonnet Trail, Unit 9, Austin, TX' -> '1450 Bluebonnet Trail'."""
    return " ".join(value.split(",")[0].split())


def address_short(value: str) -> str:
    """'1450 Bluebonnet Trail' -> '1450 Bluebonnet' (how people say it the second time)."""
    return _SUFFIX.sub("", address_street(value))


@dataclass
class Entity:
    type: str
    n: int
    forms: dict = field(default_factory=dict)      # part (None/'first'/'last') -> surface form
    aliases: list = field(default_factory=list)    # extra literal forms (non-person types)
    surname_only: bool = False                     # a lone name seen after a title: a surname, never a first name
    merged_into: int | None = None                 # n of the entity this duplicate was merged into (same type)
    local: bool = False                            # hides chosen places only; never matched in new text
    office: bool = False                           # office staff: the person who answers the calls, never the client
    only: list = field(default_factory=list)       # transcripts a local entity was hidden for from a typed box (no code in their text)
    via: str = ""                                  # the transcript whose typed message or directions added this entry

    def placeholder(self, part: str | None = None) -> str:
        return f"[{self.type}_{self.n}{'.' + part if part else ''}]"


@dataclass(frozen=True)
class Form:
    surface: str
    entity: Entity
    part: str | None
    case_sensitive: bool


class Registry:
    def __init__(self):
        self.entities: list[Entity] = []
        self._index: dict = {}                 # (type, norm key) -> (Entity, part)
        self.collisions: list[str] = []        # surfaces that already belonged to another entity
        self.high: dict = {}                   # type -> highest number ever issued, so a deleted number is never reused

    def _new(self, type_: str) -> Entity:
        n = 1 + max(self.high.get(type_, 0), *(e.n for e in self.entities if e.type == type_), 0)
        ent = Entity(type_, n)
        self.entities.append(ent)
        return ent

    def _bind(self, type_: str, key: str, ent: Entity, part):
        k = (type_, key)
        if k in self._index:
            if self._index[k][0] is not ent:
                self.collisions.append(key)
            return
        self._index[k] = (ent, part)

    def lookup(self, type_: str, value: str):
        key = canonical_email(value) if type_ == "EMAIL" else norm(value)
        return self._index.get((type_, key))

    def add_person(self, name: str):
        _no_token(name)
        hit = self.lookup("PERSON", name)
        if hit:
            return hit
        tokens = name.split()
        ent = self._new("PERSON")
        ent.forms[None] = " ".join(tokens)
        self._bind("PERSON", norm(name), ent, None)
        if len(tokens) >= 2:
            ent.forms["first"], ent.forms["last"] = tokens[0], tokens[-1]
            self._bind("PERSON", norm(tokens[0]), ent, "first")
            self._bind("PERSON", norm(tokens[-1]), ent, "last")
        return ent, None

    def add_local_person(self, name: str, new: bool = False) -> Entity:
        """An entity for places the reviewer chose one by one. It gets a placeholder that restores, but it is not
        bound to any surface, so a later transcript does not hide that word everywhere. One is reused for the same
        word. new: always make a separate entry (a word hidden from a typed box is its own entry, tied to one
        transcript, and must never take over the one made by Choose each place)."""
        _no_token(name)
        name = " ".join(name.split())
        for e in self.entities:
            if not new and e.local and e.type == "PERSON" and e.merged_into is None and not e.only and e.forms.get(None) == name:
                return e
        ent = self._new("PERSON")
        ent.forms[None] = name
        ent.local = True
        return ent

    def make_client_wide(self, ent: Entity) -> bool:
        """A word hidden for one transcript only becomes a hidden name for the whole client. False when another entry
        already owns the word (that one then applies, and this one stays as it is)."""
        word = ent.forms.get(None)
        if not ent.local or not word or self.lookup(ent.type, word):
            return False
        ent.local, ent.only = False, []
        self._bind(ent.type, norm(word), ent, None)
        return True

    def add_nickname(self, ent: Entity, nickname: str):
        """Link a nickname to an existing person so both share one entity number."""
        _no_token(nickname)
        hit = self.lookup("PERSON", nickname)
        if hit:
            return hit
        ent.forms["nick"] = nickname
        self._bind("PERSON", norm(nickname), ent, "nick")
        return ent, "nick"

    def add_surname(self, ent: Entity, surname: str) -> bool:
        """A known single-name person is seen with a surname. Keep the bare name's placeholder
        stable and add [PERSON_n.last], so earlier chat content stays valid."""
        _no_token(surname)
        if "last" in ent.forms:
            return False
        hit = self.lookup("PERSON", surname)
        if hit and (hit[0] is ent or set(hit[0].forms) != {None}):
            return False
        ent.forms["last"] = surname
        self._index[("PERSON", norm(surname))] = (ent, "last")   # may take over a lone surname entity
        return True

    def link_nickname(self, ent: Entity, short: Entity) -> None:
        """"Jess" is a shorter form of "Jessica": the short entity's name becomes ent's .nick. The old
        entity stays in the list, so placeholders already used in earlier chat text still restore."""
        if "nick" in ent.forms or short is ent:
            return
        ent.forms["nick"] = short.forms[None]
        self._index[("PERSON", norm(short.forms[None]))] = (ent, "nick")

    def shorter_forms_of(self, name: str):
        """Entities whose lone name is a proper prefix of this first name (Jess of Jessica)."""
        n = norm(name)
        return [e for e in self.entities if e.type == "PERSON" and e.merged_into is None and not e.local and set(e.forms) == {None}
                and len(norm(e.forms[None])) >= 3 and len(n) >= len(norm(e.forms[None])) + 2
                and n.startswith(norm(e.forms[None]))]

    def longer_entity_for(self, short: str):
        """An entity whose first name starts with this short name (Jessica for Jess), or None."""
        n = norm(short)
        if len(n) < 3:
            return None
        for e in self.entities:
            first = e.forms.get("first") or (e.forms[None] if set(e.forms) == {None} else None)
            if e.type == "PERSON" and e.merged_into is None and not e.local and first and len(norm(first)) >= len(n) + 2 and norm(first).startswith(n) \
                    and "nick" not in e.forms:
                return e
        return None

    def add_firstname(self, ent: Entity, first: str) -> bool:
        """A known lone surname is seen with a first name. [PERSON_n] keeps meaning the surname."""
        _no_token(first)
        if "first" in ent.forms or self.lookup("PERSON", first):
            return False
        ent.forms["first"] = first
        self._bind("PERSON", norm(first), ent, "first")
        return True

    def add_value(self, type_: str, value: str):
        _no_token(value)
        if type_ == "PERSON":
            return self.add_person(value)
        hit = self.lookup(type_, value) or (type_ == "ADDRESS" and self.lookup(type_, address_street(value)))
        if hit:
            return hit
        ent = self._new(type_)
        surface = " ".join(value.split())
        if type_ == "ADDRESS":      # the street alone, and the short spoken form, resolve to the same entity
            for alias in (address_street(value), address_short(value)):
                if len(alias.split()) >= 2 and norm(alias) != norm(surface) and alias not in ent.aliases:
                    ent.aliases.append(alias)
                    self._bind(type_, norm(alias), ent, None)
        ent.forms[None] = surface
        self._bind(type_, canonical_email(value) if type_ == "EMAIL" else norm(value), ent, None)
        if type_ == "EMAIL":
            ent.aliases.append(canonical_email(value))
        return ent, None

    def entity(self, type_: str, n: int) -> Entity | None:
        """The entity for a placeholder. A merged duplicate resolves to the entity it was merged into."""
        for e in self.entities:
            if e.type == type_ and e.n == n:
                return self.entity(type_, e.merged_into) if e.merged_into is not None else e
        return None

    # edits made by the user in the registry editor; they apply to new text only

    def _unbind(self, ent: Entity, part=...):
        for k in [k for k, (e, p) in self._index.items() if e is ent and (part is ... or p == part)]:
            del self._index[k]

    def set_form(self, ent: Entity, part: str | None, value: str) -> None:
        """Fix the stored value of one form. Old chat text keeps its placeholders and now restores the fixed value."""
        value = " ".join(value.split())
        if not value:
            raise ValueError("a value cannot be empty")
        _no_token(value)
        if ent.type == "PERSON":
            clash = self._index.get(("PERSON", norm(value)))
            if clash and clash[0] is not ent:
                raise ValueError(f"{value!r} already belongs to {clash[0].placeholder(clash[1])}")
            self._unbind(ent, part)
            ent.forms[part] = value
            self._index[("PERSON", norm(value))] = (ent, part)
            return
        clash = self.lookup(ent.type, value)
        if clash and clash[0] is not ent:
            raise ValueError(f"{value!r} already belongs to {clash[0].placeholder()}")
        self._unbind(ent)
        ent.forms[None] = value
        ent.aliases = []
        self._index[(ent.type, canonical_email(value) if ent.type == "EMAIL" else norm(value))] = (ent, None)
        if ent.type == "EMAIL":
            ent.aliases.append(canonical_email(value))
        if ent.type == "ADDRESS":
            for alias in (address_street(value), address_short(value)):
                if len(alias.split()) >= 2 and norm(alias) != norm(value) and alias not in ent.aliases:
                    ent.aliases.append(alias)
                    self._index.setdefault((ent.type, norm(alias)), (ent, None))

    def merge(self, keep: Entity, dup: Entity) -> None:
        """dup is the same thing as keep. New text with dup's spellings gets keep's placeholder, and old
        placeholders of dup restore keep's values."""
        if keep is dup or keep.type != dup.type or keep.merged_into is not None or dup.merged_into is not None:
            raise ValueError("cannot merge these entries")
        spellings = {dup.forms[None], *dup.aliases}
        for part, value in dup.forms.items():
            if part is not None and part not in keep.forms and keep.type == "PERSON":
                keep.forms[part] = value                       # keep learns a first or last name it lacked
                spellings.discard(value)
                self._unbind(dup, part)
                self._index[("PERSON", norm(value))] = (keep, part)
            elif part is not None:
                spellings.add(value)
        self._unbind(dup)
        spellings = {sp for sp in spellings if not has_token(sp)}
        for spelling in sorted(spellings):
            if ("PERSON" if keep.type == "PERSON" else keep.type, norm(spelling)) not in self._index \
                    and norm(spelling) != norm(keep.forms[None]) and spelling not in keep.aliases:
                keep.aliases.append(spelling)
                key = canonical_email(spelling) if keep.type == "EMAIL" else norm(spelling)
                self._index[(keep.type, key)] = (keep, None)
        dup.merged_into = keep.n
        dup.aliases = []

    def remove(self, ent: Entity) -> None:
        """Delete an entry. Placeholders already used in earlier chat text become unknown."""
        self._unbind(ent)
        self.entities.remove(ent)
        self.high[ent.type] = max(self.high.get(ent.type, 0), ent.n)      # old chat text must never resolve to a new person
        for e in self.entities:
            if e.merged_into == ent.n and e.type == ent.type:
                e.merged_into = None

    def surface(self, ent: Entity, part: str | None) -> str | None:
        if part == "rest":          # everything after the first word of the full name, worked out when asked
            words = (ent.forms.get(None) or "").split()
            return " ".join(words[1:]) if len(words) > 1 else None
        if part == "first" and "first" not in ent.forms:      # the first word of a full name that has no first form
            words = (ent.forms.get(None) or "").split()
            return words[0] if len(words) > 1 else None
        return ent.forms.get(part)

    def iter_forms(self):
        """Every literal form to look for in new text. Names are case-sensitive."""
        for (type_, _), (ent, part) in self._index.items():
            surface = ent.forms.get(part) if type_ == "PERSON" else ent.forms.get(None)
            if not surface or has_token(surface):        # a code saved by mistake in an older version is never a value
                continue
            if type_ == "PERSON":
                yield Form(surface, ent, part, True)
            else:
                yield Form(surface, ent, None, False)
        for ent in self.entities:
            for alias in ent.aliases:
                if alias != norm(ent.forms[None]) and not has_token(alias):
                    yield Form(alias, ent, None, False)

    def code_entries(self) -> list:
        """Entities that hold a placeholder token as a value: damage from an older version, which hid a code as if
        it were a name. Returns (entity, forms) where forms are the parts (None for full) and aliases holding a code."""
        found = []
        for e in self.entities:
            bad = [p for p, v in e.forms.items() if has_token(v)]
            bad_alias = [a for a in e.aliases if has_token(a)]
            if bad or bad_alias:
                found.append((e, bad, bad_alias))
        return found

    def strip_codes(self) -> tuple[int, int]:
        """Remove what code_entries finds and nothing else. An entry whose full form is a code is removed (its number is
        never reused). Any other form or alias that is a code is dropped from an entry that has a real full form.
        Returns (entries removed, forms removed)."""
        removed = forms = 0
        for e, bad, bad_alias in self.code_entries():
            if None in bad or None not in e.forms:
                self.remove(e)
                removed += 1
                continue
            for p in bad:
                self._unbind(e, p)
                del e.forms[p]
                forms += 1
            e.aliases = [a for a in e.aliases if a not in bad_alias]
            forms += len(bad_alias)
        return removed, forms

    def to_dict(self) -> dict:
        return {"entities": [{"type": e.type, "n": e.n, "forms": {k or "full": v for k, v in e.forms.items()},
                              "aliases": e.aliases, "surname_only": e.surname_only, "merged_into": e.merged_into,
                              **({"local": True} if e.local else {}), **({"office": True} if e.office else {}),
                              **({"only": list(e.only)} if e.only else {}), **({"via": e.via} if e.via else {})}
                             for e in self.entities],
                "index": [[t, k, e.n, p] for (t, k), (e, p) in self._index.items()],
                "high": dict(self.high)}

    @classmethod
    def from_dict(cls, data: dict) -> "Registry":
        reg = cls()
        for d in data["entities"]:
            reg.entities.append(Entity(d["type"], d["n"], {(None if k == "full" else k): v
                                                           for k, v in d["forms"].items()}, list(d["aliases"]),
                                   d.get("surname_only", False), d.get("merged_into"), bool(d.get("local", False)),
                                   bool(d.get("office", False)), [str(t) for t in d.get("only", [])], str(d.get("via", ""))))
        for t, k, n, p in data["index"]:
            reg._index[(t, k)] = (reg.entity(t, n), p)
        reg.high = {t: int(n) for t, n in data.get("high", {}).items()}
        return reg
