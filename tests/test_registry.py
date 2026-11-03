import pytest


from app.scrub.registry import Registry


def test_person_variants_share_one_entity():
    r = Registry()
    ent, part = r.add_person("Maria Lopez")
    assert part is None and ent.placeholder() == "[PERSON_1]"
    assert r.lookup("PERSON", "maria") == (ent, "first")
    assert r.lookup("PERSON", "LOPEZ") == (ent, "last")
    assert ent.placeholder("first") == "[PERSON_1.first]"


def test_lookup_is_case_and_whitespace_insensitive_but_keeps_surface():
    r = Registry()
    r.add_person("Maria  Lopez")
    ent, _ = r.add_person("MARIA LOPEZ")
    assert ent.n == 1 and len(r.entities) == 1
    assert ent.forms[None] == "Maria Lopez"


def test_emails_share_a_key_across_case():
    r = Registry()
    a, _ = r.add_value("EMAIL", "Maria.Lopez@Gmail.com")
    b, _ = r.add_value("EMAIL", "maria.lopez@gmail.com")
    assert a is b


def test_numbering_is_per_type():
    r = Registry()
    r.add_person("A One")
    r.add_value("EMAIL", "x@y.com")
    r.add_person("B Two")
    assert [e.placeholder() for e in r.entities] == ["[PERSON_1]", "[EMAIL_1]", "[PERSON_2]"]


def test_save_and_load_keeps_numbers_stable():
    r = Registry()
    r.add_person("Maria Lopez")
    r.add_value("EMAIL", "m@x.com")
    r2 = Registry.from_dict(r.to_dict())
    assert r2.add_person("Maria Lopez")[0].placeholder() == "[PERSON_1]"
    assert r2.add_person("Sam Whitaker")[0].placeholder() == "[PERSON_2]"
    assert r2.lookup("EMAIL", "M@X.com")[0].placeholder() == "[EMAIL_1]"


def test_surname_added_later_keeps_bare_placeholder():
    r = Registry()
    ent, _ = r.add_person("Denise")
    assert r.add_surname(ent, "Park")
    assert r.lookup("PERSON", "Denise") == (ent, None)
    assert r.lookup("PERSON", "Park") == (ent, "last")


def test_merge_sends_old_placeholders_and_new_spellings_to_the_kept_entity():
    from app.scrub.registry import Registry
    r = Registry()
    keep, _ = r.add_person("Maria Lopez")
    dup, _ = r.add_person("Mariah Lopes")
    r.merge(keep, dup)
    assert r.entity("PERSON", dup.n) is keep                  # old [PERSON_2] restores Maria Lopez
    assert r.lookup("PERSON", "Mariah Lopes")[0] is keep      # new text with the typo joins [PERSON_1]
    assert {f.surface for f in r.iter_forms() if f.entity is keep} >= {"Maria Lopez", "Mariah Lopes"}
    again = Registry.from_dict(r.to_dict())
    assert again.to_dict() == r.to_dict() and again.entity("PERSON", dup.n).n == keep.n


def test_set_form_and_remove_keep_numbering_stable():
    from app.scrub.registry import Registry
    r = Registry()
    a, _ = r.add_person("Maria Lopez")
    b, _ = r.add_person("Kevin Walters")
    r.set_form(a, None, "Maria Lopez-Diaz")
    assert r.lookup("PERSON", "Maria Lopez-Diaz")[0] is a and r.lookup("PERSON", "Maria Lopez") is None
    with pytest.raises(ValueError):
        r.set_form(a, "first", "Kevin")
    e, _ = r.add_value("EMAIL", "old@x.com")
    r.set_form(e, None, "new@x.com")
    assert r.lookup("EMAIL", "NEW@x.com")[0] is e and r.lookup("EMAIL", "old@x.com") is None
    r.remove(a)
    c, _ = r.add_person("Dana Fox")
    assert (b.n, c.n) == (2, 3) and r.lookup("PERSON", "Maria") is None
