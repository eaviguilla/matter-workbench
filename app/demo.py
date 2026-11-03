"""Demo mode: a throwaway workbench seeded with synthetic clients. Nothing here is real data.

The data lives in a temp folder that is removed on exit, so the real data folder is never touched. Start it with:  python -m app --demo
"""
import atexit
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

from . import workflow as wf
from .scrub.evaluate import load_annotated
from .scrub.ner import NerConfig, NerModel
from .store import Store
from .web import create_app

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
CLIENTS = (("Maria", "01_maria_lopez"), ("Daniel", "02_daniel_whitfield"), ("Priya", "03_priya_raman"))


class _NoHits:
    def predict(self, text, labels, threshold):
        return []


def seed(store: Store, ner: NerModel) -> None:
    settings = wf.load_settings(store)
    for i, (first, name) in enumerate(CLIENTS):
        cid = store.create_client(first)
        ann = load_annotated(name, (FIXTURES / f"{name}.ann.txt").read_text(encoding="utf-8"))
        intake = wf.run_intake(store, cid, ann.text, ner, settings)
        decisions = [{"text": g.text, "decision": "keep",
                      "spans": [(o["start"], o["end"]) for o in g.occurrences]} for g in intake.groups]
        # Recent days, never after today: the app refuses a future call date, so the demo must not hold one.
        call_date = date.today() - timedelta(days=len(CLIENTS) - i)
        tx = wf.save_transcript(store, cid, ann.text, call_date, ner, settings, decisions)
        if i == 0:
            store.add_output(cid, tx, "clio-note", "Call note for [PERSON_1]\n- Spoke with [PERSON_2.first]"
                             " about the denied claim.\n- Mail goes to [ADDRESS_1].\n- Follow up with [PERSON_9].", "import")
            store.add_output(cid, tx, "clio-note", "Call note for [PERSON_1] (revised)\n- Spoke with "
                             "[PERSON_2.first] about the denied claim.\n- Mail goes to [ADDRESS_1].", "edit")
            store.add_output(cid, tx, "jordan-calendar-overview", "Calendar notes for [PERSON_1]\n- Appeal deadline "
                             "as said on the call.\n- Reply to [EMAIL_1] this week.", "import")
            store.set_requested_outputs(tx, ["clio-note", "jordan-calendar-overview", "clio-form-note"])    # the last one is still waiting
            store.add_message(cid, "correction", f"[CLIENT: {cid} | TX: {tx}]\n[CORRECTION] fix the date", tx)
            store.set_transcript_status(tx, "copied")


def create_demo_app(model_dir: Path | None = None):
    folder = Path(tempfile.mkdtemp(prefix="matter-workbench-demo-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    ner = NerModel(NerConfig(model_dir=model_dir or Path(__file__).resolve().parent.parent / "models" / "gliner_pii"))
    if not ner.available:                   # still show the screens; real scrubbing needs the model
        ner = NerModel(backend_factory=lambda: _NoHits())
    with Store.open(folder, env={}, home=folder) as s:
        seed(s, ner)
    return create_app(folder, env={}, home=folder, ner=ner)
