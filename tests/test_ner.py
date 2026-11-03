import importlib.util
from pathlib import Path

import pytest

from app.scrub.ner import NerConfig, NerModel, NerUnavailable, find_model_file
from app.scrub.pipeline import ScrubConfig, scrub_message, scrub_transcript
from app.scrub.registry import Registry
from fake_ner import FakeBackend


def tx(*turns):
    return "".join(f"• {name} 0:{i:02d}\n{text}\n" for i, (name, text) in enumerate(turns, 1))


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def model(table, **cfg):
    backend = FakeBackend(table)
    loads = []

    def factory():
        loads.append(1)
        return backend
    return NerModel(NerConfig(**cfg), backend_factory=factory, clock=Clock()), backend, loads


def test_model_loads_lazily_on_first_use():
    m, _, loads = model({})
    assert not m.loaded and loads == []
    m.detect("hello")
    assert m.loaded and loads == [1]


def test_model_unloads_after_the_idle_period_and_reloads_on_demand():
    m, _, loads = model({}, idle_seconds=600)
    clock = m._clock
    m.detect("a")
    clock.now = 599
    assert not m.unload_if_idle() and m.loaded
    clock.now = 601
    assert m.unload_if_idle() and not m.loaded
    m.detect("b")
    assert loads == [1, 1]


def test_use_resets_the_idle_timer():
    m, _, _ = model({}, idle_seconds=600)
    m._clock.now = 500
    m.detect("a")
    m._clock.now = 1000
    assert not m.unload_if_idle()
    m._clock.now = 1100
    assert m.unload_if_idle()


def test_threshold_splits_hits_from_near_misses_and_drops_the_rest():
    m, backend, _ = model({"Kevin": ("person", 0.9), "Joy": ("person", 0.4), "Zed": ("person", 0.1)},
                          threshold=0.5, near_miss=0.2)
    res = m.detect("Kevin and Joy and Zed")
    assert [h.score for h in res.hits] == [0.9]
    assert [h.score for h in res.near_misses] == [0.4]
    assert backend.calls[0][1] == pytest.approx(0.3)      # the model is asked once, at the lower bound


def test_missing_model_reports_unavailable_and_blocks_when_required(tmp_path):
    m = NerModel(NerConfig(model_dir=tmp_path))
    assert not m.available
    with pytest.raises(NerUnavailable):
        m.detect("text")
    with pytest.raises(NerUnavailable):
        scrub_transcript(tx(("Sam Whitaker", "Hi")), Registry(), ScrubConfig(require_ner=True), m)
    with pytest.raises(NerUnavailable):
        scrub_message("Hi", Registry(), ScrubConfig(require_ner=True), None)
    # without the flag, rules-only still works
    assert scrub_transcript(tx(("Sam Whitaker", "Hi")), Registry(), ner=None).text.startswith("• [PERSON_1]")


def test_model_catches_a_bare_name_and_propagates_it():
    r = Registry()
    m, _, _ = model({"Kevin": ("person", 0.93)})
    text = tx(("Sam Whitaker", "Who set up the email?"), ("Maria Lopez", "My grandson set it up. Kevin. Kevin's at college."))
    assert "Kevin" in scrub_transcript(text, Registry()).text          # rules alone miss it
    res = scrub_transcript(text, r, ner=m)
    assert "Kevin" not in res.text
    assert res.text.count("[PERSON_3]") == 2 and "[PERSON_3]'s at college" in res.text
    assert any(a.source == "ner" for a in res.applied)


def test_model_hit_with_a_title_keeps_the_title_and_scrubs_the_name():
    m, _, _ = model({"Mrs. Okafor": ("person", 0.9)})
    res = scrub_transcript(tx(("Sam Whitaker", "We spoke to Mrs. Okafor yesterday.")), Registry(), ner=m)
    assert "Mrs. [PERSON_2]" in res.text


def test_model_email_and_address_hits():
    m, _, _ = model({"juan dot cruz at yahoo dot co": ("email", 0.8), "55 Bay Rd": ("street address", 0.8)})
    res = scrub_transcript(tx(("Sam Whitaker", "juan dot cruz at yahoo dot co is his email. He lives at 55 Bay Rd.")),
                           Registry(), ner=m)
    assert "[EMAIL_1]" in res.text and "[ADDRESS_1]" in res.text


def test_near_miss_becomes_a_review_flag_and_is_not_scrubbed():
    m, _, _ = model({"Joy": ("person", 0.4)}, threshold=0.5, near_miss=0.2)
    res = scrub_transcript(tx(("Sam Whitaker", "It was Joy who came by.")), Registry(), ner=m)
    assert "Joy" in res.text
    joy = [f for f in res.flags if f.text == "Joy"]
    assert len(joy) == 1 and "0.40" in joy[0].reason


def test_model_only_sees_turn_bodies_one_turn_at_a_time():
    m, backend, _ = model({})
    scrub_transcript(tx(("Sam Whitaker", "First turn."), ("Maria Lopez", "Second turn.")), Registry(), ner=m)
    assert [c[0].strip() for c in backend.calls] == ["First turn.", "Second turn."]


def test_outgoing_message_goes_through_the_model_too():
    r = Registry()
    m, _, _ = model({"Kevin": ("person", 0.9)})
    res = scrub_message("[CORRECTION] The grandson is Kevin, not Keith.", r, ner=m)
    assert "Kevin" not in res.text and "[PERSON_1]" in res.text


def run(table, *turns, **kw):
    m, _, _ = model(table)
    r = Registry()
    return scrub_transcript(tx(*turns), r, ner=m, **kw), r


def test_model_junk_is_filtered_pronouns_relations_and_phrases():
    table = {w: ("person", 0.99) for w in ["I", "She", "My father", "your mother", "Mom", "Papa", "Who at the insurer"]}
    res, _ = run(table, ("Sam Whitaker", "I think She said My father and your mother and Mom and Papa. Who at the insurer?"))
    assert not [a for a in res.applied if a.source == "ner"]


def test_model_label_words_are_not_emails_or_addresses():
    res, _ = run({"your email": ("email", 0.9), "other lane": ("street address", 0.9)},
                 ("Sam Whitaker", "What is your email? Someone in the other lane stopped."))
    assert not [a for a in res.applied if a.source == "ner"]


def test_model_keeps_real_names_next_to_junk():
    res, _ = run({"Kevin": ("person", 0.9), "My father": ("person", 0.99)}, ("Sam Whitaker", "My father drove Kevin home."))
    assert [a.placeholder for a in res.applied if a.source == "ner"] == ["[PERSON_2]"]


def test_relative_sharing_a_surname_gets_the_existing_surname_placeholder():
    res, r = run({"Joy": ("person", 0.9), "Joy Oyelaran": ("person", 0.95)},
                 ("Will Oyelaran", "Hi. It was Joy at home."), ("Beth Nakamura", "Joy Oyelaran lives there."))
    assert "Oyelaran" not in res.text and "Joy" not in res.text
    assert len(r.entities) == 3             # Will, Beth, Joy. No second Joy and no second Oyelaran.
    assert "[PERSON_3] [PERSON_1.last]" in res.text


def test_shorter_form_after_the_full_name_becomes_a_nickname():
    res, r = run({"Jess": ("person", 0.9)}, ("Jessica Tran", "People say Jess for short."))
    assert "[PERSON_1.nick]" in res.text and len(r.entities) == 2 and r.entity("PERSON", 1).forms["nick"] == "Jess"


def test_full_name_after_a_short_form_links_the_short_one_as_nickname():
    res, r = run({"Rich": ("person", 0.9), "Richard Tolliver": ("person", 0.9)},
                 ("Sam Whitaker", "The director was Rich."), ("Maria Lopez", "Richard Tolliver, yes."))
    assert r.entity("PERSON", 4).forms["nick"] == "Rich"   # 1 Sam, 2 Maria, 3 Rich (orphaned), 4 Richard
    assert "Rich" not in res.text


def test_model_address_that_runs_on_is_cut_back_to_the_known_address():
    res, r = run({"2250 Pine Ridge exit": ("street address", 0.9)},
                 ("Terrence Brooks", "I live at 2250 Pine Ridge Road, Toledo, OH 43604."),
                 ("Nora Feldman", "Near the 2250 Pine Ridge exit?"))
    assert res.text.count("[ADDRESS_1]") == 2 and "ADDRESS_2" not in res.text and "exit?" in res.text


def test_spelled_name_from_the_model_matches_the_known_name():
    res, r = run({"K-O-W-A-L-S-K-I": ("person", 0.9)},
                 ("Sam Whitaker", "The adjuster, Denise Kowalski, called. Spelled K-O-W-A-L-S-K-I."))
    assert len(r.entities) == 2 and "The adjuster, [PERSON_2], called. Spelled [PERSON_2.last]." in res.text


REAL = Path(__file__).resolve().parent.parent / "models" / "gliner_pii"


@pytest.mark.skipif(find_model_file(REAL) is None or importlib.util.find_spec("onnxruntime") is None,
                    reason="exported model or onnxruntime not installed")
def test_real_model_finds_a_bare_name_and_an_address_and_ignores_pronouns():
    m = NerModel(NerConfig(model_dir=REAL))
    r = Registry()
    res = scrub_transcript(tx(("Sam Whitaker", "Who set up the email?"),
                              ("Maria Lopez", "My grandson Kevin Walters did, I think. He lives at 55 Bay Road.")), r, ner=m)
    assert "Kevin" not in res.text and "Walters" not in res.text and "55 Bay Road" not in res.text
    assert "I think" in res.text and "My grandson" in res.text
