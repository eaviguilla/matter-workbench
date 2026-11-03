import io
import json

import pytest

from app.store import Store
from app import workflow as wf
from mcp_server.server import MAX_BYTES, TOOL, handle, serve
from tests.webhelp import Session, fixture_text, make_app, review_form, saved_tx


@pytest.fixture
def env(tmp_path):
    web = Session(make_app(tmp_path))
    cid = web.post("/clients", {"first_name": "Maria"}, follow_redirects=False).headers["location"].rsplit("/", 1)[1]
    r = web.post(f"/clients/{cid}/intake", {"text": fixture_text(1), "call_date": "2026-11-02"})
    tx = saved_tx(web.post(f"/clients/{cid}/intake/save", review_form(r.text), follow_redirects=False))
    app = web.c.app
    opener = lambda: Store.open(app.state.data_dir, env={}, home=app.state.home)  # noqa: E731
    return opener, cid, tx


def call(opener, **args):
    reply = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "save_output", "arguments": args}}, opener)
    return reply["result"]["content"][0]["text"], reply["result"]["isError"]


def enable(opener, on=True):
    with opener() as s:
        cfg = wf.load_settings(s)
        cfg.mcp_enabled = on
        wf.save_settings(s, cfg)


def versions(opener, tx, output="clio-note"):
    with opener() as s:
        return [o["version"] for o in s.list_outputs(tx, output)]


def test_off_by_default_then_saves_versions(env):
    opener, cid, tx = env
    text, err = call(opener, client_id=cid, transcript_id=tx, output="clio-note", content="Hello [PERSON_1]")
    assert err and "turned off" in text and versions(opener, tx) == []
    enable(opener)
    assert call(opener, client_id=cid, transcript_id=tx, output="clio-note", content="Hello [PERSON_1]") == ("saved clio-note v1", False)
    assert call(opener, client_id=cid, transcript_id=tx, output="clio-note", content="Hello again") == ("saved clio-note v2", False)
    assert versions(opener, tx) == [1, 2]
    with opener() as s:
        assert {o["source"] for o in s.list_outputs(tx, "clio-note")} == {"mcp"}


@pytest.mark.parametrize("args,reason", [
    ({"client_id": "nope", "transcript_id": "TX-20261102-1", "output": "clio-note", "content": "x"}, "client_id"),
    ({"client_id": "CID", "transcript_id": "TX-20261102-1", "output": "reply", "content": "x"}, "output"),
    ({"client_id": "CID", "transcript_id": "TX-20261102-1", "output": "../clio-note", "content": "x"}, "output"),
    ({"client_id": "CID", "transcript_id": "TX-20261102-1", "output": 5, "content": "x"}, "output"),
    ({"client_id": "CID", "transcript_id": "TX-20261102-1", "content": "x"}, "output"),
    ({"client_id": "CID", "transcript_id": "nope", "output": "clio-note", "content": "x"}, "transcript_id"),
    ({"client_id": "CID", "transcript_id": "TX-20261102-1", "output": "clio-note", "content": ""}, "empty"),
    ({"client_id": "CID", "transcript_id": "TX-20261102-1", "output": "clio-note", "content": 5}, "empty"),
    ({"client_id": "Ghost-20261102-1", "transcript_id": "TX-20261102-1", "output": "clio-note", "content": "x"}, "unknown"),
    ({"client_id": "CID", "transcript_id": "TX-20990101-9", "output": "clio-note", "content": "x"}, "unknown"),
    ({"client_id": "CID", "transcript_id": "TX-20261102-1", "output": "clio-note", "content": "x" * (MAX_BYTES + 1)}, "200 KB"),
    ({"transcript_id": "TX-20261102-1", "output": "clio-note", "content": "x"}, "client_id"),
])
def test_bad_input_is_rejected(env, args, reason):
    opener, cid, tx = env
    enable(opener)
    assert tx == "TX-20261102-1"            # the call date is typed in the fixture, the client ID date is today's
    args = {k: cid if v == "CID" else v for k, v in args.items()}
    text, err = call(opener, **args)
    assert err and text.startswith("rejected") and reason in text
    assert versions(opener, tx) == []


def test_a_transcript_of_another_client_is_rejected(env):
    opener, cid, tx = env
    enable(opener)
    with opener() as s:
        other = s.create_client("Kevin")
    text, err = call(opener, client_id=other, transcript_id=tx, output="clio-note", content="x")
    assert err and "do not belong together" in text


def test_a_mismatched_header_is_rejected_and_known_values_are_masked(env):
    opener, cid, tx = env
    enable(opener)
    text, err = call(opener, client_id=cid, transcript_id=tx, output="clio-note", content="[CLIENT: Kevin-20261102-1 | TX: TX-20261102-1]\nx")
    assert err and "header" in text
    assert call(opener, client_id=cid, transcript_id=tx, output="clio-note", content="Maria Lopez agreed.")[1] is False
    with opener() as s:
        assert "Lopez" not in s.list_outputs(tx, "clio-note")[-1]["content"]


def test_exactly_one_write_only_tool_and_no_reply_holds_stored_data(env):
    opener, cid, tx = env
    enable(opener)
    listing = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, opener)["result"]["tools"]
    assert listing == [TOOL] and set(TOOL["inputSchema"]["properties"]) == {"client_id", "transcript_id", "output", "content"}
    for method in ("resources/list", "resources/read", "prompts/list", "tools/read", "tools/search"):
        assert "error" in handle({"jsonrpc": "2.0", "id": 2, "method": method}, opener)
    reply = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_clients"}}, opener)
    assert "error" in reply
    text, _ = call(opener, client_id=cid, transcript_id=tx, output="clio-note", content="secret-looking content [PERSON_1]")
    assert text == "saved clio-note v1"


def test_stdio_loop(env):
    opener, cid, tx = env
    enable(opener)
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
             json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
             "not json",
             json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                         "params": {"name": "save_output", "arguments": {"client_id": cid, "transcript_id": tx, "output": "clio-note", "content": "ok"}}})]
    out = io.StringIO()
    serve(opener, io.StringIO("\n".join(lines) + "\n"), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, None, 2]
    assert replies[0]["result"]["serverInfo"]["name"] == "matter-workbench"
    assert replies[1]["error"]["code"] == -32700 and replies[2]["result"]["content"][0]["text"] == "saved clio-note v1"


def test_data_unavailable_is_a_rejection_not_a_crash(tmp_path):
    def opener():
        return Store.open(tmp_path / "missing", env={}, home=tmp_path)
    # a fresh data folder has the connector off
    text, err = call(opener, client_id="Maria-20261102-1", transcript_id="TX-20261102-1", output="clio-note", content="x")
    assert err and "turned off" in text
