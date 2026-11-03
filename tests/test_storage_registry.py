"""The registry must survive storage exactly. Real values live only in client.json, never next to a transcript."""
import importlib.util
import re
from pathlib import Path

import pytest

from app.store import Store
from app.paths import CLIENT_FILE
from app.scrub.evaluate import load_annotated
from app.scrub.ner import NerConfig, NerModel, find_model_file
from app.scrub.pipeline import ScrubConfig, scrub_transcript
from app.scrub.registry import Registry, canonical_email, norm

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.ann.txt"))
REAL = Path(__file__).resolve().parent.parent / "models" / "gliner_pii"
HAS_MODEL = find_model_file(REAL) is not None and importlib.util.find_spec("onnxruntime") is not None


def annotated(path):
    return load_annotated(path.stem, path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ner():
    return NerModel(NerConfig(model_dir=REAL)) if HAS_MODEL else None


@pytest.fixture
def store(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    with Store.open(tmp_path / "data", env={}, home=home) as s:
        yield s


@pytest.mark.parametrize("keep_first", [False, True])
@pytest.mark.parametrize("use_model", [False, True])
@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem[:12])
def test_saved_registry_comes_back_identical_and_scrubs_the_same(store, ner, path, use_model, keep_first):
    if use_model and not HAS_MODEL:
        pytest.skip("exported model not installed")
    model = ner if use_model else None
    cfg = ScrubConfig(keep_first_names=keep_first, require_ner=use_model)
    text = annotated(path).text
    reg = Registry()
    first = scrub_transcript(text, reg, cfg, model)
    cid = store.create_client("Test")
    store.save_registry(cid, reg, "TX-20261101-1")
    loaded = store.load_registry(cid)
    assert loaded.to_dict() == reg.to_dict()
    # the same text through a copy of the original and through the reloaded registry gives the same output
    again_original = scrub_transcript(text, Registry.from_dict(reg.to_dict()), cfg, model)
    again_loaded = scrub_transcript(text, loaded, cfg, model)
    assert again_loaded.text == again_original.text
    assert again_loaded.text == first.text
    assert loaded.to_dict() == reg.to_dict(), "a second pass must not change the registry"


def test_registry_keeps_growing_across_saves(store):
    cid = store.create_client("Test")
    texts = [annotated(p).text for p in FIXTURES[:2]]
    reg = Registry()
    scrub_transcript(texts[0], reg)
    store.save_registry(cid, reg)
    reg2 = store.load_registry(cid)
    scrub_transcript(texts[1], reg2)
    store.save_registry(cid, reg2)
    assert store.load_registry(cid).to_dict() == reg2.to_dict()
    assert len(reg2.entities) > len(reg.entities)


def forbidden(ann):
    """Every tagged value, in the forms the registry might have stored it."""
    out = set()
    for s, e, t, _ in ann.spans:
        value = ann.text[s:e]
        out |= {value, norm(value), canonical_email(value)}
    return {v for v in out if len(v) >= 4}


def test_real_values_are_only_in_client_json(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    folder = tmp_path / "data"
    with Store.open(folder, env={}, home=home) as s:
        for path in FIXTURES:
            ann = annotated(path)
            reg = Registry()
            scrubbed = scrub_transcript(ann.text, reg, ScrubConfig(), None).text
            cid = s.create_client("Test")
            s.save_registry(cid, reg, "TX-20261101-1")
            tx = s.add_transcript(cid, scrubbed)
            s.add_output(cid, tx, "clio-note", "[PERSON_1] called.")
            assert any(v in (folder / "clients" / cid / CLIENT_FILE).read_text(encoding="utf-8") for v in forbidden(ann))
            stored = "".join(p.read_text(encoding="utf-8") for p in (folder / "clients" / cid / "transcripts").rglob("*")
                             if p.is_file())
            assert "[PERSON_1]" in stored
            values = {v for e in reg.entities for v in e.forms.values() if len(v) >= 4}
            assert [v for v in values if re.search(rf"(?<!\w){re.escape(v)}(?!\w)", stored)] == []
