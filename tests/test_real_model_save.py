"""Saving must work with the real name model, not only with the fake one the other web tests use."""
import importlib.util
import re
from pathlib import Path

import pytest

from app.scrub.pipeline import scrub_transcript
from app.scrub.registry import Registry
from app.web import create_app
from tests.webhelp import Session, fixture_text, make_app, review_form, saved_tx

REAL = Path(__file__).parent.parent / "models" / "gliner_pii"
needs_model = pytest.mark.skipif(not (REAL / "model_quantized.onnx").exists()
                                 or importlib.util.find_spec("onnxruntime") is None, reason="real model not installed")
SAMPLE = (Path(__file__).parent.parent / "samples" / "sample_call.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    d = tmp_path_factory.mktemp("real")
    (d / "home").mkdir()
    return Session(create_app(d / "data", env={}, home=d / "home", model_dir=REAL))


def flagged(html):
    return re.findall(r'<input type="hidden" name="w\d+" value="([^"]*)">', html)


@needs_model
@pytest.mark.parametrize("n", [0, *range(1, 11)])
@pytest.mark.parametrize("decision", ["scrub", "keep"])
def test_every_call_saves_when_each_flag_gets_a_decision(real, n, decision):
    text = SAMPLE if n == 0 else fixture_text(n)
    loc = real.post("/clients", {"first_name": "Tomas"}, follow_redirects=False).headers["location"]
    cid = loc.rsplit("/", 1)[1]
    page = real.post(f"/clients/{cid}/intake", {"text": text, "call_date": "2026-11-02"}).text
    for _ in range(8):      # scrubbing a word can reveal another, and the review page then asks about that one
        assert "Review before saving" in page
        r = real.post(f"/clients/{cid}/intake/save", review_form(page, decision), follow_redirects=False)
        if r.status_code == 303:
            assert saved_tx(r).startswith("TX-")
            return
        page = r.text
    pytest.fail(f"never saved, still flagged: {flagged(page)}")


@pytest.mark.parametrize("sentence, word", [
    ("We use WhatsApp daily.", "WhatsApp"), ("I called MetLife today.", "MetLife"),
    ("It is Tri-State something.", "Tri-State"), ("Over in Wilkes-Barre now.", "Wilkes-Barre"),
])
def test_a_flag_covers_the_whole_word_so_scrubbing_it_clears_it(sentence, word):
    text = f"• Ana Ruiz 0:01\nHello there.\n• Bo Lund 0:06\n{sentence}\n"
    reg = Registry()
    assert word in [f.text for f in scrub_transcript(text, reg).flags]
    reg.add_value("PERSON", word)
    result = scrub_transcript(text, reg)
    assert word not in result.text and word not in [f.text for f in result.flags]


def test_a_word_joined_to_a_known_name_is_still_flagged():
    text = "• Ana Ruiz 0:01\nHello there.\n• Bo Lund 0:06\nWe saw Ana-Marisol today.\n"
    flags = [f.text for f in scrub_transcript(text, Registry()).flags]
    assert "Marisol" in flags


def test_a_save_that_cannot_finish_stays_on_the_review_page_and_names_the_words(tmp_path):
    web = Session(make_app(tmp_path))
    cid = web.post("/clients", {"first_name": "Tomas"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    text = "• Ana Ruiz 0:01\nHello there.\n• Bo Lund 0:06\nWe visited Zebedee today.\n"
    page = web.post(f"/clients/{cid}/intake", {"text": text, "call_date": "2026-11-02"}).text
    form = review_form(page)
    del form["d" + next(k[1:] for k in form if re.fullmatch(r"w\d+", k))]
    r = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    assert r.status_code == 200 and "Review before saving" in r.text and "Zebedee" in r.text
    assert "still need a decision" in r.text
