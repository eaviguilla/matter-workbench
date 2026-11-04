"""Add synthetic test clients to the data folder, so the client and call pages can be examined.

  python scripts/seed_test_cases.py                      # the normal data folder, or MATTER_WORKBENCH_HOME if set
  python scripts/seed_test_cases.py --data-dir PATH      # a folder of your choice

Safe to run twice. A client whose first name already exists is skipped, and no other client is touched. Every name
starts with Test and every name, email and address is invented. The newer cases (Testk to Testn) also have call titles;
the first ten do not. The registries hold the invented real values, so the
pages show restored names. The scrubbed transcripts and outputs hold placeholders only, apart from one reply in
Testf that was saved with an invented name in plain text on purpose, to show the real-value warning.
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import forms  # noqa: E402
from app.outputs import FORM_SLUGS, SLUGS, TEXT_SLUGS  # noqa: E402
from app.scrub.registry import Registry  # noqa: E402
from app.store import Store  # noqa: E402

NOTE, CAL, FORM = TEXT_SLUGS
LONG_FIRST = "Testhlongfirstnamethatkeepsongoingandgoing"


def people(first: str, last: str):
    """A registry with the client, an office person, an email and an address. Returns it and the placeholders."""
    reg = Registry()
    me = reg.add_person(f"{first} {last}")[0]
    staff = reg.add_person("Sam Officer")[0]
    mail = reg.add_value("EMAIL", f"{first.lower()[:12]}.{last.lower()}@example.test")[0]
    addr = reg.add_value("ADDRESS", "12 Sample Road, Testville")[0]
    return reg, dict(me=me.placeholder(), first=me.placeholder("first"), staff=staff.placeholder(),
                     mail=mail.placeholder(), addr=addr.placeholder())


def transcript(p: dict, topic: str) -> str:
    return (f"{p['staff']}: Thank you for calling the office. Who am I speaking with?\n"
            f"{p['me']}: Hello, this is {p['first']}. I am calling about {topic}.\n"
            f"{p['staff']}: Can I confirm your address is {p['addr']} and your email is {p['mail']}?\n"
            f"{p['me']}: Yes, both are right. I need an answer by 20 November.\n"
            f"{p['staff']}: Understood. We will send the draft to {p['mail']} on Friday.\n")


def note(p: dict, n: int = 1) -> str:
    return (f"Call with {p['me']} about the lease. {p['first']} wants the repair finished by 20 November. "
            f"Draft to be sent to {p['mail']} on Friday. Revision {n}.")


def overview(p: dict, n: int = 1) -> str:
    return (f"20 Nov: {p['first']}'s deadline for the repair answer.\nFriday: send the draft to {p['mail']}.\n"
            f"Revision {n}.")


def form(p: dict, n: int = 1) -> str:
    return (f"Matter: Lease repair\nContact: {p['me']}\nIssue: repair deadline of 20 November\n"
            f"Next step: send the draft on Friday. Revision {n}.")


def probate(p: dict, n: int = 1) -> str:
    return forms.render(FORM_SLUGS[0], {1: p["first"], 2: "None.", 3: "California", 4: "Orange", 5: "03/14/2026",
                                        6: f"A house and a bank account. Revision {n}.", 7: "Yes",
                                        8: "12 Example Street, Santa Ana", 9: "Not discussed", 13: "Not discussed"})


def long_overview(p: dict) -> str:
    rows = [f"{day} Nov: follow up with {p['first']} on item {day}. Confirm the date with {p['staff']} and keep "
            f"{p['mail']} copied on the reply." for day in range(1, 29)]
    return "\n".join(["Dates and deadlines mentioned across the call.", *rows])


LOTS_OF_TITLES = ["Lease follow-up", "Repair deadline", "Payment plan", "Notice check", "Deposit question", "Move-out date",
                  "Document list", "Hearing prep", "Settlement offer", "Landlord reply"]


def lots_of_calls() -> list:
    """40 calls over about four months, with titles and a mix of output states, newest first."""
    full = {NOTE: [(lambda p: note(p), "import")], CAL: [(lambda p: overview(p), "import")],
            FORM: [(lambda p: form(p), "import")]}
    kinds = [dict(requested=[NOTE, CAL, FORM], status="copied", outputs=full),
             dict(requested=[NOTE], status="copied", outputs={NOTE: [(lambda p: note(p), "import"), (lambda p: note(p, 2), "mcp")]}),
             dict(requested=[NOTE, CAL], status="copied", outputs={}),
             dict(requested=[], status="reviewed", outputs={}),
             dict(requested=[CAL, FORM], status="copied", outputs={CAL: [(lambda p: overview(p), "import")]})]
    calls = []
    for i in range(40):
        calls.append(dict(ago=2 + 3 * i, topic=f"item {40 - i}", title=f"{LOTS_OF_TITLES[i % len(LOTS_OF_TITLES)]} {40 - i}",
                          **kinds[i % len(kinds)]))
    return calls


def nine_versions() -> list:
    sources = ["import", "mcp", "import", "edit", "mcp", "import", "mcp", "edit", "mcp"]
    return [(lambda p, n=n: note(p, n), src) for n, src in enumerate(sources, 1)]


def hidename_transcript(p: dict) -> str:
    return (transcript(p, "the keys").rstrip("\n")
            + f"\n{p['me']}: Hartley Quimby is the landlord and he said he will bring the keys on Friday.\n")


def case_list() -> list:
    """Each case: first name, last name, calls newest first. A call is (days ago, topic, requested, outputs, status).
    outputs maps a slug to [(text builder, source)]. Builders take the placeholders and return the text."""
    return [
        dict(first="Testa", last="Allthree", calls=[dict(
            ago=1, topic="the lease", requested=[NOTE, CAL, FORM], status="copied",
            outputs={NOTE: [(lambda p: note(p, 1), "import"), (lambda p: note(p, 2), "mcp"),
                            (lambda p: note(p, 3) + " Hand edit: added the phone call time.", "edit")],
                     CAL: [(lambda p: overview(p, 1), "import"), (lambda p: overview(p, 2), "mcp")],
                     FORM: [(lambda p: form(p, 1), "import")],
                     FORM_SLUGS[0]: [(lambda p: probate(p, 1), "import"), (lambda p: probate(p, 2), "edit")]})]),
        dict(first="Testb", last="Onlyone", calls=[dict(
            ago=2, topic="a boundary question", requested=[NOTE], status="copied",
            outputs={NOTE: [(lambda p: note(p), "import")]})]),
        dict(first="Testc", last="Waiting", calls=[dict(
            ago=3, topic="a contract renewal", requested=[NOTE, CAL], status="copied", outputs={})]),
        dict(first="Testd", last="Noneyet", calls=[dict(
            ago=4, topic="an estate question", requested=[], status="reviewed", outputs={})]),
        dict(first="Teste", last="Longtext", calls=[dict(
            ago=5, topic="a long list of dates", requested=[NOTE, CAL, FORM], status="copied",
            outputs={NOTE: [(lambda p: note(p), "import")], CAL: [(long_overview, "import")],
                     FORM: [(lambda p: form(p), "import")]})]),
        dict(first="Testf", last="Warnings", extra_person="Quentin Verity", calls=[dict(
            ago=6, topic="a deed", requested=[NOTE, CAL, FORM], status="copied",
            outputs={NOTE: [(lambda p: note(p) + " Ask [PERSON_9] to sign.", "import")],
                     CAL: [(lambda p: overview(p) + "\nSpoke with Quentin Verity about the deed.", "import")],
                     FORM: [(lambda p: form(p), "import")]})]),
        dict(first="Testg", last="Manycalls", calls=[
            dict(ago=2, topic="a follow up", requested=[NOTE, CAL, FORM], status="copied",
                 outputs={NOTE: [(lambda p: note(p), "import")], CAL: [(lambda p: overview(p), "import")],
                          FORM: [(lambda p: form(p), "import")]}),
            dict(ago=9, topic="a payment plan", requested=[NOTE], status="copied", outputs={NOTE: [(lambda p: note(p), "import")]}),
            dict(ago=16, topic="a notice", requested=[NOTE, CAL], status="copied", outputs={}),
            dict(ago=30, topic="a first meeting", requested=[], status="reviewed", outputs={}),
            dict(ago=47, topic="a document check", requested=[CAL], status="copied", outputs={CAL: [(lambda p: overview(p), "import")]}),
            dict(ago=90, topic="an intake call", requested=[], status="reviewed", outputs={})]),
        dict(first=LONG_FIRST, last="Wide", calls=[dict(
            ago=7, topic="a name that keeps going", requested=[NOTE, CAL, FORM], status="copied",
            outputs={NOTE: [(lambda p: note(p), "import")], CAL: [(lambda p: overview(p), "import")],
                     FORM: [(lambda p: form(p), "import")]})]),
        dict(first="Testi", last="Archived", archived=True, calls=[dict(
            ago=120, topic="a closed matter", requested=[NOTE], status="copied",
            outputs={NOTE: [(lambda p: note(p), "import")]})]),
        dict(first="Testj", last="Empty", calls=[]),
        # Newer cases, with call titles.
        dict(first="Testk", last="Nineversions", calls=[dict(
            ago=3, topic="a long revision history", title="Lease follow-up", requested=[NOTE, CAL, FORM], status="copied",
            outputs={NOTE: nine_versions(),
                     CAL: [(lambda p: overview(p, 1), "import"), (lambda p: overview(p, 2), "mcp")],
                     FORM: [(lambda p: form(p, 1), "import"), (lambda p: form(p, 2), "edit")]})]),
        dict(first="Testl", last="Manycalls", calls=lots_of_calls()),
        dict(first="Testm", last="Hidename", calls=[dict(
            ago=1, topic="the keys", title="Key handover", requested=[NOTE], status="copied",
            text=hidename_transcript, outputs={NOTE: [(lambda p: note(p) + " Hartley Quimby will bring the keys.", "import")]})]),
        # Paste samples/review_may.txt into this client's Add transcript page to try Choose each place.
        dict(first="Testn", last="Reviewwords", calls=[]),
    ]


def seed(store: Store) -> tuple[list, list]:
    """Add the test clients that are missing. Returns (first names added, first names skipped)."""
    have = {c["first_name"].strip().casefold() for c in store.list_clients(include_archived=True)}
    added, skipped = [], []
    today = date.today()
    for case in case_list():
        first = case["first"]
        if first.casefold() in have:
            skipped.append(first)
            continue
        reg, p = people(first, case["last"])
        with store.transaction():          # one client, all or nothing, so a stopped run never leaves half a client
            cid = store.create_client(first)
            first_tx = None
            for call in case["calls"]:
                body = call["text"](p) if call.get("text") else transcript(p, call["topic"])
                tx = store.add_transcript(cid, body, today - timedelta(days=call["ago"]), call.get("title", ""))
                first_tx = first_tx or tx
                for slug, versions in call["outputs"].items():
                    for build, source in versions:
                        store.add_output(cid, tx, slug, build(p), source)
                store.set_requested_outputs(tx, call["requested"])
                store.set_transcript_status(tx, call["status"])
            if case.get("extra_person"):           # known only after the reply was saved, as when a name is added later
                reg.add_person(case["extra_person"])
            store.save_registry(cid, reg, first_tx)
            if case.get("archived"):
                store.set_archived(cid, True)
        added.append(first)
    return added, skipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", type=Path, default=None,
                    help="the data folder; by default the normal one, or MATTER_WORKBENCH_HOME if it is set")
    args = ap.parse_args(argv)
    with Store.open(args.data_dir) as store:
        added, skipped = seed(store)
    print(f"Added {len(added)} test client{'s' if len(added) != 1 else ''}"
          + (f". Skipped {len(skipped)} that already exist." if skipped else "."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
