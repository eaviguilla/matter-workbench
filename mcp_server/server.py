"""One tool, save_output(client_id, transcript_id, output, content), over MCP's stdio transport (JSON lines).

Write-only: no tool reads, lists or searches anything, and no reply contains stored data. It writes through
the same code as the Import box, so known real values are replaced with placeholders before saving.
"""
import json
import sys
from collections.abc import Callable
from typing import TextIO

from app import workflow as wf
from app.store import Busy, Damaged, Store, StoreTooNew
from app.ids import CLIENT_ID_RE, TX_ID_RE
from app.outputs import NAMES, SLUGS
from app.paths import UnsafeLocation

MAX_BYTES = 200_000
PROTOCOL = "2024-11-05"
TOOL = {
    "name": "save_output",
    "description": "Save one output you produced for a transcript as a new version in the local Matter Workbench. "
                   "Call it once per output. Write-only. Returns only the saved version number or a rejection reason.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "client_id": {"type": "string", "description": "The client ID from the header line."},
            "transcript_id": {"type": "string", "description": "The transcript ID from the header line."},
            "output": {"type": "string", "enum": list(SLUGS),
                       "description": "Which output this is: " + "; ".join(f"{slug} is {name}" for slug, name in NAMES.items()) + "."},
            "content": {"type": "string", "description": "The full output, placeholders unchanged. For the two intake forms, "
                           "write each answer under a line that reads exactly [ANSWER: <question number>]. Questions left out keep "
                           "their earlier answer."},
        },
        "required": ["client_id", "transcript_id", "output", "content"],
        "additionalProperties": False,
    },
}


def save_output(open_store: Callable[[], Store], args: dict) -> tuple[str, bool]:
    """Returns (message, is_error). The message never contains stored or submitted content."""
    client_id, tx_id, content = args.get("client_id"), args.get("transcript_id"), args.get("content")
    output = args.get("output")
    if not (isinstance(client_id, str) and CLIENT_ID_RE.match(client_id)):
        return "rejected: client_id is not a valid client ID", True
    if not (isinstance(tx_id, str) and TX_ID_RE.match(tx_id)):
        return "rejected: transcript_id is not a valid transcript ID", True
    if not (isinstance(output, str) and output in NAMES):
        return "rejected: output is not a known output", True
    if not isinstance(content, str) or not content.strip():
        return "rejected: content is empty", True
    if len(content.encode("utf-8")) > MAX_BYTES:
        return "rejected: content is over 200 KB", True
    try:
        store = open_store()
    except (UnsafeLocation, Damaged, StoreTooNew):
        return "rejected: the workbench data is not available", True
    with store:
        if not wf.load_settings(store).mcp_enabled:
            return "rejected: the connector is turned off in the workbench settings", True
        row = store.get_transcript(tx_id)
        if store.get_client(client_id) is None or row is None or row["client_id"] != client_id:
            return "rejected: unknown client or transcript, or they do not belong together", True
        try:
            check = wf.check_import(store, client_id, content, tx_id, wf.load_settings(store).keep_first_names,
                                    output, markers=False)
            if check.problem:
                return "rejected: the header line in content does not match these IDs", True
            version = wf.save_import(store, client_id, check, "output", "mcp")
        except (wf.ImportProblem, Busy, Damaged):
            return "rejected: could not save", True
        return f"saved {version}", False


def handle(message: dict, open_store: Callable[[], Store]) -> dict | None:
    """One JSON-RPC message in, one reply out (None for notifications)."""
    method, mid = message.get("method"), message.get("id")
    if mid is None:
        return None
    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "matter-workbench", "version": "0.1.0"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [TOOL]})
    if method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") != TOOL["name"]:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        text, is_error = save_output(open_store, params.get("arguments") or {})
        return ok({"content": [{"type": "text", "text": text}], "isError": is_error})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}


def serve(open_store: Callable[[], Store], stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line), open_store)
        except (ValueError, AttributeError):
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
