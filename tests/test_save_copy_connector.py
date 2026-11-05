"""Bugs found by breaking the forms, save and discard, Copy for Clio, the extension and the connector.

Each test failed before its fix. The extension twin-title case is in test_clio_filler.py.
"""
import io
import json

import pytest

from app import forms, workflow as wf
from app.outputs import FORM_SLUGS, TEXT_SLUGS
from mcp_server.server import handle, save_output, serve
from tests.test_mcp import enable
from tests.test_outputs import do_import, env, store_of  # noqa: F401  (env is a fixture)

PRO, EST, GEN, TRU = FORM_SLUGS
NOTE = TEXT_SLUGS[0]


def reply(cid, tx, slug, body):
    return f"[CLIENT: {cid} | TX: {tx}]\n[OUTPUT: {slug}]\n{body}"


def versions(web, tx, slug):
    with store_of(web) as s:
        return [o["content"] for o in s.list_outputs(tx, slug)]


def answers(web, tx, slug):
    return forms.parse(slug, versions(web, tx, slug)[-1]).answers


def edit_fields(web, answers_by_n):
    return {"csrf": web.token, **{f"answer_{n}": t for n, t in answers_by_n.items()}}


# Importing and saving ---------------------------------------------------------------------------------------------

def test_saving_the_same_import_twice_adds_one_version(env):
    web, cid, tx, tmp = env
    chk = web.post(f"/clients/{cid}/import", {"text": reply(cid, tx, NOTE, "Same note body.")})
    body = {"content": chk.text.split("<textarea")[1].split(">", 1)[1].split("</textarea>")[0], "kind": "output"}
    import html
    body["content"] = html.unescape(body["content"]).lstrip("\n")
    web.post(f"/clients/{cid}/import/save", body, follow_redirects=False)
    web.post(f"/clients/{cid}/import/save", body, follow_redirects=False)
    assert len(versions(web, tx, NOTE)) == 1


def test_connector_resending_the_same_output_adds_no_version(env):
    web, cid, tx, tmp = env
    op = lambda: store_of(web)
    enable(op)
    args = {"client_id": cid, "transcript_id": tx, "output": NOTE, "content": "Same note body."}
    assert save_output(op, args) == ("saved clio-note v1", False)
    text, err = save_output(op, args)
    assert not err and "unchanged" in text
    assert len(versions(web, tx, NOTE)) == 1


# The page editor (no JavaScript) ----------------------------------------------------------------------------------

def test_a_form_page_edit_that_started_from_an_old_version_is_refused(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, EST, "[ANSWER: 1]\nYes\n\n[ANSWER: 2]\nAnna"))
    with store_of(web) as s:
        s.add_output(cid, tx, EST, forms.merge(EST, versions(web, tx, EST)[-1], {2: "Beatrice"}), "mcp")
    r = web.post(f"/transcripts/{tx}/outputs/{EST}/edit?v=1", edit_fields(web, {1: "Yes", 2: "Anna", 5: "Yes"}),
                 follow_redirects=False)
    assert r.status_code == 200 and "newer version" in r.text
    assert len(versions(web, tx, EST)) == 2 and answers(web, tx, EST)[2] == "Beatrice"
    assert "Yes" in r.text, "the typed answers stay on the page"


def test_a_text_page_edit_that_started_from_an_old_version_is_refused(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, NOTE, "first body"))
    with store_of(web) as s:
        s.add_output(cid, tx, NOTE, "second body from claude", "mcp")
    r = web.post(f"/transcripts/{tx}/outputs/{NOTE}/edit?v=1", {"content": "first body edited", "csrf": web.token},
                 follow_redirects=False)
    assert r.status_code == 200 and "newer version" in r.text
    assert versions(web, tx, NOTE) == ["first body", "second body from claude"]


def test_a_page_edit_saves_only_the_answers_that_changed(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, EST, "[ANSWER: 1]\nYes\n\n[ANSWER: 2]\nAnna\n\n[ANSWER: 4]\nYes"))
    # Question 2 is typed back with a trailing space and a different line ending. That is not a change.
    r = web.post(f"/transcripts/{tx}/outputs/{EST}/edit?v=1", edit_fields(web, {1: "Yes", 2: "Anna \r\n", 4: "No"}),
                 follow_redirects=False)
    assert r.status_code == 303
    got = answers(web, tx, EST)
    assert got[4] == "No" and got[2] == "Anna" and got[1] == "Yes"


def test_an_untouched_page_edit_says_nothing_changed(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, EST, "[ANSWER: 1]\nYes\n\n[ANSWER: 2]\nAnna"))
    r = web.post(f"/transcripts/{tx}/outputs/{EST}/edit?v=1", edit_fields(web, {1: "Yes", 2: "Anna"}),
                 follow_redirects=False)
    assert r.status_code == 200 and "Nothing changed" in r.text
    assert len(versions(web, tx, EST)) == 1


def test_not_discussed_survives_a_page_edit_of_another_answer(env):
    web, cid, tx, tmp = env
    do_import(web, cid, reply(cid, tx, EST, "[ANSWER: 4]\nNot discussed\n\n[ANSWER: 6]\nYes"))
    page = web.get(f"/transcripts/{tx}/outputs/{EST}/edit").text
    assert "Not discussed</option>" in page, "the Yes or No box offers the stored answer"
    r = web.post(f"/transcripts/{tx}/outputs/{EST}/edit?v=1", edit_fields(web, {4: "Not discussed", 6: "No"}),
                 follow_redirects=False)
    assert r.status_code == 303
    got = answers(web, tx, EST)
    assert got[4].lower().startswith("not discussed") and got[6] == "No"


# Form warnings ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, ok", [("03/14/2024", True), ("3/4/2024", True), ("13/45/2020", False),
                                      ("02/30/2020", False), ("March 4", False), ("2024-03-14", False),
                                      ("Not discussed", True), ("", True)])
def test_a_date_answer_that_clio_cannot_read_is_flagged(text, ok):
    assert (forms.choice_problem(PRO, 5, text) == "") is ok


# Routes ----------------------------------------------------------------------------------------------------------

def test_starting_an_intake_with_nothing_pasted_asks_again_instead_of_failing(env):
    web, cid, tx, tmp = env
    r = web.post("/intake/start", {"text": "", "call_date": "", "client": "", "first_name": ""})
    assert r.status_code == 200 and "Something went wrong" not in r.text


def test_a_json_route_given_a_form_body_answers_400(env):
    web, cid, tx, tmp = env
    for url in (f"/transcripts/{tx}/hide-word", f"/transcripts/{tx}/outputs/{NOTE}/request-change"):
        assert web.post(url, {"text": "hi"}).status_code == 400, url


# Connector --------------------------------------------------------------------------------------------------------

def run(web, lines):
    out = io.StringIO()
    serve(lambda: store_of(web), io.StringIO("\n".join(lines) + "\n"), out)
    return [json.loads(x) for x in out.getvalue().splitlines()]


@pytest.mark.parametrize("params", [
    {"name": "save_output", "arguments": "abc"}, {"name": "save_output", "arguments": [1, 2]}, [1], "x", 5,
    {"name": ["save_output"]},
])
def test_a_tool_call_with_bad_params_gets_an_error_with_its_own_id(env, params):
    web, cid, tx, tmp = env
    got = run(web, [json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": params})])
    assert got[0]["id"] == 7 and got[0]["error"]["code"] == -32602


@pytest.mark.parametrize("msg", ['[1,2]', '"x"', '5', 'null', '{"id": 3}', '{"id": 3, "method": 5}',
                                 '{"id": {"a":1}, "method": "ping"}'])
def test_odd_messages_never_stop_the_loop(env, msg):
    web, cid, tx, tmp = env
    got = run(web, [msg, json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"})])
    assert got[-1]["id"] == 9 and "result" in got[-1]


def test_an_unexpected_error_in_one_call_does_not_end_the_session(env, monkeypatch):
    web, cid, tx, tmp = env
    enable(lambda: store_of(web))
    monkeypatch.setattr(wf, "save_import", lambda *a, **k: (_ for _ in ()).throw(KeyError("boom")))
    call = {"name": "save_output", "arguments": {"client_id": cid, "transcript_id": tx, "output": NOTE, "content": "hello"}}
    got = run(web, [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": call}),
                    json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})])
    assert [r["id"] for r in got] == [1, 2]
    assert got[0]["error"]["code"] == -32603 and "boom" not in json.dumps(got[0])


def test_a_rejected_form_reply_says_why(env):
    web, cid, tx, tmp = env
    op = lambda: store_of(web)
    enable(op)
    text, err = save_output(op, {"client_id": cid, "transcript_id": tx, "output": PRO, "content": "no markers here"})
    assert err and text != "rejected: could not save" and text.startswith("rejected: ")


def test_the_tool_description_reads_cleanly():
    from mcp_server.server import TOOL
    assert "intake forms, write each answer" in TOOL["inputSchema"]["properties"]["content"]["description"]
    assert handle({"id": 1, "method": "tools/list"}, None)["result"]["tools"] == [TOOL]


# Copy for Clio text ------------------------------------------------------------------------------------------------

import shutil
import subprocess
from pathlib import Path


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the extension's reader")
@pytest.mark.parametrize("answer", ["a\n ---\nb", " ---", "a\n  --- 3. x\nb", "--- End of answers\nz", "x\n-----\ny"])
def test_an_answer_with_lines_that_look_like_separators_reads_back_unchanged(answer):
    rows = [dict(n=1, question="Q?", text=answer, state="answered", fold=False)]
    text = wf.clio_text(PRO, rows, "Ana", "2026-01-01", 1)
    reader = Path(__file__).resolve().parents[1] / "clio_filler" / "parse.js"
    code = f"const r = require({json.dumps(str(reader))}).parse(JSON.parse(process.argv[1])); console.log(JSON.stringify(r.answers));"
    out = subprocess.run(["node", "-e", code, json.dumps(text)], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [{"n": 1, "question": "Q?", "text": answer.strip()}]


# Saving the same call twice ------------------------------------------------------------------------------------------

def test_saving_the_same_call_again_keeps_the_title_outputs_and_directions_from_the_second_review(tmp_path):
    from datetime import date
    from tests.test_saving import ner, reopen_new
    s = reopen_new(tmp_path)
    cid = s.create_client("Pat", pending=True)
    call = "Pat: hello there\nStaff: hi"
    first = wf.save_transcript(s, cid, call, date(2026, 3, 10), ner(), wf.Settings(), (), outputs=(NOTE,))
    again = wf.save_transcript(s, cid, call, date(2026, 3, 10), ner(), wf.Settings(), (), title="Intake call",
                               outputs=(NOTE, PRO), directions="focus on dates")
    assert again == first and len(s.list_transcripts(cid)) == 1
    row = s.get_transcript(first)
    assert row["title"] == "Intake call" and row["planned_outputs"] == [NOTE, PRO]
    assert row["directions"] == "focus on dates"
    # a third save with nothing new clears nothing
    wf.save_transcript(s, cid, call, date(2026, 3, 10), ner(), wf.Settings(), ())
    row = s.get_transcript(first)
    assert row["title"] == "Intake call" and row["directions"] == "focus on dates"
