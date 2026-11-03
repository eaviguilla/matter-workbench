"""Check the data folder and report problems without showing any stored value:  python -m app.check

client.json holds real names, so the report is what to share with Claude when something needs repair, never the file.
It gives paths, field names and the position of a JSON error. Client IDs appear in paths, as they already do in the
header line sent with every transcript.
"""
import json
import sys
from pathlib import Path

from .scrub.registry import Registry, has_token

from .outputs import SLUGS
from .paths import AUDIT_NAME, CLIENT_FILE, CLIENTS_DIR, SETTINGS_NAME, TRANSCRIPT_FILE, TRANSCRIPTS_DIR, prepare_data_dir

CLIENT_FIELDS = (("schema", int), ("id", str), ("first_name", str), ("created_at", str), ("transcripts", dict),
                 ("messages", list), ("registry", dict), ("settings", dict))
TRANSCRIPT_FIELDS = (("call_date", str), ("status", str), ("created_at", str), ("seq", int), ("flags", list))
OUTPUT_FIELDS = (("output", str), ("transcript_id", str), ("versions", list))
VERSION_FIELDS = (("version", int), ("at", str), ("source", str), ("text", str))
SOURCES = ("import", "mcp", "edit", "hide")


def _load(path: Path, problems: list, root: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:       # never e.doc or a slice of the text, which holds the contents
        problems.append(f"{path.relative_to(root)}: not valid JSON at line {e.lineno}, column {e.colno}")
    except (OSError, UnicodeDecodeError) as e:
        problems.append(f"{path.relative_to(root)}: cannot be read ({type(e).__name__})")
    else:
        if isinstance(data, dict):
            return data
        problems.append(f"{path.relative_to(root)}: the top level is not an object")
    return None


def _fields(data: dict, fields, where: str, problems: list) -> None:
    for name, kind in fields:
        if not isinstance(data.get(name), kind):
            problems.append(f"{where}: field {name} is missing or is not {kind.__name__}")


def check(folder: Path) -> list[str]:
    """Problems found, as text that holds no stored value."""
    problems: list[str] = []
    if (folder / SETTINGS_NAME).exists():
        _load(folder / SETTINGS_NAME, problems, folder)
    for client in sorted((folder / CLIENTS_DIR).glob("*")) if (folder / CLIENTS_DIR).is_dir() else []:
        if not client.is_dir() or client.name.startswith("."):
            continue
        rel = client.relative_to(folder)
        doc = _load(client / CLIENT_FILE, problems, folder) if (client / CLIENT_FILE).exists() else None
        if doc is None:
            if not (client / CLIENT_FILE).exists():
                problems.append(f"{rel / CLIENT_FILE}: the file is missing")
            continue
        _fields(doc, CLIENT_FIELDS, str(rel / CLIENT_FILE), problems)
        if doc.get("id") != client.name:
            problems.append(f"{rel / CLIENT_FILE}: field id does not match the folder name")
        reg = doc.get("registry") if isinstance(doc.get("registry"), dict) else {}
        for ent in reg.get("entities") if isinstance(reg.get("entities"), list) else []:
            if not isinstance(ent, dict):
                continue
            values = [v for v in (ent.get("forms") or {}).values() if isinstance(v, str)] + \
                     [a for a in (ent.get("aliases") or []) if isinstance(a, str)]
            if "only" in ent and (not isinstance(ent["only"], list) or any(not isinstance(t, str) for t in ent["only"])):
                problems.append(f"{rel / CLIENT_FILE}: hidden name {ent.get('type')}_{ent.get('n')} has a field only that is "
                                "not a list of transcript IDs")
            if "via" in ent and not isinstance(ent["via"], str):
                problems.append(f"{rel / CLIENT_FILE}: hidden name {ent.get('type')}_{ent.get('n')} has a field via that is not text")
            if any(has_token(v) for v in values):        # the value is never shown, only which entry holds it
                problems.append(f"{rel / CLIENT_FILE}: hidden name {ent.get('type')}_{ent.get('n')} holds a code "
                                "instead of a name. Run python -m app.check --fix to remove it, or delete it on the "
                                "Hidden names page.")
        listed = doc.get("transcripts") if isinstance(doc.get("transcripts"), dict) else {}
        for tx, meta in listed.items():
            where = f"{rel / CLIENT_FILE}: transcript {tx}"
            if isinstance(meta, dict):
                _fields(meta, TRANSCRIPT_FIELDS, where, problems)
                asked = meta.get("requested_outputs", [])
                if not isinstance(asked, list) or any(o not in SLUGS for o in asked):
                    problems.append(f"{where}: field requested_outputs is not a list of known outputs")
                if "title" in meta and not isinstance(meta["title"], str):
                    problems.append(f"{where}: field title is not str")
                planned = meta.get("planned_outputs", [])
                if not isinstance(planned, list) or any(o not in SLUGS for o in planned):
                    problems.append(f"{where}: field planned_outputs is not a list of known outputs")
                if "directions" in meta and not isinstance(meta["directions"], str):
                    problems.append(f"{where}: field directions is not str")
                ok = meta.get("directions_ok", [])
                if not isinstance(ok, list) or any(not isinstance(w, str) for w in ok):
                    problems.append(f"{where}: field directions_ok is not a list of text")
            else:
                problems.append(f"{where}: is not an object")
            tx_dir = client / TRANSCRIPTS_DIR / tx
            if not (tx_dir / TRANSCRIPT_FILE).is_file():
                problems.append(f"{rel / TRANSCRIPTS_DIR / tx / TRANSCRIPT_FILE}: the file is missing")
            for path in sorted(tx_dir.glob("*.json")):
                out = _load(path, problems, folder)
                if out is None:
                    continue
                out_rel = str(path.relative_to(folder))
                _fields(out, OUTPUT_FIELDS, out_rel, problems)
                if path.stem not in SLUGS:
                    problems.append(f"{out_rel}: not a known output file")
                elif out.get("output") != path.stem:
                    problems.append(f"{out_rel}: field output does not match the file name")
                if out.get("transcript_id") != tx:
                    problems.append(f"{out_rel}: field transcript_id does not match the folder name")
                for i, v in enumerate(out.get("versions") if isinstance(out.get("versions"), list) else [], 1):
                    if isinstance(v, dict):
                        _fields(v, VERSION_FIELDS, f"{out_rel}: version entry {i}", problems)
                        if v.get("version") != i:
                            problems.append(f"{out_rel}: version entry {i} is out of order")
                        if "source" in v and v["source"] not in SOURCES:
                            problems.append(f"{out_rel}: version entry {i} has an unknown source")
                    else:
                        problems.append(f"{out_rel}: version entry {i} is not an object")
    audit = folder / AUDIT_NAME
    if audit.exists():
        for n, line in enumerate(audit.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            try:
                json.loads(line)
            except json.JSONDecodeError:
                problems.append(f"{AUDIT_NAME}: line {n} is not valid JSON and is skipped when read")
    return problems


def fix(folder: Path) -> dict:
    """Repair the one kind of damage a version of the app caused: a hidden-name entry whose value is a code such as
    [PERSON_1]. Removes those entries (or only the code form of a mixed one) and changes nothing else. Returns counts
    only: clients fixed, entries removed and forms removed."""
    from .store import Store
    done = {"clients": 0, "entries": 0, "forms": 0}
    with Store.open(folder) as s:
        for row in s.list_clients(include_archived=True):
            cid = row["id"]
            with s.transaction():
                reg = s.load_registry(cid)
                if not reg.code_entries():
                    continue
                removed, forms = reg.strip_codes()
                s.save_registry(cid, reg)
            done["clients"] += 1
            done["entries"] += removed
            done["forms"] += forms
    return done


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if any(a not in ("--fix",) for a in argv):
        print("Usage: python -m app.check [--fix]")
        return 2
    folder = prepare_data_dir()
    if "--fix" in argv:
        n = fix(folder)
        print(f"Removed {n['entries']} hidden-name entr{'y' if n['entries'] == 1 else 'ies'} that held a code and "
              f"{n['forms']} code form{'' if n['forms'] == 1 else 's'} in {n['clients']} client{'' if n['clients'] == 1 else 's'}.")
    problems = check(folder)
    for p in problems:
        print(p)
    print(f"{len(problems)} problem{'s' if len(problems) != 1 else ''} found.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
