"""File storage: one folder per client, one folder per call.

    settings.json, audit.jsonl, .lock
    clients/<client id>/client.json
    clients/<client id>/transcripts/<transcript id>/transcript.txt and one JSON file per output

client.json holds the real values in plain text, so nothing outside this computer may read it. No method here takes
an original transcript or a rehydrated output, so there is no path by which one could be stored.

A save is safe against a crash because of the order of the writes. A new transcript's folder is written first and
counts only once client.json lists it. client.json is then replaced by one rename, and that is the moment of the save.
Existing text and output files are replaced after it, so they never refer to a placeholder client.json lacks.
"""
import hashlib
import json
import os
import secrets
import shutil
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .outputs import SLUGS, is_slug
from .ids import CLIENT_ID_RE, TX_ID_RE, make_client_id, make_transcript_id
from .paths import AUDIT_NAME, CLIENT_FILE, CLIENTS_DIR, LOCK_NAME, SETTINGS_NAME, TRANSCRIPT_FILE, TRANSCRIPTS_DIR, prepare_data_dir
from .scrub.registry import Registry, canonical_email, norm

SCHEMA = 1
STATUSES = ("draft", "reviewed", "copied")
MESSAGE_KINDS = ("transcript", "correction", "comment", "summary")
OUTPUT_SOURCES = ("import", "mcp", "edit", "hide", "unhide")
DECISIONS = ("scrub", "keep")
_TMP = ".tmp"
_TRASH = ".trash-"


class Damaged(Exception):
    """A stored file cannot be read. The message names the file and never its contents."""

    def __init__(self, path: Path, why: str):
        super().__init__(f"{path} cannot be read: {why}")
        self.path, self.why = path, why


class StoreTooNew(Exception):
    """The file was written by a newer version of the app."""


class Busy(Exception):
    """Another copy of the app or the connector kept the write lock too long."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _retry(action: Callable):
    """Windows refuses a rename or read for a moment while a scanner or editor has the file open."""
    for attempt in range(20):
        try:
            return action()
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.1)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f"{path.name}.{os.getpid()}{_TMP}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(text.encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    _retry(lambda: os.replace(tmp, path))
    if os.name == "posix":      # the rename itself must reach the disk too
        d = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(d)
        finally:
            os.close(d)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(_retry(lambda: path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:       # its message gives the position only; e.doc would hold the contents
        raise Damaged(path, f"not valid JSON at line {e.lineno}, column {e.colno}") from None
    except UnicodeDecodeError:
        raise Damaged(path, "not valid UTF-8") from None
    if not isinstance(data, dict):
        raise Damaged(path, "the top level is not an object")
    if data.get("schema", 1) > SCHEMA:
        raise StoreTooNew(f"{path} was written by a newer version of this app.")
    return data


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


class _Lock:
    """One lock for all writers. The operating system releases it if the process dies, so a crash cannot leave it stuck."""

    def __init__(self, path: Path, timeout: float):
        self.path, self.timeout, self.fd = path, timeout, None

    def _try(self) -> bool:
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        import fcntl
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        end = time.monotonic() + self.timeout
        while not self._try():
            if time.monotonic() >= end:
                os.close(self.fd)
                self.fd = None
                raise Busy("The workbench is busy saving. Try again in a moment.")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        if os.name == "nt":
            import msvcrt
            os.lseek(self.fd, 0, os.SEEK_SET)
            msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        os.close(self.fd)       # closing releases the flock
        self.fd = None


class Store:
    fault: Callable[[str], None] | None = None      # tests use this to stop a save at a named step

    def __init__(self, folder: Path, clock: Callable[[], datetime] = _now, lock_timeout: float = 10.0):
        self.folder, self._clock, self._lock_timeout = folder, clock, lock_timeout
        self.damaged: list[str] = []
        self._depth = 0
        self._reset()

    def _reset(self) -> None:
        self._docs: dict = {}           # client documents read in this transaction
        self._dirty: set = set()
        self._forgotten: set = set()
        self._gone_tx: list = []        # transcript folders removed after client.json no longer lists them
        self._new_files: dict = {}      # written before client.json
        self._later_files: dict = {}    # written after client.json
        self._settings: dict | None = None
        self._settings_dirty = False
        self._audits: list = []

    @classmethod
    def open(cls, data_dir: Path | None = None, env=None, home: Path | None = None,
             clock: Callable[[], datetime] = _now, lock_timeout: float = 10.0) -> "Store":
        folder = prepare_data_dir(data_dir, env, home)
        store = cls(folder, clock, lock_timeout)
        store._read_settings()          # a damaged or too-new settings file stops the app here
        return store

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- transactions ------------------------------------------------------------------------

    @contextmanager
    def _tx(self):
        """One transaction. Nested uses join the outer one, so a multi-step save commits or is dropped as a whole.
        Nothing reaches the disk until the outermost one ends. It covers one client, the most any save touches."""
        if self._depth:
            self._depth += 1
            try:
                yield self
            finally:
                self._depth -= 1
            return
        with _Lock(self.folder / LOCK_NAME, self._lock_timeout):
            self._depth = 1
            try:
                yield self
                self._commit()
            finally:
                self._depth = 0
                self._reset()

    transaction = _tx

    def _step(self, name: str) -> None:
        if Store.fault:
            Store.fault(name)

    def _commit(self) -> None:
        dirty = self._dirty - self._forgotten
        if len(dirty) > 1:
            raise RuntimeError("One transaction cannot change two clients.")
        for path, text in self._new_files.items():
            write_atomic(path, text)
            self._step("new_file")
        self._step("before_client")
        for cid in dirty:
            write_atomic(self._client_file(cid), _dump(self._docs[cid]))
        self._step("after_client")
        for path, text in self._later_files.items():
            write_atomic(path, text)
            self._step("later_file")
        if self._settings_dirty:
            write_atomic(self.folder / SETTINGS_NAME, _dump(self._settings))
        for cid in self._forgotten:
            self._remove_client_folder(cid)
        for folder in self._gone_tx:
            self._remove_folder(folder)
        audits, self._audits = self._audits, []
        for line in audits:
            self._append_audit(line)

    def _remove_client_folder(self, cid: str) -> None:
        self._remove_folder(self._client_dir(cid))

    def _remove_folder(self, folder: Path) -> None:
        if folder.exists():
            trash = folder.with_name(_TRASH + folder.name)
            _retry(lambda: os.replace(folder, trash))
            shutil.rmtree(trash, ignore_errors=True)

    def clean_up(self) -> None:
        """Remove what a crash can leave: temporary files, unlisted transcript folders, half-made client folders.
        A client whose client.json cannot be read is left exactly as it is."""
        with _Lock(self.folder / LOCK_NAME, self._lock_timeout):
            for tmp in self.folder.rglob(f"*{_TMP}"):
                tmp.unlink(missing_ok=True)
            root = self.folder / CLIENTS_DIR
            if not root.is_dir():
                return
            for folder in root.iterdir():
                if folder.name.startswith(_TRASH):
                    shutil.rmtree(folder, ignore_errors=True)
                elif folder.is_dir() and not (folder / CLIENT_FILE).exists():
                    if not any(p.is_file() for p in folder.rglob("*")):
                        shutil.rmtree(folder, ignore_errors=True)
                elif folder.is_dir():
                    try:
                        listed = _read_json(folder / CLIENT_FILE).get("transcripts", {})
                    except (Damaged, StoreTooNew):
                        continue
                    for tx in (folder / TRANSCRIPTS_DIR).glob("*"):
                        if tx.is_dir() and tx.name not in listed:
                            shutil.rmtree(tx, ignore_errors=True)

    # ---- paths and documents -----------------------------------------------------------------

    def _client_dir(self, cid: str) -> Path:
        if not CLIENT_ID_RE.fullmatch(cid):     # the ID came from a URL or a reply, and it is about to become a path
            raise ValueError("malformed client ID")
        return self.folder / CLIENTS_DIR / cid

    def _client_file(self, cid: str) -> Path:
        return self._client_dir(cid) / CLIENT_FILE

    def _tx_dir(self, cid: str, tx_id: str) -> Path:
        if not TX_ID_RE.fullmatch(tx_id):
            raise ValueError("malformed transcript ID")
        return self._client_dir(cid) / TRANSCRIPTS_DIR / tx_id

    def _client_ids(self) -> list[str]:
        root = self.folder / CLIENTS_DIR
        found = {p.name for p in root.iterdir() if p.is_dir() and CLIENT_ID_RE.fullmatch(p.name)} if root.is_dir() else set()
        return sorted((found | set(self._docs)) - self._forgotten)

    def _doc(self, cid: str) -> dict | None:
        """The client's document, or None if there is none. Files are read afresh outside a transaction, because
        the connector is a separate process. Inside one the same copy is kept, with this transaction's changes."""
        if not CLIENT_ID_RE.fullmatch(cid) or cid in self._forgotten:
            return None
        if cid in self._docs:
            return self._docs[cid]
        path = self._client_file(cid)
        if not path.is_file():
            return None
        doc = _read_json(path)
        for key, kind in (("id", str), ("first_name", str), ("created_at", str), ("transcripts", dict),
                          ("messages", list), ("registry", dict), ("settings", dict)):
            if not isinstance(doc.get(key), kind):
                raise Damaged(path, f"the field {key} is missing or has the wrong type")
        if doc["id"] != cid:            # a folder name differing in case only, on a disk that ignores case
            return None
        if self._depth:
            self._docs[cid] = doc
        return doc

    def _edit(self, cid: str) -> dict:
        """The document, to change inside a transaction."""
        doc = self._doc(cid)
        if doc is None:
            raise KeyError(cid)
        self._dirty.add(cid)
        return doc

    def _read_settings(self) -> dict:
        if self._settings is not None:
            return self._settings
        path = self.folder / SETTINGS_NAME
        data = _read_json(path) if path.exists() else {"schema": SCHEMA, "settings": {}}
        if not isinstance(data.get("settings"), dict):
            raise Damaged(path, "the field settings is missing or has the wrong type")
        if self._depth:
            self._settings = data
        return data

    def _text(self, path: Path) -> str:
        for staged in (self._new_files, self._later_files):
            if path in staged:
                return staged[path]
        try:
            return _retry(lambda: path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise Damaged(path, "the file is missing") from None
        except UnicodeDecodeError:
            raise Damaged(path, "not valid UTF-8") from None

    def _stamp(self) -> str:
        return self._clock().isoformat(timespec="seconds")

    # ---- settings (plain values, the per-client ones live with the client) ---------------------

    @staticmethod
    def _client_setting(name: str):
        parts = name.split(".", 2)
        return (parts[1], parts[2]) if len(parts) == 3 and parts[0] == "client" else None

    def get_setting(self, name: str, default: str | None = None) -> str | None:
        scoped = self._client_setting(name)
        if scoped:
            doc = self._doc(scoped[0])
            return doc["settings"].get(scoped[1], default) if doc else default
        return self._read_settings()["settings"].get(name, default)

    def set_setting(self, name: str, value: str) -> None:
        with self._tx():
            scoped = self._client_setting(name)
            if scoped:
                self._edit(scoped[0])["settings"][scoped[1]] = str(value)
                return
            self._read_settings()["settings"][name] = str(value)
            self._settings_dirty = True

    def form_secret(self) -> bytes:
        """Signs form tokens. It is kept, so a page left open across a restart can still save."""
        with self._tx():
            data = self._read_settings()
            if "form_secret" not in data:
                data["form_secret"] = secrets.token_hex(32)
                self._settings_dirty = True
            return bytes.fromhex(data["form_secret"])

    # ---- clients -----------------------------------------------------------------------------

    @staticmethod
    def _client_row(doc: dict) -> dict:
        return {"id": doc["id"], "first_name": doc["first_name"], "created_at": doc["created_at"],
                "archived": int(bool(doc.get("archived"))), "pending": int(bool(doc.get("pending")))}

    def create_client(self, first_name: str, added: date | None = None, pending: bool = False) -> str:
        """pending: made for a transcript that is not saved yet, so it is hidden until the first save."""
        added = added or self._clock().astimezone().date()       # the user's own day, like the call date field
        with self._tx():
            cid = make_client_id(first_name, added, self._client_ids())
            self._docs[cid] = {"schema": SCHEMA, "id": cid, "first_name": first_name.strip(), "created_at": self._stamp(),
                               "archived": False, "pending": bool(pending), "settings": {},
                               "registry": {"entities": [], "index": [], "high": {}}, "first_seen": {},
                               "transcripts": {}, "messages": [], "next_message": 1, "next_seq": 1}
            self._dirty.add(cid)
            self.audit("client_created", cid)
        return cid

    def rename_client(self, client_id: str, first_name: str) -> None:
        """Change the display name only. The ID keeps its original name so earlier chats still match."""
        if not first_name.strip():
            raise ValueError("first name is empty")
        with self._tx():
            self._edit(client_id)["first_name"] = first_name.strip()
            self.audit("client_renamed", client_id)

    def delete_empty_client(self, client_id: str) -> bool:
        """Remove a client that has no transcripts, messages or outputs, such as one made for a review that was
        never saved. Returns False and changes nothing when the client holds anything."""
        with self._tx():
            doc = self._doc(client_id)
            if doc is None or doc["transcripts"] or doc["messages"]:
                return False
            self._forgotten.add(client_id)
            self.audit("client_deleted_empty", client_id)
        return True

    def delete_client(self, client_id: str) -> bool:
        """Remove a client with everything it holds: transcripts, outputs, messages and the saved real values. There is
        no undo. Returns False when there is no such client."""
        with self._tx():
            if self._doc(client_id) is None:
                return False
            self._forgotten.add(client_id)
            self.audit("client_deleted", client_id)
        return True

    def delete_transcript(self, client_id: str, tx_id: str) -> bool:
        """Remove one transcript with its outputs and the messages copied for it. client.json stops listing it first,
        then the folder goes, so a crash leaves only an unlisted folder that clean_up removes. Returns False when the
        client does not list it."""
        with self._tx():
            doc = self._doc(client_id)
            if doc is None or tx_id not in doc["transcripts"]:
                return False
            doc = self._edit(client_id)
            del doc["transcripts"][tx_id]
            doc["messages"] = [m for m in doc["messages"] if m.get("transcript_id") != tx_id]
            self._gone_tx.append(self._tx_dir(client_id, tx_id))
            self.audit("transcript_deleted", client_id, tx_id)
        return True

    def activate_client(self, client_id: str) -> None:
        with self._tx():
            self._edit(client_id)["pending"] = False

    def purge_pending(self, older_than_minutes: int = 0) -> int:
        """Remove pending clients that never got a transcript, such as from a review that was abandoned."""
        cutoff = (self._clock() - timedelta(minutes=older_than_minutes)).isoformat(timespec="seconds")
        purged = 0
        with self._tx():
            for cid in self._client_ids():
                try:
                    doc = self._doc(cid)
                except Damaged:
                    continue
                if doc and doc.get("pending") and doc["created_at"] <= cutoff and not doc["transcripts"]:
                    self._forgotten.add(cid)
                    self.audit("client_purged_pending", cid)
                    purged += 1
        return purged

    def _all_docs(self) -> list[dict]:
        docs = []
        for cid in self._client_ids():
            try:
                doc = self._doc(cid)
            except Damaged:             # the other clients keep working, and the page says which one needs repair
                if cid not in self.damaged:
                    self.damaged.append(cid)
                continue
            if doc:
                docs.append(doc)
        return docs

    def list_clients(self, include_archived: bool = False) -> list[dict]:
        rows = [self._client_row(d) for d in self._all_docs()
                if not d.get("pending") and (include_archived or not d.get("archived"))]
        return sorted(sorted(rows, key=lambda r: r["id"]), key=lambda r: r["created_at"], reverse=True)

    def client_activity(self) -> dict:
        """client id -> time of the latest transcript, message or output (or creation)."""
        activity = {}
        for doc in self._all_docs():
            times = [doc["created_at"]]
            for t in doc["transcripts"].values():
                times += [t["created_at"], t.get("last_output_at") or ""]
            times += [m.get("copied_at") or "" for m in doc["messages"]]
            activity[doc["id"]] = max(times)
        return activity

    def get_client(self, client_id: str) -> dict | None:
        doc = self._doc(client_id)
        return self._client_row(doc) if doc else None

    def set_archived(self, client_id: str, archived: bool) -> None:
        with self._tx():
            self._edit(client_id)["archived"] = bool(archived)

    # ---- transcripts (scrubbed text only) ------------------------------------------------------

    def _tx_ids(self) -> list[str]:
        """Every transcript ID in use, across clients, because they are unique across clients."""
        found = {p.name for p in (self.folder / CLIENTS_DIR).glob(f"*/{TRANSCRIPTS_DIR}/*")}
        for doc in self._docs.values():
            found.update(doc["transcripts"])
        return sorted(found)

    def _owner(self, tx_id: str) -> str | None:
        if not TX_ID_RE.fullmatch(tx_id):
            return None
        for cid, doc in self._docs.items():
            if tx_id in doc["transcripts"]:
                return cid
        for p in (self.folder / CLIENTS_DIR).glob(f"*/{TRANSCRIPTS_DIR}/{tx_id}"):
            doc = self._doc(p.parent.parent.name)
            if doc and tx_id in doc["transcripts"]:
                return doc["id"]
        return None

    def _transcript_row(self, doc: dict, tx_id: str) -> dict:
        t = doc["transcripts"][tx_id]
        return {"id": tx_id, "client_id": doc["id"], "call_date": t["call_date"], "status": t["status"],
                "created_at": t["created_at"], "requested_outputs": list(t.get("requested_outputs", [])),
                "title": t.get("title") or "", "planned_outputs": list(t.get("planned_outputs", [])),
                "directions": t.get("directions") or "", "directions_ok": list(t.get("directions_ok", [])),
                "scrubbed_text": self._text(self._tx_dir(doc["id"], tx_id) / TRANSCRIPT_FILE)}

    def add_transcript(self, client_id: str, scrubbed_text: str, call_date: date | None = None,
                       title: str = "") -> str:
        call_date = call_date or self._clock().astimezone().date()
        with self._tx():
            doc = self._edit(client_id)
            tx = make_transcript_id(call_date, self._tx_ids())
            self._new_files[self._tx_dir(client_id, tx) / TRANSCRIPT_FILE] = scrubbed_text
            doc["transcripts"][tx] = {"call_date": call_date.isoformat(), "status": "draft", "created_at": self._stamp(),
                                      "seq": doc["next_seq"], "flags": [], "requested_outputs": []}
            if title.strip():
                doc["transcripts"][tx]["title"] = title.strip()
            doc["next_seq"] += 1
            self.audit("transcript_added", client_id, tx, len(scrubbed_text.encode("utf-8")))
        return tx

    def get_transcript(self, tx_id: str) -> dict | None:
        owner = self._owner(tx_id)
        return self._transcript_row(self._doc(owner), tx_id) if owner else None

    def list_transcripts(self, client_id: str) -> list[dict]:
        doc = self._doc(client_id)
        if doc is None:
            return []
        order = sorted(doc["transcripts"], key=lambda t: (doc["transcripts"][t]["call_date"], doc["transcripts"][t]["seq"]),
                       reverse=True)
        return [self._transcript_row(doc, t) for t in order]

    def set_transcript_status(self, tx_id: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        with self._tx():
            owner = self._owner(tx_id)
            if owner:
                self._edit(owner)["transcripts"][tx_id]["status"] = status

    def set_transcript_title(self, tx_id: str, scrubbed_title: str) -> None:
        """The optional call title, already scrubbed. An empty title removes it. Titles are never sent to Claude."""
        with self._tx():
            owner = self._owner(tx_id)
            if owner:
                t = self._edit(owner)["transcripts"][tx_id]
                if scrubbed_title.strip():
                    t["title"] = scrubbed_title.strip()
                else:
                    t.pop("title", None)
                self.audit("title_set", owner, tx_id, len(scrubbed_title.encode("utf-8")))

    def set_planned_outputs(self, tx_id: str, outputs) -> None:
        """The outputs ticked on the review page, kept apart from requested_outputs (which only a copy sets)."""
        wanted = set(outputs)
        if not wanted <= set(SLUGS):
            raise ValueError("unknown output")
        with self._tx():
            owner = self._owner(tx_id)
            if owner:
                self._edit(owner)["transcripts"][tx_id]["planned_outputs"] = [o for o in SLUGS if o in wanted]

    def set_transcript_directions(self, tx_id: str, scrubbed_directions: str, confirmed=()) -> None:
        """Directions typed for Claude, already scrubbed. Empty removes them. Sent with the next Copy for Claude."""
        with self._tx():
            owner = self._owner(tx_id)
            if owner:
                t = self._edit(owner)["transcripts"][tx_id]
                if scrubbed_directions.strip():
                    t["directions"] = scrubbed_directions.strip()
                    if confirmed:           # words the reviewer already ticked as fine to send, so the copy does not ask again
                        t["directions_ok"] = sorted({str(w) for w in confirmed})
                    else:
                        t.pop("directions_ok", None)
                else:
                    t.pop("directions", None)
                    t.pop("directions_ok", None)

    def update_scrubbed_text(self, tx_id: str, scrubbed_text: str) -> None:
        """Re-scrub after the reviewer's decisions. Takes scrubbed text only."""
        with self._tx():
            owner = self._owner(tx_id)
            if owner:
                path = self._tx_dir(owner, tx_id) / TRANSCRIPT_FILE
                (self._new_files if path in self._new_files else self._later_files)[path] = scrubbed_text

    # ---- registry (the real values, in plain text) ---------------------------------------------

    def save_registry(self, client_id: str, registry: Registry, first_seen_tx: str | None = None) -> None:
        data = json.loads(json.dumps(registry.to_dict(), ensure_ascii=False))
        with self._tx():
            doc = self._edit(client_id)
            doc["registry"] = data
            for ent in data["entities"]:
                doc["first_seen"].setdefault(f"[{ent['type']}_{ent['n']}]", first_seen_tx)

    def load_registry(self, client_id: str) -> Registry:
        doc = self._doc(client_id)
        return Registry.from_dict(doc["registry"]) if doc else Registry()

    def registry_fingerprint(self, client_id: str) -> str:
        """Changes when the client's registry changes. Lets a long job notice that another writer changed it."""
        doc = self._doc(client_id)
        return hashlib.sha256(json.dumps(doc["registry"] if doc else {}, sort_keys=True).encode()).hexdigest()

    def find_placeholder(self, client_id: str, type_: str, value: str) -> str | None:
        """The entity placeholder whose full form is this value."""
        wanted = canonical_email if type_ == "EMAIL" else norm
        doc = self._doc(client_id)
        for ent in doc["registry"]["entities"] if doc else []:
            full = ent["forms"].get("full")
            if ent["type"] == type_ and full and wanted(full) == wanted(value):
                return f"[{ent['type']}_{ent['n']}]"
        return None

    # ---- messages, outputs, review decisions, audit --------------------------------------------

    def add_message(self, client_id: str, kind: str, scrubbed_text: str, transcript_id: str | None = None,
                    copied: bool = True, output: str | None = None) -> int:
        """output: the output a change request was about, so the import page can offer it."""
        if output is not None and not is_slug(output):
            raise ValueError(f"unknown output {output!r}")
        if kind not in MESSAGE_KINDS:
            raise ValueError(f"unknown message kind {kind!r}")
        with self._tx():
            doc = self._edit(client_id)
            mid = doc["next_message"]
            doc["next_message"] += 1
            doc["messages"].append({"id": mid, "client_id": client_id, "transcript_id": transcript_id, "kind": kind,
                                    "scrubbed_text": scrubbed_text, "copied_at": self._stamp() if copied else None,
                                    "created_at": self._stamp(), **({"output": output} if output else {})})
            if copied:
                self.audit("message_copied", client_id, transcript_id, len(scrubbed_text.encode("utf-8")))
        return mid

    def list_messages(self, client_id: str) -> list[dict]:
        doc = self._doc(client_id)
        return list(doc["messages"]) if doc else []

    def _output_path(self, client_id: str, transcript_id: str, output: str) -> Path:
        if not is_slug(output):         # the slug becomes a file name, so only the known ones are accepted
            raise ValueError(f"unknown output {output!r}")
        return self._tx_dir(client_id, transcript_id) / f"{output}.json"

    def _output_versions(self, client_id: str, transcript_id: str, output: str) -> list[dict]:
        path = self._output_path(client_id, transcript_id, output)
        staged = self._new_files.get(path) or self._later_files.get(path)
        if staged is None and not path.exists():
            return []
        versions = (json.loads(staged) if staged else _read_json(path)).get("versions")
        if not isinstance(versions, list):
            raise Damaged(path, "the field versions is missing or has the wrong type")
        return versions

    def add_output(self, client_id: str, transcript_id: str, output: str, content: str, source: str = "import") -> int:
        """Add a version of one output, placeholders still in it, to that output's own file. Earlier versions stay,
        and no other output's file is touched. Returns the new version number."""
        if source not in OUTPUT_SOURCES:
            raise ValueError(f"unknown output source {source!r}")
        with self._tx():
            doc = self._edit(client_id)
            if transcript_id not in doc["transcripts"]:
                raise KeyError(transcript_id)
            path = self._output_path(client_id, transcript_id, output)
            versions = self._output_versions(client_id, transcript_id, output)
            version = len(versions) + 1
            at = self._stamp()
            versions.append({"version": version, "at": at, "source": source, "text": content})
            self._later_files[path] = _dump({"schema": SCHEMA, "output": output, "transcript_id": transcript_id,
                                             "versions": versions})
            doc["transcripts"][transcript_id]["last_output_at"] = at
            self.audit("output_edited" if source in ("edit", "hide", "unhide") else "output_imported", client_id, transcript_id,
                       len(content.encode("utf-8")))
        return version

    def list_outputs(self, transcript_id: str, output: str) -> list[dict]:
        if not is_slug(output):
            raise ValueError(f"unknown output {output!r}")
        owner = self._owner(transcript_id)
        if not owner:
            return []
        return [{"id": v["version"], "client_id": owner, "transcript_id": transcript_id, "output": output,
                 "version": v["version"], "content": v["text"], "source": v["source"], "created_at": v["at"]}
                for v in self._output_versions(owner, transcript_id, output)]

    def set_requested_outputs(self, transcript_id: str, outputs) -> None:
        """The outputs ticked at the last Copy for Claude, kept in the order the app lists them."""
        wanted = set(outputs)
        if not wanted <= set(SLUGS):
            raise ValueError("unknown output")
        with self._tx():
            owner = self._owner(transcript_id)
            if owner:
                self._edit(owner)["transcripts"][transcript_id]["requested_outputs"] = [o for o in SLUGS if o in wanted]

    def save_review_decision(self, transcript_id: str, span: tuple[int, int], text: str, decision: str) -> None:
        if decision not in DECISIONS:
            raise ValueError(f"unknown decision {decision!r}")
        with self._tx():
            owner = self._owner(transcript_id)
            flags = self._edit(owner)["transcripts"][transcript_id]["flags"]
            key, text_hash = f"{span[0]}:{span[1]}", hashlib.sha256(f"{owner}\0{norm(text)}".encode()).hexdigest()
            flags[:] = [f for f in flags if (f["span"], f["text_hash"]) != (key, text_hash)]
            flags.append({"transcript_id": transcript_id, "span": key, "text_hash": text_hash, "decision": decision,
                          "decided_at": self._stamp()})

    def decided_keep(self, transcript_id: str, word: str) -> bool:
        """The reviewer chose Keep for this word (at one place or for all) on this transcript. Only a hash of the word
        is stored with the decision, so the word is hashed the same way here."""
        owner = self._owner(transcript_id)
        if not owner:
            return False
        want = hashlib.sha256(f"{owner}\0{norm(word)}".encode()).hexdigest()
        return any(f["text_hash"] == want and f["decision"] == "keep" for f in self.list_review_decisions(transcript_id))

    def list_review_decisions(self, transcript_id: str) -> list[dict]:
        owner = self._owner(transcript_id)
        flags = self._doc(owner)["transcripts"][transcript_id]["flags"] if owner else []
        return sorted(flags, key=lambda f: f["span"])

    def audit(self, action: str, client_id: str | None = None, transcript_id: str | None = None,
              size: int | None = None) -> None:
        """Action and IDs and a byte count. Never content."""
        line = json.dumps({"at": self._stamp(), "action": action, "client_id": client_id, "transcript_id": transcript_id,
                           "bytes": size})
        if self._depth:
            self._audits.append(line)
        else:
            self._append_audit(line)

    def _append_audit(self, line: str) -> None:
        fd = os.open(self.folder / AUDIT_NAME, os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "r+b") as f:
            f.seek(0, os.SEEK_END)
            torn = False
            if f.tell():                # a crash can leave half a line, and this entry must not join it
                f.seek(-1, os.SEEK_END)
                torn = f.read(1) != b"\n"
            f.write((("\n" if torn else "") + line + "\n").encode("utf-8"))

    def list_audit(self) -> list[dict]:
        path = self.folder / AUDIT_NAME
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
            try:
                rows.append({"id": len(rows) + 1, **json.loads(line)})
            except json.JSONDecodeError:
                continue
        return rows
