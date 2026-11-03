from app.scrub.pipeline import ScrubConfig, scrub_message, scrub_transcript
from app.scrub.registry import Registry


def tx(*turns):
    return "".join(f"• {name} 0:{i:02d}\n{text}\n" for i, (name, text) in enumerate(turns, 1))


def test_speaker_names_and_body_are_scrubbed_everywhere():
    r = Registry()
    res = scrub_transcript(tx(("Maria Lopez", "Hi, I'm Maria Lopez."), ("Sam Whitaker", "Thanks Maria. Lopez, right?")), r)
    assert "Maria" not in res.text and "Lopez" not in res.text and "Whitaker" not in res.text
    assert "• [PERSON_1] 0:01" in res.text
    assert "[PERSON_1.first]" in res.text and "[PERSON_1.last]" in res.text
    assert "0:02" in res.text   # timestamps stay


def test_email_containing_a_registered_name_is_one_email_span():
    r = Registry()
    res = scrub_transcript(tx(("Maria Lopez", "Write to Maria.Lopez@gmail.com please.")), r)
    assert "Write to [EMAIL_1] please." in res.text
    assert "gmail" not in res.text


def test_spoken_and_written_email_share_a_placeholder():
    r = Registry()
    res = scrub_transcript(tx(("Sam Whitaker", "It is juan dot cruz at yahoo dot com."),
                              ("Maria Lopez", "Is that juan.cruz@yahoo.com?")), r)
    assert res.text.count("[EMAIL_1]") == 2 and "EMAIL_2" not in res.text


def test_spoken_email_with_number_words_and_spelled_letters():
    r = Registry()
    res = scrub_transcript(tx(("Sam Whitaker", "maria dot lopez seventy one at gmail dot com and p r a m a n at outlook dot com")), r)
    assert "[EMAIL_1] and [EMAIL_2]" in res.text
    assert r.entity("EMAIL", 1).forms[None] == "maria.lopez71@gmail.com"
    assert r.entity("EMAIL", 2).forms[None] == "praman@outlook.com"


def test_names_are_case_sensitive_so_common_words_survive():
    r = Registry()
    res = scrub_transcript(tx(("Will Oyelaran", "I will do it. Will you wait?")), r)
    assert "I will do it." in res.text
    assert "[PERSON_1.first] you wait?" in res.text


def test_possessive_keeps_suffix():
    r = Registry()
    res = scrub_transcript(tx(("Maria Lopez", "That is Maria's car.")), r)
    assert "[PERSON_1.first]'s car." in res.text


def test_cue_names_are_registered_and_propagated():
    r = Registry()
    res = scrub_transcript(tx(("Maria Lopez", "My father, Roberto Hale, died. Then Roberto left a policy.")), r)
    assert "Roberto" not in res.text and "Hale" not in res.text
    assert "[PERSON_2]" in res.text and "[PERSON_2.first]" in res.text


def test_address_with_unit_is_one_placeholder():
    r = Registry()
    res = scrub_transcript(tx(("Priya Raman", "I live at 908 Juniper Court, Apt 3B, Columbus, OH 43215. Yes.")), r)
    assert "I live at [ADDRESS_1]. Yes." in res.text


def test_nickname_joins_the_speakers_entity():
    r = Registry()
    res = scrub_transcript(tx(("Terrence Brooks", "Everybody calls me TJ. Call TJ anything.")), r)
    assert res.text.count("[PERSON_1.nick]") == 2 and len(r.entities) == 1


def test_placeholders_are_stable_across_transcripts_and_reloads():
    r = Registry()
    scrub_transcript(tx(("Maria Lopez", "Hello from Maria Lopez")), r)
    r = Registry.from_dict(r.to_dict())
    res = scrub_transcript(tx(("Sam Whitaker", "Thanks Maria Lopez"), ("Maria Lopez", "Welcome")), r)
    assert "[PERSON_1]" in res.text and "PERSON_3" not in res.text
    assert r.entity("PERSON", 2).forms[None] == "Sam Whitaker"


def test_for_claude_prepends_an_unscrubbed_header():
    r = Registry()
    res = scrub_transcript(tx(("Maria Lopez", "Hi")), r)
    out = res.for_claude("Maria-20261102-1", "TX-20261102-1")
    assert out.startswith("[CLIENT: Maria-20261102-1 | TX: TX-20261102-1]\n")


def test_outgoing_message_uses_the_same_registry():
    r = Registry()
    scrub_transcript(tx(("Maria Lopez", "Hi")), r)
    res = scrub_message("[CORRECTION] Maria Lopez's email is maria@x.com, not Lopez@y.org.", r)
    assert "Maria" not in res.text and "x.com" not in res.text and "y.org" not in res.text
    assert "[PERSON_1]'s email is [EMAIL_1]" in res.text


def test_keep_first_names_scrubs_only_the_last_name():
    r = Registry()
    cfg = ScrubConfig(keep_first_names=True)
    res = scrub_transcript(tx(("Maria Lopez", "I am Maria. My name is Maria Lopez.")), r, cfg)
    assert "• Maria [PERSON_1.last] 0:01" in res.text
    assert "I am Maria. My name is Maria [PERSON_1.last]." in res.text
    assert "Lopez" not in res.text


def test_surname_learned_after_a_bare_first_name():
    r = Registry()
    res = scrub_transcript(tx(("Nora Feldman", "I have a sister, Denise. She is the executor. Denise Brooks-Hall signed.")), r)
    assert "Denise" not in res.text and "Brooks-Hall" not in res.text
    assert "[PERSON_2] [PERSON_2.last] signed" in res.text


def test_review_flags_unknown_capitalized_words_only():
    r = Registry()
    res = scrub_transcript(tx(("Sam Whitaker", "We met Kevin yesterday. Then we left on Tuesday.")), r)
    assert [f.text for f in res.flags] == ["Kevin"]


def test_common_word_name_is_flagged_even_if_the_word_appears_in_lower_case():
    r = Registry()
    res = scrub_transcript(tx(("Sam Whitaker", "I told Bill about it. Bill drove him there. The hospital bill came later.")), r)
    assert [f.text for f in res.flags] == ["Bill", "Bill"]


def test_names_that_are_months_are_flagged_mid_sentence():
    r = Registry()
    res = scrub_transcript(tx(("Sam Whitaker", "We spoke to June at the desk in March.")), r)
    assert "June" in [f.text for f in res.flags]


def test_short_spoken_address_shares_the_full_addresss_placeholder():
    r = Registry()
    res = scrub_transcript(tx(("Priya Raman", "I live at 908 Juniper Court, Apt 3B, Columbus, OH 43215."),
                              ("Jamal Pierce", "Is 908 Juniper the same as your father's?"),
                              ("Priya Raman", "No, 908 Juniper Court, unit 3B.")), r)
    assert res.text.count("[ADDRESS_1]") == 3 and "ADDRESS_2" not in res.text
    assert "Juniper" not in res.text


def test_two_known_single_names_seen_together_become_one_person():
    r = Registry()
    res = scrub_transcript(tx(("Hannah Goldberg", "Mrs. Okafor lives next door. Her name is Rose. Rose Okafor called.")), r)
    assert "Okafor" not in res.text and "Rose" not in res.text
    assert "[PERSON_3] [PERSON_3.last] called" in res.text


def test_keep_first_names_still_scrubs_a_lone_surname_after_a_title():
    r = Registry()
    cfg = ScrubConfig(keep_first_names=True)
    res = scrub_transcript(tx(("Sam Whitaker", "A neighbor, Mrs. Okafor, saw it. Okafor called the police.")), r, cfg)
    assert "Okafor" not in res.text
    assert "Mrs. [PERSON_2]" in res.text


def test_a_kept_first_name_in_a_full_name_is_not_flagged_for_review():
    """With first names left visible, 'Tomas Beltran' becomes 'Tomas [PERSON_1.last]' and the first name is no flag.
    It used to be flagged on every occurrence, and 'scrub' could not clear it, so the transcript could never be saved."""
    text = "•\nDana Whitaker\n0:01\nHello.\n•\nTomas Beltran\n0:06\nYes, I am Tomas Beltran and I live here.\n"
    res = scrub_transcript(text, Registry(), ScrubConfig(keep_first_names=True))
    assert res.flags == []
    assert "Tomas [PERSON_" in res.text and "Beltran" not in res.text
