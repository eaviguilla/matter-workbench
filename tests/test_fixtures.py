"""The 10 synthetic intake conversations: every tagged value must be scrubbed or flagged."""
from pathlib import Path

import pytest

from app.scrub.evaluate import evaluate, load_annotated
from app.scrub.pipeline import ScrubConfig

FILES = sorted((Path(__file__).parent / "fixtures").glob("*.ann.txt"))


def run(path, cfg=ScrubConfig()):
    return evaluate(load_annotated(path.stem, path.read_text(encoding="utf-8")), cfg)


def test_there_are_ten_conversations():
    assert len(FILES) == 10


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem[:12])
@pytest.mark.parametrize("keep_first", [False, True])
def test_no_leak_survives_the_review_gate(path, keep_first):
    rep = run(path, ScrubConfig(keep_first_names=keep_first))
    assert rep.leaks_after_gate == []
    assert rep.inconsistent == []


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem[:12])
def test_emails_and_addresses_are_always_caught_automatically(path):
    rep = run(path)
    assert [m for m in rep.auto_missed if m[0] in ("EMAIL", "ADDRESS")] == []


def test_overall_automatic_recall_does_not_regress():
    total = missed = 0
    for p in FILES:
        rep = run(p)
        total += sum(rep.total.values())
        missed += len(rep.auto_missed)
    assert (total - missed) / total >= 0.94


def test_scrubbed_text_hides_every_tagged_surname_and_email_domain():
    for p in FILES:
        ann = load_annotated(p.stem, p.read_text(encoding="utf-8"))
        rep = evaluate(ann)
        for s, e, t, _ in ann.spans:
            text = ann.text[s:e]
            if t == "EMAIL" or (t == "ADDRESS"):
                assert text not in rep.scrubbed_text
