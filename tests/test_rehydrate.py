from app.rehydrate import rehydrate
from app.scrub.pipeline import scrub_transcript
from app.scrub.registry import Registry

HEADER = "[CLIENT: Maria-20261102-1 | TX: TX-20261102-1]"


def make():
    r = Registry()
    text = ("• Maria Lopez 0:01\nMy father, Roberto Hale, lives at 12 Oak Street, Dayton, OH 45402. "
            "Mail maria@example.com.\n• Sam Whitaker 0:09\nThanks Maria.\n")
    res = scrub_transcript(text, r)
    return r, text, res


def test_round_trip_restores_the_original():
    r, text, res = make()
    assert rehydrate(res.text, r).text == text


def test_tolerates_case_drift_spaces_and_possessives():
    r, *_ = make()
    out = rehydrate(f"{HEADER}\n[person_1.FIRST] and [ PERSON_1 ]'s car, [PERSON_1 . last].", r)
    assert out.text.endswith("Maria and Maria Lopez's car, Lopez.")
    assert not out.unknown


def test_unknown_placeholder_is_left_in_place_and_reported():
    r, *_ = make()
    out = rehydrate("See [PERSON_9] and [PERSON_1.nick] and [EMAIL_1].", r)
    assert "[PERSON_9]" in out.text and "[PERSON_1.nick]" in out.text
    assert out.unknown == ["[PERSON_9]", "[PERSON_1.nick]"]
    assert "maria@example.com" in out.text


def test_header_is_found_and_never_treated_as_a_placeholder():
    r, *_ = make()
    out = rehydrate(f"{HEADER}\nSummary for [PERSON_1.first].", r)
    assert (out.client_id, out.tx_id) == ("Maria-20261102-1", "TX-20261102-1")
    assert out.text.startswith(HEADER) and not out.unknown
    assert rehydrate("no header here", r).client_id is None


def test_unused_entities_are_listed():
    r, *_ = make()
    out = rehydrate("Only [PERSON_1] appears.", r)
    assert "[PERSON_3]" in out.unused and "[PERSON_1]" not in out.unused


def test_possible_real_value_skips_client_first_name_and_header():
    r, *_ = make()
    out = rehydrate(f"{HEADER}\nMaria said Roberto and Sam Whitaker agree.", r, client_first_name="Maria")
    assert "Maria" not in out.possible_real
    assert "Roberto" in out.possible_real and "Sam Whitaker" in out.possible_real


def test_rehydrated_values_are_plain_text():
    r = Registry()
    r.add_person("<script>x</script> Smith")
    out = rehydrate("Hello [PERSON_1.last]", r)
    assert out.text == "Hello Smith"
    out = rehydrate("Hello [PERSON_1]", r)
    assert out.text == "Hello <script>x</script> Smith"   # returned verbatim as data; the UI inserts text nodes
