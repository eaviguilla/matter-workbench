"""The three named outputs: their files, the Copy checklist, the Import and connector routes, and the transcript page."""
import json
import re

import pytest

from app import workflow as wf
from app.store import Store
from app.outputs import FORM_SLUGS, SLUGS, TEXT_SLUGS
from tests.webhelp import Session, fixture_text, make_app, review_form, saved_tx

NOTE, CAL, FORM = TEXT_SLUGS


@pytest.fixture
def env(tmp_path):
    web = Session(make_app(tmp_path))
    cid = web.post("/clients", {"first_name": "Maria"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    r = web.post(f"/clients/{cid}/intake", {"text": fixture_text(1), "call_date": "2026-11-02"})
    tx = saved_tx(web.post(f"/clients/{cid}/intake/save", review_form(r.text), follow_redirects=False))
    return web, cid, tx, tmp_path


def store_of(web):
    app = web.c.app
    return Store.open(app.state.data_dir, env={}, home=app.state.home)


def tx_dir(tmp_path, cid, tx):
    return tmp_path / "data" / "clients" / cid / "transcripts" / tx


def copy(web, tx, outputs):
    return web.post_json(f"/transcripts/{tx}/copy", {"outputs": outputs})


def textarea(html):
    import html as h
    return h.unescape(re.search(r'<textarea [^>]*name="content"[^>]*>(.*?)</textarea>', html, re.S).group(1))


def do_import(web, cid, text, **fields):
    chk = web.post(f"/clients/{cid}/import", {"text": text, **fields})
    return chk, web.post(f"/clients/{cid}/import/save", {"content": textarea(chk.text), "kind": "output", **fields},
                         follow_redirects=False)


def all_output_text(tmp_path):
    return "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "data" / "clients").rglob("*.json")
                   if p.name != "client.json")


# ---- storage ------------------------------------------------------------------------------------------

def test_each_output_is_its_own_file_with_add_only_versions(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        assert s.add_output(cid, tx, NOTE, "one") == 1 and s.add_output(cid, tx, NOTE, "two", "mcp") == 2
        assert s.add_output(cid, tx, NOTE, "three", "edit") == 3
    data = json.loads((tx_dir(tmp, cid, tx) / f"{NOTE}.json").read_text(encoding="utf-8"))
    assert data["schema"] == 1 and data["output"] == NOTE and data["transcript_id"] == tx
    assert [(v["version"], v["source"], v["text"]) for v in data["versions"]] == [
        (1, "import", "one"), (2, "mcp", "two"), (3, "edit", "three")]
    assert all(set(v) == {"version", "at", "source", "text"} for v in data["versions"])
    assert not (tx_dir(tmp, cid, tx) / "reply.json").exists()


def test_updating_one_output_leaves_the_other_files_alone(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        s.add_output(cid, tx, CAL, "calendar")
        s.add_output(cid, tx, FORM, "form")
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tx_dir(tmp, cid, tx).glob("*.json")}
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "note")
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tx_dir(tmp, cid, tx).glob("*.json")}
    assert set(after) == {f"{NOTE}.json", f"{CAL}.json", f"{FORM}.json"}
    for slug in (CAL, FORM):
        assert after[f"{slug}.json"] == before[f"{slug}.json"]


def test_the_store_needs_a_known_output(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        for bad in ("reply", "", "../clio-note", "Clio-Note", None):
            with pytest.raises(ValueError):
                s.add_output(cid, tx, bad, "x")
            with pytest.raises(ValueError):
                s.list_outputs(tx, bad)
        with pytest.raises(TypeError):
            s.list_outputs(tx)
        with pytest.raises(ValueError):
            s.add_output(cid, tx, NOTE, "x", "somewhere")
        with pytest.raises(ValueError):
            s.set_requested_outputs(tx, ["reply"])
    assert list(tx_dir(tmp, cid, tx).glob("*.json")) == []


def test_two_outputs_in_one_transaction_commit_or_drop_together(env, monkeypatch):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        with s.transaction():
            s.add_output(cid, tx, NOTE, "a")
            s.add_output(cid, tx, CAL, "b")
            s.add_output(cid, tx, NOTE, "c")
        assert [o["content"] for o in s.list_outputs(tx, NOTE)] == ["a", "c"] and len(s.list_outputs(tx, CAL)) == 1
        with pytest.raises(RuntimeError):
            with s.transaction():
                s.add_output(cid, tx, FORM, "never")
                raise RuntimeError("stop")
        assert s.list_outputs(tx, FORM) == []


def test_the_check_command_knows_the_output_files(env):
    from app import check
    web, cid, tx, tmp = env
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "x")
        s.set_requested_outputs(tx, [NOTE])
    assert check.check(tmp / "data") == []
    (tx_dir(tmp, cid, tx) / "reply.json").write_text('{"output": "reply", "transcript_id": "' + tx + '", "versions": []}',
                                                     encoding="utf-8")
    assert any("reply.json: not a known output file" in p for p in check.check(tmp / "data"))


# ---- Copy for Claude ----------------------------------------------------------------------------------

def test_copy_needs_at_least_one_output_ticked(env):
    web, cid, tx, tmp = env
    assert web.post_json(f"/transcripts/{tx}/copy", {}).status_code == 400
    for picked in ([], "clio-note", ["reply"], [NOTE, "nope"], [5]):
        assert copy(web, tx, picked).status_code == 400
    assert web.post(f"/transcripts/{tx}/copy", {}).status_code == 400            # a form post with nothing ticked
    with store_of(web) as s:
        assert s.list_messages(cid) == [] and s.get_transcript(tx)["status"] == "reviewed"
        assert s.get_transcript(tx)["requested_outputs"] == []
    with pytest.raises(wf.ImportProblem):
        wf.chosen_outputs([])


def test_the_page_disables_copy_until_something_is_ticked_and_boxes_follow_the_last_copy(env):
    web, cid, tx, tmp = env
    page = web.get(f"/transcripts/{tx}").text
    assert re.search(r'<button type="button" data-copy-url="[^"]*" disabled>Copy for Claude', page)
    assert page.count('name="output"') == 6 and " checked" not in page.split("<legend>Ask Claude for</legend>")[1].split("</fieldset>")[0]
    assert copy(web, tx, [FORM, NOTE]).status_code == 200
    fields = web.get(f"/transcripts/{tx}").text.split("<legend>Ask Claude for</legend>")[1].split("</fieldset>")[0]
    assert re.findall(r'value="([a-z-]+)"( checked)?', fields) == [(NOTE, " checked"), (CAL, ""), (FORM, " checked"), (FORM_SLUGS[0], ""), (FORM_SLUGS[1], ""), (FORM_SLUGS[2], "")]
    assert re.search(r'data-copy-url="[^"]*">Copy for Claude', web.get(f"/transcripts/{tx}").text)
    # a later call starts from the last choice
    r = web.post(f"/clients/{cid}/intake", {"text": fixture_text(1).replace("Hello", "Hi there"), "call_date": "2026-11-01"})
    tx2 = saved_tx(web.post(f"/clients/{cid}/intake/save", review_form(r.text), follow_redirects=False))
    assert tx2 != tx
    fields = web.get(f"/transcripts/{tx2}").text.split("<legend>Ask Claude for</legend>")[1].split("</fieldset>")[0]
    assert re.findall(r'value="([a-z-]+)"( checked)?', fields) == [(NOTE, " checked"), (CAL, ""), (FORM, " checked"), (FORM_SLUGS[0], ""), (FORM_SLUGS[1], ""), (FORM_SLUGS[2], "")]


def test_the_copied_text_names_the_ticked_outputs_then_the_header_then_the_transcript_and_no_writing_rules(env):
    web, cid, tx, tmp = env
    text = copy(web, tx, [CAL]).json()["text"]
    head, rest = text.split(f"[CLIENT: {cid} | TX: {tx}]\n", 1)
    assert head == f"Outputs to write: Overview for Jordan's calendar notes ({CAL}).\n\n"
    assert "Clio Note" not in text and "Clio form note" not in text and "[OUTPUT:" not in text and "save_output" not in text
    with store_of(web) as s:
        scrubbed = s.get_transcript(tx)["scrubbed_text"]
        assert rest == scrubbed and s.get_transcript(tx)["requested_outputs"] == [CAL]
        assert s.list_messages(cid)[0]["scrubbed_text"] == text
    both = copy(web, tx, [FORM, NOTE, FORM_SLUGS[0]]).json()["text"]
    head = both.split("[CLIENT:")[0]
    assert head == f"Outputs to write: Clio Note ({NOTE}), Clio form note ({FORM}), Probate Intake Form ({FORM_SLUGS[0]}).\n\n"
    assert "Lopez" not in both
    doc = json.loads((tmp / "data" / "clients" / cid / "client.json").read_text(encoding="utf-8"))
    assert doc["transcripts"][tx]["requested_outputs"] == [NOTE, FORM, FORM_SLUGS[0]]


def test_settings_has_no_output_instructions_and_the_old_routes_are_gone(env):
    web, cid, tx, tmp = env
    page = web.get("/settings").text
    assert "Output instructions" not in page and "instructions_" not in page and "Instructions to save in Claude" in page
    assert web.c.post("/settings/outputs", data={"csrf": web.token}).status_code in (404, 405)
    with store_of(web) as s:
        s.set_setting(f"instructions.{NOTE}", "Write two lines only.")        # an old stored setting is ignored
    assert "Write two lines only." not in copy(web, tx, [NOTE]).json()["text"]


# ---- getting outputs in -------------------------------------------------------------------------------

def reply(cid, tx, *parts):
    return f"[CLIENT: {cid} | TX: {tx}]\n" + "\n".join(parts)


def test_a_reply_with_markers_is_split_and_saved_as_new_versions_in_one_go(env):
    web, cid, tx, tmp = env
    text = reply(cid, tx, f"[OUTPUT: {NOTE}]", "Note about [PERSON_1].", "", f"[OUTPUT: {FORM}]", "Form [EMAIL_1] text.")
    chk, saved = do_import(web, cid, text)
    assert "Will save 2 outputs" in chk.text and saved.status_code == 303 and saved.headers["location"] == f"/clients/{cid}?tx={tx}&view=outputs"
    with store_of(web) as s:
        assert [o["content"] for o in s.list_outputs(tx, NOTE)] == ["Note about [PERSON_1]."]
        assert [o["content"] for o in s.list_outputs(tx, FORM)] == ["Form [EMAIL_1] text."]
        assert s.list_outputs(tx, CAL) == []
    do_import(web, cid, reply(cid, tx, f"[OUTPUT: {NOTE}]", "Second note."))
    with store_of(web) as s:
        assert [o["version"] for o in s.list_outputs(tx, NOTE)] == [1, 2] and len(s.list_outputs(tx, FORM)) == 1


def test_a_marker_with_an_unknown_name_is_reported_and_nothing_is_saved(env):
    web, cid, tx, tmp = env
    text = reply(cid, tx, f"[OUTPUT: {NOTE}]", "Good note.", "[OUTPUT: clio-notes]", "Typo section.")
    chk = web.post(f"/clients/{cid}/import", {"text": text})
    assert 'The output name "clio-notes"' in chk.text and "Nothing is saved" in chk.text and "disabled" in chk.text
    saved = web.post(f"/clients/{cid}/import/save", {"content": textarea(chk.text), "kind": "output"})
    assert saved.status_code == 200 and "clio-notes" in saved.text and "Nothing was saved" in saved.text
    with store_of(web) as s:
        assert s.list_outputs(tx, NOTE) == []
    check = wf.check_import(store_of(web), cid, text, None, False)
    assert check.bad_markers == ["clio-notes"] and [p.slug for p in check.pieces] == [NOTE]
    with store_of(web) as s:
        with pytest.raises(wf.ImportProblem):
            wf.save_import(s, cid, check)
    # the same goes for a marker with no text under it
    empty = wf.check_import(store_of(web), cid, reply(cid, tx, f"[OUTPUT: {NOTE}]", "ok", f"[OUTPUT: {CAL}]"), None, False)
    assert empty.empty_markers == [CAL]
    with store_of(web) as s:
        with pytest.raises(wf.ImportProblem):
            wf.save_import(s, cid, empty)
        assert s.list_outputs(tx, NOTE) == []


def test_marker_names_ignore_case_and_spacing_and_text_before_the_first_marker_is_flagged(env):
    web, cid, tx, tmp = env
    text = reply(cid, tx, "Here you go:", "  [output:   CLIO-NOTE ]  ", "Body.")
    check = wf.check_import(store_of(web), cid, text, None, False)
    assert [p.slug for p in check.pieces] == [NOTE] and check.loose_text and check.tx_id == tx
    assert not wf.check_import(store_of(web), cid, reply(cid, tx, f"[OUTPUT: {NOTE}]", "Body."), None, False).loose_text


def test_a_reply_without_markers_needs_an_output_choice(env):
    web, cid, tx, tmp = env
    chk = web.post(f"/clients/{cid}/import", {"text": reply(cid, tx, "Plain text.")})
    assert "No [OUTPUT: ...] lines found" in chk.text and '<select name="output" required>' in chk.text
    saved = web.post(f"/clients/{cid}/import/save", {"content": textarea(chk.text), "kind": "output", "tx_id": tx})
    assert saved.status_code == 200 and "Choose which output" in saved.text
    saved = web.post(f"/clients/{cid}/import/save", {"content": textarea(chk.text), "kind": "output", "tx_id": tx,
                                                     "output": "reply"})
    assert saved.status_code == 200 and "Choose one of the listed outputs" in saved.text
    do_import(web, cid, reply(cid, tx, "Plain text."), output=CAL)
    with store_of(web) as s:
        assert [o["content"] for o in s.list_outputs(tx, CAL)] == ["Plain text."]


def test_a_reply_that_names_two_transcripts_is_refused(env):
    web, cid, tx, tmp = env
    other = f"[CLIENT: {cid} | TX: TX-20200101-1]"
    check = wf.check_import(store_of(web), cid, f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {NOTE}]\nA\n{other}\n[OUTPUT: {CAL}]\nB",
                            None, False)
    assert check.problem and check.tx_id is None


def test_known_real_values_are_replaced_before_any_output_is_stored(env):
    web, cid, tx, tmp = env
    text = reply(cid, tx, f"[OUTPUT: {NOTE}]", "Maria Lopez agreed.", f"[OUTPUT: {CAL}]", "Call Maria Lopez back.")
    chk, _ = do_import(web, cid, text)
    assert "2 real values replaced" in chk.text
    web.post(f"/transcripts/{tx}/outputs/{FORM}/edit", {"content": "x"})        # no such output yet, so nothing happens
    with store_of(web) as s:
        s.add_output(cid, tx, FORM, "Form for [PERSON_1].")
    assert web.post(f"/transcripts/{tx}/outputs/{FORM}/edit", {"content": "Typed Maria Lopez here."}, follow_redirects=False).status_code == 303
    stored = all_output_text(tmp)
    assert "Lopez" not in stored and "[PERSON_" in stored


# ---- the connector ------------------------------------------------------------------------------------

def test_the_connector_rejects_an_unknown_output_and_saves_into_the_named_file(env):
    from mcp_server.server import save_output
    web, cid, tx, tmp = env
    opener = lambda: store_of(web)  # noqa: E731
    with opener() as s:
        cfg = wf.load_settings(s)
        cfg.mcp_enabled = True
        wf.save_settings(s, cfg)
    args = {"client_id": cid, "transcript_id": tx, "content": "Hello [PERSON_1]"}
    for bad in ("reply", "clio_note", "", None, ["clio-note"]):
        text, err = save_output(opener, {**args, "output": bad})
        assert err and text == "rejected: output is not a known output"
    assert save_output(opener, args)[1]
    assert not list(tx_dir(tmp, cid, tx).glob("*.json"))
    assert save_output(opener, {**args, "output": CAL}) == (f"saved {CAL} v1", False)
    assert [p.name for p in tx_dir(tmp, cid, tx).glob("*.json")] == [f"{CAL}.json"]
    # markers inside connector content are not split: the tool names the output itself
    save_output(opener, {**args, "output": FORM, "content": f"[OUTPUT: {NOTE}]\nSomething"})
    with opener() as s:
        assert s.list_outputs(tx, NOTE) == [] and len(s.list_outputs(tx, FORM)) == 1


# ---- the transcript page ------------------------------------------------------------------------------

def test_requested_outputs_wait_for_claude_and_received_ones_open_on_the_latest_version(env):
    web, cid, tx, tmp = env
    assert "Waiting for Claude" not in web.get(f"/transcripts/{tx}").text
    copy(web, tx, [NOTE, CAL, FORM])
    page = web.get(f"/transcripts/{tx}").text
    assert page.count("Waiting for Claude") == 3 and all(f'id="out-{slug}"' in page for slug in SLUGS)
    with store_of(web) as s:
        s.add_output(cid, tx, CAL, "Old [PERSON_1].")
        s.add_output(cid, tx, CAL, "New [PERSON_2].", "mcp")
    page = web.get(f"/transcripts/{tx}").text
    assert page.count("Waiting for Claude") == 2
    shown = re.search(rf'<pre class="text" id="out-rehydrated-{CAL}">(.*?)</pre>', page, re.S).group(1)
    assert shown.startswith("New ") and "[PERSON_2]" not in shown


def test_an_older_version_can_be_chosen_per_output_without_moving_the_latest(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        maria = s.find_placeholder(cid, "PERSON", "Maria Lopez")
        s.add_output(cid, tx, NOTE, f"Note one {maria}.")
        s.add_output(cid, tx, NOTE, "Note two.")
        s.add_output(cid, tx, CAL, "Cal one.")
        s.add_output(cid, tx, CAL, "Cal two.")
    page = web.get(f"/transcripts/{tx}?{NOTE}=1").text
    def shown(html, slug):
        return re.search(rf'<pre class="text" id="out-rehydrated-{slug}">(.*?)</pre>', html, re.S).group(1)
    def raw(html, slug):
        return re.search(rf'<pre class="hidden-text" id="out-raw-{slug}">(.*?)</pre>', html, re.S).group(1)
    assert shown(page, NOTE) == "Note one Maria Lopez."
    assert raw(page, NOTE) == f"Note one {maria}." and shown(page, CAL) == "Cal two."
    assert "Lopez" not in raw(page, NOTE) and "Lopez" in shown(page, NOTE)
    page = web.get(f"/transcripts/{tx}").text
    assert shown(page, NOTE) == "Note two." and raw(page, NOTE) == "Note two."
    with store_of(web) as s:
        assert [o["version"] for o in s.list_outputs(tx, NOTE)] == [1, 2]
    # comparing works for one output and keeps the other's choice
    page = web.get(f"/transcripts/{tx}?{CAL}=2&cmp-{CAL}=1&{NOTE}=1").text
    assert "Changes from v1 to v2" in page and "d-add" in page and f"{NOTE}=1" in page
    assert web.get(f"/transcripts/{tx}?{NOTE}=9&cmp-{NOTE}=x").status_code == 200       # a bad number shows the latest


def test_the_latest_route_counts_versions_of_every_output(env):
    web, cid, tx, tmp = env
    assert web.get(f"/transcripts/{tx}/latest").json() == {"version": 0}
    with store_of(web) as s:
        s.add_output(cid, tx, FORM, "a")
    assert web.get(f"/transcripts/{tx}/latest").json() == {"version": 1}
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "b")
    assert web.get(f"/transcripts/{tx}/latest").json() == {"version": 2}
    assert 'data-version="2"' in web.get(f"/transcripts/{tx}").text


def test_editing_saves_a_new_version_from_the_placeholder_text(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Call [PERSON_1] back.")
    page = web.get(f"/transcripts/{tx}/outputs/{NOTE}/edit")
    assert page.status_code == 200 and textarea(page.text) == "Call [PERSON_1] back."
    r = web.post(f"/transcripts/{tx}/outputs/{NOTE}/edit", {"content": "Call [PERSON_1] back on Monday."}, follow_redirects=False)
    assert r.status_code == 303 and f"edited={NOTE}" in r.headers["location"]
    with store_of(web) as s:
        rows = s.list_outputs(tx, NOTE)
    assert [(o["version"], o["source"], o["content"]) for o in rows] == [
        (1, "import", "Call [PERSON_1] back."), (2, "edit", "Call [PERSON_1] back on Monday.")]
    assert "Saved a new version of Clio Note" in web.get(r.headers["location"]).text
    # nothing changed, or empty text, adds nothing
    same = web.post(f"/transcripts/{tx}/outputs/{NOTE}/edit", {"content": "Call [PERSON_1] back on Monday."})
    assert "Nothing changed" in same.text
    assert "The output is empty" in web.post(f"/transcripts/{tx}/outputs/{NOTE}/edit", {"content": "  \n"}).text
    with store_of(web) as s:
        assert len(s.list_outputs(tx, NOTE)) == 2
    assert web.get(f"/transcripts/{tx}/outputs/{CAL}/edit").status_code == 404          # no version to start from
    assert web.get(f"/transcripts/{tx}/outputs/reply/edit").status_code == 404


def test_editing_goes_through_the_same_masking_as_an_import(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Call [PERSON_1] back.")
    r = web.post(f"/transcripts/{tx}/outputs/{NOTE}/edit", {"content": "Call Maria Lopez back."}, follow_redirects=False)
    assert "masked=1" in r.headers["location"]
    with store_of(web) as s:
        last = s.list_outputs(tx, NOTE)[-1]
    assert "Lopez" not in last["content"] and "[PERSON_" in last["content"] and last["source"] == "edit"
    assert "Lopez" not in all_output_text(tmp)
    assert "replaced with hidden names" in web.get(r.headers["location"]).text


def test_the_markdown_export_covers_every_output_with_real_values(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Note text.")
        s.add_output(cid, tx, NOTE, "Note text revised.", "edit")
        s.add_output(cid, tx, CAL, "Calendar text.")
        s.add_output(cid, tx, FORM, "Form text for [PERSON_1].")
    body = web.post(f"/clients/{cid}/export").text
    for heading in ("### Clio Note v1", "### Clio Note v2", "### Overview for Jordan's calendar notes v1", "### Clio form note v1"):
        assert heading in body
    assert body.index("### Clio Note v1") < body.index("### Overview for") < body.index("### Clio form note")
    assert "Note text revised." in body and "Form text for " in body and "[PERSON_1]" not in body.split("### Clio form note")[1]


def test_no_output_file_ever_holds_a_real_value(env):
    web, cid, tx, tmp = env
    copy(web, tx, [NOTE, CAL, FORM])
    do_import(web, cid, reply(cid, tx, f"[OUTPUT: {NOTE}]", "Maria Lopez called.", f"[OUTPUT: {CAL}]", "See Maria Lopez.",
                              f"[OUTPUT: {FORM}]", "For Maria Lopez."))
    web.post(f"/transcripts/{tx}/outputs/{NOTE}/edit", {"content": "Maria Lopez moved."})
    stored = all_output_text(tmp)
    assert stored.count('"version"') == 4 and "Lopez" not in stored
    assert "Lopez" in web.get(f"/transcripts/{tx}").text            # real values are on screen only


# ---- the header line is never stored ------------------------------------------------------------------

HEADER_TEXT = "[CLIENT:"


def stored_texts(web, tx):
    with store_of(web) as s:
        return {slug: [o["content"] for o in s.list_outputs(tx, slug)] for slug in SLUGS}


def test_an_import_with_a_header_and_no_markers_stores_no_header(env):
    web, cid, tx, tmp = env
    _, saved = do_import(web, cid, f"\n[CLIENT: {cid} | TX: {tx}]\n\n\nNote for [PERSON_1].\n\n", output=NOTE)
    assert saved.status_code == 303
    assert stored_texts(web, tx)[NOTE] == ["Note for [PERSON_1]."]
    assert HEADER_TEXT not in all_output_text(tmp)


def test_an_import_with_a_header_and_markers_stores_no_header_in_any_file(env):
    web, cid, tx, tmp = env
    text = (f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {NOTE}]\n[CLIENT: {cid} | TX: {tx}]\n\nNote body.\n\n"
            f"[OUTPUT: {CAL}]\nCalendar body.\n[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {FORM}]\n\nForm body.")
    do_import(web, cid, text)
    got = stored_texts(web, tx)
    assert got == {NOTE: ["Note body."], CAL: ["Calendar body."], FORM: ["Form body."], FORM_SLUGS[0]: [], FORM_SLUGS[1]: [], FORM_SLUGS[2]: []}
    assert HEADER_TEXT not in all_output_text(tmp)


def test_a_section_with_only_a_header_counts_as_empty_and_nothing_is_saved(env):
    web, cid, tx, tmp = env
    h = f"[CLIENT: {cid} | TX: {tx}]"
    check = wf.check_import(store_of(web), cid, f"{h}\n[OUTPUT: {NOTE}]\nok\n[OUTPUT: {CAL}]\n{h}\n", None, False)
    assert check.empty_markers == [CAL]
    plain = wf.check_import(store_of(web), cid, h + "\n\n", None, False, output=NOTE)
    assert plain.pieces == [] and plain.empty_markers == [NOTE]
    with store_of(web) as s:
        for c in (check, plain):
            with pytest.raises(wf.ImportProblem):
                wf.save_import(s, cid, c)
    assert stored_texts(web, tx) == {NOTE: [], CAL: [], FORM: [], FORM_SLUGS[0]: [], FORM_SLUGS[1]: [], FORM_SLUGS[2]: []}


def test_the_connector_stores_no_header(env):
    from mcp_server.server import save_output
    web, cid, tx, tmp = env
    opener = lambda: store_of(web)  # noqa: E731
    with opener() as s:
        cfg = wf.load_settings(s)
        cfg.mcp_enabled = True
        wf.save_settings(s, cfg)
    h = f"[CLIENT: {cid} | TX: {tx}]"
    assert save_output(opener, {"client_id": cid, "transcript_id": tx, "output": NOTE,
                                "content": f"{h}\n\nConnector note.\n"}) == (f"saved {NOTE} v1", False)
    assert stored_texts(web, tx)[NOTE] == ["Connector note."]
    assert save_output(opener, {"client_id": cid, "transcript_id": tx, "output": CAL, "content": h})[1]
    assert stored_texts(web, tx)[CAL] == [] and HEADER_TEXT not in all_output_text(tmp)


def test_a_mismatched_header_is_still_refused_and_stores_nothing(env):
    web, cid, tx, tmp = env
    other = "Sam-20261102-1"
    for body in (f"[CLIENT: {other} | TX: {tx}]\n[OUTPUT: {NOTE}]\nText.", f"[CLIENT: {other} | TX: {tx}]\nText."):
        check = wf.check_import(store_of(web), cid, body, None, False, output=NOTE)
        assert check.problem and not check.tx_id
        with store_of(web) as s:
            with pytest.raises(wf.ImportProblem):
                wf.save_import(s, cid, check)
    chk = web.post(f"/clients/{cid}/import", {"text": f"[CLIENT: {other} | TX: {tx}]\nText.", "output": NOTE})
    assert f"This reply is for client {other}" in chk.text
    assert stored_texts(web, tx) == {NOTE: [], CAL: [], FORM: [], FORM_SLUGS[0]: [], FORM_SLUGS[1]: [], FORM_SLUGS[2]: []}


def test_a_hand_edit_never_stores_a_header(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "Call [PERSON_1] back.")
    h = f"[CLIENT: {cid} | TX: {tx}]"
    r = web.post(f"/transcripts/{tx}/outputs/{NOTE}/edit", {"content": f"{h}\n\nCall [PERSON_1] back Monday.\n"},
                 follow_redirects=False)
    assert r.status_code == 303
    assert stored_texts(web, tx)[NOTE] == ["Call [PERSON_1] back.", "Call [PERSON_1] back Monday."]
    assert "The output is empty" in web.post(f"/transcripts/{tx}/outputs/{NOTE}/edit", {"content": h}).text
    assert "Nothing changed" in web.post(f"/transcripts/{tx}/outputs/{NOTE}/edit",
                                         {"content": f"{h}\nCall [PERSON_1] back Monday."}).text
    assert len(stored_texts(web, tx)[NOTE]) == 2 and HEADER_TEXT not in all_output_text(tmp)


def test_the_copy_target_on_the_transcript_page_has_no_header_line(env):
    web, cid, tx, tmp = env
    with store_of(web) as s:
        maria = s.find_placeholder(cid, "PERSON", "Maria Lopez")
    do_import(web, cid, f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {NOTE}]\nNote for {maria}.\n[OUTPUT: {CAL}]\nCal for {maria}.")
    page = web.get(f"/transcripts/{tx}").text
    for slug in (NOTE, CAL):
        shown = re.search(rf'<pre class="text" id="out-rehydrated-{slug}">(.*?)</pre>', page, re.S).group(1)
        assert "Maria Lopez" in shown and "[CLIENT" not in shown and "TX-" not in shown
