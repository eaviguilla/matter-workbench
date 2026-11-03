import re

import pytest

from tests.webhelp import Session, fixture_text, make_app, review_form, saved_tx


@pytest.fixture
def web(tmp_path):
    return Session(make_app(tmp_path))


def new_client(web, name="Maria"):
    r = web.post("/clients", {"first_name": name}, follow_redirects=False)
    assert r.status_code == 303
    return r.headers["location"].rsplit("/", 1)[1]


def scrub_and_save(web, cid, text, decision="scrub"):
    r = web.post(f"/clients/{cid}/intake", {"text": text, "call_date": "2026-11-02"})
    assert r.status_code == 200 and "Review before saving" in r.text, r.text[:400]
    r = web.post(f"/clients/{cid}/intake/save", review_form(r.text, decision), follow_redirects=False)
    assert r.status_code == 303, r.text[:600]
    return saved_tx(r)


def test_full_flow(web):
    cid = new_client(web)
    assert cid.startswith("Maria-")
    tx = scrub_and_save(web, cid, fixture_text(1))
    page = web.get(f"/transcripts/{tx}")
    view = web.stored_text(tx)
    assert "Lopez" not in view and "[PERSON_" in view
    assert "Copy for Claude" in page.text
    # copy for claude records the copy and returns header plus scrubbed text
    r = web.post_json(f"/transcripts/{tx}/copy", {"outputs": ["clio-note"]})
    assert r.status_code == 200
    copied = r.json()["text"]
    assert f"[CLIENT: {cid} | TX: {tx}]\n" in copied and "Lopez" not in copied
    # a client's real full name shows locally
    assert "Maria Lopez" in web.get(f"/clients/{cid}").text
    # import a reply with placeholders, see it rehydrated
    reply = f"[CLIENT: {cid} | TX: {tx}]\nSummary for [PERSON_1]: call [PERSON_2.first] back. Also [PERSON_99]."
    chk = web.post(f"/clients/{cid}/import", {"text": reply, "output": "clio-note"})
    assert "Unknown hidden names" in chk.text and "Maria Lopez" in chk.text
    content = re.search(r'<textarea name="content"[^>]*>(.*?)</textarea>', chk.text, re.S).group(1)
    r = web.post(f"/clients/{cid}/import/save", {"content": content, "kind": "output", "tx_id": tx, "output": "clio-note"},
                 follow_redirects=False)
    assert r.status_code == 303
    r2 = web.post(f"/clients/{cid}/import", {"text": reply.replace("call", "phone"), "output": "clio-note"})
    content2 = re.search(r'<textarea name="content"[^>]*>(.*?)</textarea>', r2.text, re.S).group(1)
    web.post(f"/clients/{cid}/import/save", {"content": content2, "kind": "output", "tx_id": tx,
                                                       "output": "clio-note"})
    out = web.get(f"/transcripts/{tx}?clio-note=2&cmp-clio-note=1")
    assert "Changes from v1 to v2" in out.text and "d-add" in out.text
    assert "Maria Lopez" in web.get(f"/transcripts/{tx}?clio-note=1").text


def test_review_gate_blocks_saving_without_decisions(web):
    cid = new_client(web)
    text = fixture_text(1)
    r = web.post(f"/clients/{cid}/intake", {"text": text, "call_date": "2026-11-02"})
    form = review_form(r.text)
    flagged = [k for k in form if re.fullmatch(r"w\d+", k)]
    assert flagged, "fixture 1 should leave words for review with the rules alone"
    del form["d" + flagged[0][1:]]
    r = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    assert r.status_code == 200 and "still need a decision" in r.text
    assert web.get(f"/clients/{cid}").text.count("TX-") == 0          # nothing was stored


def test_keep_decisions_clear_the_flags_without_hiding_the_word(web):
    cid = new_client(web)
    tx = scrub_and_save(web, cid, fixture_text(1), "keep")
    assert web.get(f"/transcripts/{tx}").status_code == 200


def test_rescan_with_extra_text_hides_it_and_carries_decisions(web):
    cid = new_client(web)
    text = fixture_text(1)
    r = web.post(f"/clients/{cid}/intake", {"text": text, "call_date": "2026-11-02"})
    form = review_form(r.text, "keep")
    form["extra_type"], form["extra_text"] = ["PERSON", "PERSON"], ["Singer", ""]
    r2 = web.post(f"/clients/{cid}/intake/rescan", form)
    assert "Review before saving" in r2.text
    assert 'name="n_flags" value="0"' in r2.text                # every flag already decided
    assert "Nothing is flagged." in r2.text
    form2 = review_form(r2.text)
    r3 = web.post(f"/clients/{cid}/intake/save", form2, follow_redirects=False)
    assert r3.status_code == 303
    tx = saved_tx(r3)
    view = web.stored_text(tx)
    assert "Singer" not in view


def test_any_text_is_accepted_and_the_layout_note_is_shown(web):
    cid = new_client(web)
    r = web.post(f"/clients/{cid}/intake", {"text": "just some words from Tomas Beltran", "call_date": "2026-11-02"})
    assert "Review before saving" in r.text and "No speaker lines were recognized" in r.text
    r = web.post(f"/clients/{cid}/intake", {"text": "   ", "call_date": "2026-11-02"})
    assert "Nothing was pasted" in r.text
    r = web.post(f"/clients/{cid}/intake", {"text": fixture_text(1), "call_date": "not a date"})
    assert "valid call date" in r.text


def test_scrubbing_is_blocked_without_the_model(tmp_path):
    from app.scrub.ner import NerConfig, NerModel
    from app.web import create_app
    (tmp_path / "home").mkdir()
    app = create_app(tmp_path / "data", env={}, home=tmp_path / "home",
                     ner=NerModel(NerConfig(model_dir=tmp_path / "nothing")))
    web = Session(app)
    assert "name model is not installed" in web.get("/").text
    cid = new_client(web)
    r = web.post(f"/clients/{cid}/intake", {"text": fixture_text(1), "call_date": "2026-11-02"})
    assert "Scrubbing is blocked" in r.text


def test_outgoing_message_is_scrubbed_before_copy(web):
    cid = new_client(web)
    tx = scrub_and_save(web, cid, fixture_text(1))
    body = {"text": "Please also note that Maria Lopez lives at 14 Oak Lane and email maria@example.org.",
            "kind": "correction", "tx_id": tx}
    pre = web.post_json(f"/clients/{cid}/outgoing/preview", body).json()
    shown = "".join(t for t, _ in pre["segments"])
    assert "Maria Lopez" not in shown and "maria@example.org" not in shown and shown.startswith(f"[CLIENT: {cid}")
    assert "[CORRECTION]" in shown
    r = web.post_json(f"/clients/{cid}/outgoing/copy", body)
    if r.status_code == 409:                                      # unflagged words need an explicit yes
        body["confirm"] = "1"
        r = web.post_json(f"/clients/{cid}/outgoing/copy", body)
    assert r.status_code == 200 and "Maria Lopez" not in r.json()["text"]
    bad = web.post_json(f"/clients/{cid}/outgoing/preview", {"text": "x", "kind": "correction", "tx_id": ""}).json()
    assert "needs the transcript" in bad["error"]


def test_import_without_header_needs_a_pick_and_other_clients_are_refused(web):
    cid = new_client(web)
    tx = scrub_and_save(web, cid, fixture_text(1))
    other = new_client(web, "Kevin")
    r = web.post(f"/clients/{cid}/import", {"text": "Plain reply for [PERSON_1]"})
    assert "No usable header" in r.text
    r = web.post(f"/clients/{cid}/import", {"text": f"[CLIENT: {other} | TX: {tx}]\nhello"})
    assert f"not {cid}" in r.text
    r = web.post(f"/clients/{cid}/import/save", {"content": "Plain reply", "kind": "output", "tx_id": ""})
    assert "Pick the transcript" in r.text
    web.post(f"/clients/{cid}/import/save", {"content": "A summary of [PERSON_1]", "kind": "summary"})
    assert "A summary of" in web.get(f"/clients/{cid}").text


def test_real_values_in_a_reply_are_replaced_before_storing(web):
    cid = new_client(web)
    tx = scrub_and_save(web, cid, fixture_text(1))
    chk = web.post(f"/clients/{cid}/import", {"text": f"[CLIENT: {cid} | TX: {tx}]\nMaria Lopez agreed. Ms. Lopez will call."})
    assert "replaced with hidden names" in chk.text
    content = re.search(r'<textarea name="content"[^>]*>(.*?)</textarea>', chk.text, re.S).group(1)
    assert "Lopez" not in content


def test_registry_editor_edit_merge_delete(web):
    cid = new_client(web)
    scrub_and_save(web, cid, fixture_text(1))
    page = web.get(f"/clients/{cid}/registry")
    assert "Maria Lopez" in page.text and "[PERSON_1]" in page.text
    r = web.post(f"/clients/{cid}/registry/add", {"type": "PERSON", "value": "Mariah Lopes"}, follow_redirects=False)
    assert r.status_code == 303
    page = web.get(f"/clients/{cid}/registry")
    n = re.search(r"Mariah Lopes", page.text) and max(int(x) for x in re.findall(r"\[PERSON_(\d+)\]", page.text))
    r = web.post(f"/clients/{cid}/registry/merge", {"type": "PERSON", "n": str(n), "into": "1"}, follow_redirects=False)
    assert r.status_code == 303 and "merged into PERSON_1" in web.get(f"/clients/{cid}/registry").text
    r = web.post(f"/clients/{cid}/registry/edit", {"type": "PERSON", "n": "1", "part": "full", "value": "Maria Lopez-Diaz"},
                 follow_redirects=False)
    assert r.status_code == 303 and "Maria Lopez-Diaz" in web.get(f"/clients/{cid}/registry").text
    clash = web.post(f"/clients/{cid}/registry/edit", {"type": "PERSON", "n": "1", "part": "first", "value": "Sam"})
    assert "already belongs" in clash.text
    web.post(f"/clients/{cid}/registry/delete", {"type": "PERSON", "n": "1"})
    assert "Maria Lopez-Diaz" not in web.get(f"/clients/{cid}/registry").text


def test_settings_export_and_archive(web):
    cid = new_client(web)
    tx = scrub_and_save(web, cid, fixture_text(1))
    r = web.post("/settings", {"threshold": "0.6", "idle_minutes": "5"}, follow_redirects=False)
    assert r.status_code == 303
    s = web.get("/settings").text
    assert 'value="0.6"' in s
    assert "between 0.05" in web.post("/settings", {"threshold": "5", "idle_minutes": "5"}).text
    md = web.post(f"/clients/{cid}/export")
    assert "attachment" in md.headers["content-disposition"] and "Maria Lopez" in md.text and tx in md.text
    web.post(f"/clients/{cid}/archive")
    home = web.get("/").text
    assert "No clients yet" in home and "Archived (1)" in home        # still reachable, in its own list
    page = web.get(f"/clients/{cid}").text
    assert "Restore client" in page
    web.post(f"/clients/{cid}/archive")
    assert "Archive client" in web.get(f"/clients/{cid}").text and "Archived (" not in web.get("/").text


def test_browser_style_crlf_line_endings_work_end_to_end(web):
    cid = new_client(web)
    crlf = fixture_text(1).replace("\n", "\r\n")
    r = web.post(f"/clients/{cid}/intake", {"text": crlf, "call_date": "2026-11-02"})
    assert "Review before saving" in r.text
    form = review_form(r.text)
    form["text"] = form["text"].replace("\n", "\r\n") if "\r" not in form["text"] else form["text"]
    r = web.post(f"/clients/{cid}/intake/save", form, follow_redirects=False)
    assert r.status_code == 303
    tx = saved_tx(r)
    copied = web.post_json(f"/transcripts/{tx}/copy", {"outputs": ["clio-note"]}).json()["text"]
    assert "Lopez" not in copied and f"[CLIENT: {cid}" in copied
    reply = f"[CLIENT: {cid} | TX: {tx}]\r\nHello [PERSON_2]\r\nline two"
    chk = web.post(f"/clients/{cid}/import", {"text": reply, "output": "clio-form-note"})
    assert re.search(r"Belongs to Untitled, \d+ \w{3} \d{4}\.", chk.text) and "Maria Lopez" in chk.text


def test_latest_version_endpoint_returns_only_a_number(web):
    cid = new_client(web)
    tx = scrub_and_save(web, cid, fixture_text(1))
    assert web.get(f"/transcripts/{tx}/latest").json() == {"version": 0}
    from app.store import Store
    app = web.c.app
    with Store.open(app.state.data_dir, env={}, home=app.state.home) as s:
        s.add_output(cid, tx, "clio-note", "Secret [PERSON_1]", "mcp")
    assert web.get(f"/transcripts/{tx}/latest").json() == {"version": 1}
    assert 'data-poll="/transcripts/' in web.get(f"/transcripts/{tx}").text
