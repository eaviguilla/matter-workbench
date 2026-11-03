"""File storage: what is on disk, crash safety at every step of a save, two writers, unsafe IDs, damaged files."""
import json
import os
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest

from app import check as checker
from app.ids import make_client_id
from app.paths import UnsafeLocation
from app.scrub.registry import Registry
from app.store import Busy, Damaged, Store, StoreTooNew, write_atomic

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def s(tmp_path):
    (tmp_path / "home").mkdir()
    return Store.open(tmp_path / "data", env={}, home=tmp_path / "home")


def again(tmp_path, **kw):
    return Store.open(tmp_path / "data", env={}, home=tmp_path / "home", **kw)


def registry_with(name="Zed Quill"):
    reg = Registry()
    reg.add_value("PERSON", name)
    return reg


def saved_call(s, cid, text="[PERSON_1] called."):
    with s.transaction():
        tx = s.add_transcript(cid, text, date(2026, 11, 2))
        s.save_registry(cid, registry_with(), tx)
        s.set_transcript_status(tx, "reviewed")
    return tx


# ---- what is on disk --------------------------------------------------------------------------------

def test_the_files_are_where_the_layout_says(s, tmp_path):
    cid = s.create_client("Tomas", date(2026, 11, 2))
    tx = saved_call(s, cid)
    s.add_output(cid, tx, "clio-note", "[PERSON_1] called.")
    folder = tmp_path / "data" / "clients" / "Tomas-20261102-1"
    assert (folder / "transcripts" / tx / "transcript.txt").read_text(encoding="utf-8") == "[PERSON_1] called."
    doc = json.loads((folder / "client.json").read_text(encoding="utf-8"))
    assert doc["first_name"] == "Tomas" and doc["registry"]["entities"][0]["forms"]["full"] == "Zed Quill"
    assert doc["transcripts"][tx]["status"] == "reviewed"
    assert (tmp_path / "data" / "audit.jsonl").exists()


def test_new_output_versions_are_added_and_old_ones_stay(s, tmp_path):
    cid = s.create_client("Tomas")
    tx = saved_call(s, cid)
    assert s.add_output(cid, tx, "clio-note", "first") == 1 and s.add_output(cid, tx, "clio-note", "second", "mcp") == 2
    assert [(o["version"], o["content"], o["source"]) for o in s.list_outputs(tx, "clio-note")] == [(1, "first", "import"), (2, "second", "mcp")]
    data = json.loads(next((tmp_path / "data" / "clients" / cid / "transcripts" / tx).glob("*.json")).read_text(encoding="utf-8"))
    assert [v["text"] for v in data["versions"]] == ["first", "second"]


def test_everything_comes_back_from_a_new_process_view(s, tmp_path):
    cid = s.create_client("Tomas")
    tx = saved_call(s, cid)
    s.add_message(cid, "comment", "note", tx)
    s.set_setting("threshold", "0.5")
    s.set_setting(f"client.{cid}.types", "EMAIL")
    s.save_review_decision(tx, (1, 2), "Word", "keep")
    o = again(tmp_path)
    assert o.get_transcript(tx)["scrubbed_text"] == "[PERSON_1] called." and o.get_transcript(tx)["client_id"] == cid
    assert [m["scrubbed_text"] for m in o.list_messages(cid)] == ["note"]
    assert o.get_setting("threshold") == "0.5" and o.get_setting(f"client.{cid}.types") == "EMAIL"
    assert [d["decision"] for d in o.list_review_decisions(tx)] == ["keep"]
    assert o.load_registry(cid).to_dict() == registry_with().to_dict()
    assert o.find_placeholder(cid, "PERSON", "zed quill") == "[PERSON_1]"
    assert [a["action"] for a in o.list_audit()][:2] == ["client_created", "transcript_added"]


def test_transcript_ids_are_unique_across_clients(s):
    a, b = s.create_client("Tomas"), s.create_client("Maria")
    assert saved_call(s, a) != saved_call(s, b)


def test_files_are_private_to_this_user(s, tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX permissions")
    tx = saved_call(s, s.create_client("Tomas"))
    assert tx
    for p in (tmp_path / "data").rglob("*"):
        if p.is_file():
            assert p.stat().st_mode & 0o077 == 0, p.name


# ---- crash safety ------------------------------------------------------------------------------------

STEPS = ["new_file", "before_client", "after_client"]


@pytest.mark.parametrize("step", STEPS)
def test_a_failure_at_any_step_of_a_new_save_leaves_a_whole_state(s, tmp_path, monkeypatch, step):
    cid = s.create_client("Tomas")

    def stop(name):
        if name == step:
            raise OSError("disk full")
    monkeypatch.setattr(Store, "fault", stop)
    with pytest.raises(OSError):
        saved_call(s, cid)
    monkeypatch.setattr(Store, "fault", None)
    o = again(tmp_path)
    o.clean_up()
    listed = o.list_transcripts(cid)
    if step == "after_client":
        assert len(listed) == 1 and listed[0]["scrubbed_text"] and len(o.load_registry(cid).entities) == 1
    else:
        assert listed == [] and o.load_registry(cid).entities == []
        assert list((tmp_path / "data" / "clients" / cid).glob("transcripts/*")) == []


def test_a_failed_output_write_keeps_the_earlier_versions(s, monkeypatch):
    cid = s.create_client("Tomas")
    tx = saved_call(s, cid)
    s.add_output(cid, tx, "clio-note", "first")

    def stop(name):
        if name == "after_client":
            raise OSError("disk full")
    monkeypatch.setattr(Store, "fault", stop)
    with pytest.raises(OSError):
        s.add_output(cid, tx, "clio-note", "second")
    monkeypatch.setattr(Store, "fault", None)
    assert [o["content"] for o in s.list_outputs(tx, "clio-note")] == ["first"]


KILLER = """
    import os, sys
    from datetime import date
    from pathlib import Path
    sys.path.insert(0, {root!r})
    from app.store import Store
    from app.scrub.registry import Registry
    s = Store.open(Path({data!r}), env={{}}, home=Path({home!r}))
    Store.fault = lambda name: os._exit(9) if name == {step!r} else None
    reg = Registry(); reg.add_value("PERSON", "Zed Quill")
    with s.transaction():
        tx = s.add_transcript({cid!r}, "[PERSON_1] called.", date(2026, 11, 2))
        s.save_registry({cid!r}, reg, tx)
"""


@pytest.mark.parametrize("step", STEPS)
def test_killing_the_process_at_any_step_leaves_a_whole_state_and_frees_the_lock(s, tmp_path, step):
    cid = s.create_client("Tomas")
    code = textwrap.dedent(KILLER).format(root=str(ROOT), data=str(tmp_path / "data"), home=str(tmp_path / "home"),
                                          step=step, cid=cid)
    assert subprocess.run([sys.executable, "-c", code], cwd=tmp_path).returncode == 9
    o = again(tmp_path, lock_timeout=1)
    o.clean_up()                        # also proves the dead process did not keep the lock
    saved = o.list_transcripts(cid)
    assert len(saved) == (1 if step == "after_client" else 0)
    assert len(o.load_registry(cid).entities) == len(saved)
    assert list((tmp_path / "data").rglob("*.tmp")) == []
    assert o.add_transcript(cid, "next", date(2026, 11, 3))


def test_a_rolled_back_transaction_writes_nothing(s, tmp_path):
    cid = s.create_client("Tomas")
    with pytest.raises(ValueError):
        with s.transaction():
            s.add_transcript(cid, "text", date(2026, 11, 2))
            s.rename_client(cid, "Changed")
            raise ValueError
    assert s.get_client(cid)["first_name"] == "Tomas" and s.list_transcripts(cid) == []
    assert "transcript_added" not in [a["action"] for a in s.list_audit()]


def test_one_transaction_cannot_half_change_two_clients(s):
    a, b = s.create_client("Tomas"), s.create_client("Maria")
    with pytest.raises(RuntimeError):
        with s.transaction():
            s.rename_client(a, "X")
            s.rename_client(b, "Y")
    assert s.get_client(a)["first_name"] == "Tomas" and s.get_client(b)["first_name"] == "Maria"


# ---- two writers -------------------------------------------------------------------------------------

def test_a_second_writer_waits_then_gives_up_clearly(s, tmp_path):
    with s.transaction():
        with pytest.raises(Busy):
            with again(tmp_path, lock_timeout=0).transaction():
                pass


WRITER = """
    import sys
    from datetime import date
    from pathlib import Path
    sys.path.insert(0, {root!r})
    from app.store import Store
    s = Store.open(Path({data!r}), env={{}}, home=Path({home!r}), lock_timeout=60)
    for i in range(25):
        s.add_transcript({cid!r}, "call", date(2026, 11, 2))
        s.add_output({cid!r}, {tx!r}, "clio-note", "version")
"""


def test_two_processes_saving_at_once_lose_nothing_and_share_no_id(s, tmp_path):
    cid = s.create_client("Tomas")
    tx = saved_call(s, cid)
    code = textwrap.dedent(WRITER).format(root=str(ROOT), data=str(tmp_path / "data"), home=str(tmp_path / "home"),
                                          cid=cid, tx=tx)
    procs = [subprocess.Popen([sys.executable, "-c", code], cwd=tmp_path) for _ in range(2)]
    assert [p.wait(timeout=120) for p in procs] == [0, 0]
    ids = [t["id"] for t in s.list_transcripts(cid)]
    assert len(ids) == 51 == len(set(ids))
    assert [o["version"] for o in s.list_outputs(tx, "clio-note")] == list(range(1, 51))


# ---- unsafe IDs --------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["../../etc", "..", "Tomas-20261102-1\n", "a/b", "..\\..\\x", "", "Tomas-20261102-1/../.."])
def test_a_bad_id_never_reaches_a_path(s, bad):
    assert s.get_client(bad) is None and s.get_transcript(bad) is None and s.list_transcripts(bad) == []
    assert s.list_outputs(bad, "clio-note") == []


def test_the_web_app_refuses_a_path_in_a_client_id(tmp_path):
    from tests.webhelp import Session, make_app
    web = Session(make_app(tmp_path))
    for url in ("/clients/..%2F..%2Fetc", "/transcripts/..%2F..%2Fetc"):
        assert web.c.get(url).status_code == 404


def test_names_differing_only_in_case_get_separate_folders(s):
    a, b = s.create_client("Tomas", date(2026, 11, 2)), s.create_client("TOMAS", date(2026, 11, 2))
    assert a.casefold() != b.casefold()
    assert s.get_client(a)["first_name"] == "Tomas" and s.get_client(b)["first_name"] == "TOMAS"


def test_a_very_long_name_makes_a_usable_folder(s):
    assert s.get_client(s.create_client("A" * 500))
    assert len(make_client_id("A" * 500, date(2026, 11, 2))) < 60


# ---- damaged files -----------------------------------------------------------------------------------

def test_a_damaged_client_is_named_and_the_others_keep_working(s, tmp_path):
    bad, ok = s.create_client("Tomas"), s.create_client("Maria")
    secret = "Zed Quill private"
    (tmp_path / "data" / "clients" / bad / "client.json").write_text('{"first_name": "' + secret, encoding="utf-8")
    assert [c["id"] for c in s.list_clients()] == [ok] and s.damaged == [bad]
    with pytest.raises(Damaged) as e:
        s.get_client(bad)
    assert secret not in str(e.value)


def test_a_damaged_output_is_not_overwritten(s, tmp_path):
    cid = s.create_client("Tomas")
    tx = saved_call(s, cid)
    s.add_output(cid, tx, "clio-note", "first")
    path = next((tmp_path / "data" / "clients" / cid / "transcripts" / tx).glob("*.json"))
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(Damaged):
        s.add_output(cid, tx, "clio-note", "second")
    assert path.read_text(encoding="utf-8") == "{broken"


def test_cleanup_leaves_a_damaged_client_alone(s, tmp_path):
    cid = s.create_client("Tomas")
    tx = saved_call(s, cid)
    folder = tmp_path / "data" / "clients" / cid
    (folder / "client.json").write_text("{broken", encoding="utf-8")
    s.clean_up()
    assert (folder / "transcripts" / tx / "transcript.txt").exists()


def test_data_from_a_newer_version_is_refused(s, tmp_path):
    (tmp_path / "data" / "settings.json").write_text('{"schema": 99, "settings": {}}', encoding="utf-8")
    with pytest.raises(StoreTooNew):
        again(tmp_path)


def test_the_web_app_shows_a_repair_page_with_no_values(tmp_path):
    from tests.webhelp import Session, make_app
    web = Session(make_app(tmp_path))
    cid = web.post("/clients", {"first_name": "Tomas"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    (tmp_path / "data" / "clients" / cid / "client.json").write_text('{"secret": "Zed Quill', encoding="utf-8")
    home = web.get("/")
    assert home.status_code == 200 and cid in home.text and "app.check" in home.text
    page = web.c.get(f"/clients/{cid}", headers={"accept": "text/html"})
    assert page.status_code == 503 and "app.check" in page.text and "Zed Quill" not in page.text


# ---- the check command -------------------------------------------------------------------------------

def test_the_check_passes_on_healthy_data(s, tmp_path):
    cid = s.create_client("Tomas")
    s.add_output(cid, saved_call(s, cid), "clio-note", "first")
    assert checker.check(tmp_path / "data") == []


def test_the_check_reports_problems_without_any_stored_value(s, tmp_path):
    secret = "Zed Quill private"
    a, b, c = s.create_client("Tomas"), s.create_client("Maria"), s.create_client("Lena")
    tx_b, tx_c = saved_call(s, b, secret), saved_call(s, c)
    s.add_output(c, tx_c, "clio-note", secret)
    clients = tmp_path / "data" / "clients"
    (clients / a / "client.json").write_text('{"first_name": "' + secret, encoding="utf-8")
    (clients / b / "transcripts" / tx_b / "transcript.txt").unlink()
    out = next((clients / c / "transcripts" / tx_c).glob("*.json"))
    data = json.loads(out.read_text(encoding="utf-8"))
    data["versions"][0].pop("source")
    out.write_text(json.dumps(data), encoding="utf-8")
    report = "\n".join(checker.check(tmp_path / "data"))
    assert "not valid JSON at line 1" in report and "transcript.txt: the file is missing" in report
    assert "version entry 1: field source" in report and secret not in report and "Zed" not in report


def test_a_location_check_still_applies(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(UnsafeLocation):
        Store.open(tmp_path / "repo" / "data", env={}, home=tmp_path)


def test_atomic_write_replaces_the_whole_file(tmp_path):
    p = tmp_path / "x" / "f.txt"
    write_atomic(p, "one")
    write_atomic(p, "two")
    assert p.read_text(encoding="utf-8") == "two" and [q.name for q in p.parent.iterdir()] == ["f.txt"]
