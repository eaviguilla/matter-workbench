#!/usr/bin/env python3
"""Build one zip that runs on macOS and Windows:  python scripts/package.py  [--out dist] [--no-model]

The zip holds only what the app needs to run. It is built from an allow list, so a file that is not named
here never ships. It holds no saved clients, transcripts, mappings, keys or settings. Those live in the
data folder outside this project, and the build also refuses to continue if a data-like file (a client file,
a key, an .env, a Word file) turns up among the files it would pack.

The person who receives it unzips it and runs `python run.py`.
"""
import argparse
import fnmatch
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP = "matter-workbench"

# Directories packed whole (minus caches), and single files packed as they are.
DIRS = ["app", "mcp_server"]
FILES = ["run.py", "pyproject.toml", "README.md", "samples/sample_call.txt"]
MODEL_DIR = "models/gliner_pii"
MODEL_FILES = ["gliner_config.json", "model_quantized.onnx", "tokenizer.json", "tokenizer_config.json"]

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".venv", ".git", "node_modules", "dist", "build", "tests", "design"}
SKIP_FILES = ["*.pyc", "*.pyo", ".DS_Store", "Thumbs.db"]
# Anything like this inside the pack is a stop, not a skip.
FORBIDDEN = ["client.json", "settings.json", "audit.jsonl", "transcript.txt", "clients", ".env", ".env.*", "*.pem", "*.key",
             "*.p12", "*.docx", "*.doc", "*.pdf", "*.xlsx", "*.csv", "*.log", "*.bak", "*.backup", "*.keystore",
             "real", "real/*", "*.ann.txt"]

NOTICE = """Matter Workbench package notices

Name model
  GLiNER multilingual PII model, urchade/gliner_multi_pii-v1, exported to ONNX and quantized.
  License: Apache 2.0. https://huggingface.co/urchade/gliner_multi_pii-v1
  The license permits redistribution when this notice is kept.

Libraries are downloaded by run.py from the Python Package Index when you first run it, each under its own license.
"""

START_HERE = """# Matter Workbench

A local tool that hides names, emails and addresses in call transcripts before you paste them into claude.ai,
and puts the real values back in Claude's replies. Everything runs on this computer.

This package holds the app and the name model. It holds no client records or transcripts.

## What you need first

- Python 3.11 or newer. Python 3.12 or 3.13 is the safest choice.
- An internet connection for the first run only. Later runs work offline.
- About 2 GB of free disk space and 1 to 2 GB of memory while the app runs.

## macOS

1. Unzip the file. Open Terminal and go into the folder.
2. Run this. The first run takes a few minutes. It builds a private environment, installs the libraries, checks
   the model and opens the app in your browser.

```bash
cd matter-workbench
python3 run.py
```

3. Run the same command next time. It starts the app in seconds because everything is installed.

If `python3 --version` shows something older than 3.11, install Python from https://www.python.org/downloads/
or run `brew install python@3.12`, then use `python3.12 run.py`.

## Windows

1. Unzip the file (right-click, Extract All). Open PowerShell and go into the folder.
2. Run this.

```powershell
cd matter-workbench
py run.py
```

3. Run the same command next time.

If `py` is not found, install Python from https://www.python.org/downloads/ and tick "Add python.exe to PATH" in
the installer. If Windows Defender or SmartScreen asks about the file, choose "More info" and then "Run anyway".
Do not unzip into OneDrive, iCloud Drive or Dropbox. Use a plain folder such as `C:\\MatterWorkbench`.

## Options

```text
python run.py --port 9000      use another port (the default is 8765)
python run.py --no-browser     do not open the page automatically
python run.py --reinstall      delete the private environment and install again
python run.py --install-only   install, then stop
```

On Windows write `py run.py` instead of `python run.py`. Stop the app with Ctrl+C in the window.

## Where your data goes

Saved clients and transcripts are stored outside this folder.

- macOS: `~/Library/Application Support/MatterWorkbench.noindex`
- Windows: `%LOCALAPPDATA%\\MatterWorkbench`

Real names, emails and addresses are stored there as plain text, so keep disk encryption on (FileVault or BitLocker).
Data stays on that computer. Copying this folder to another computer never copies it, and a new computer starts with
no clients. Never share `client.json`. To report a problem, run `python -m app.check`, whose report holds no stored
values.

## Updating

Unzip the new package over the old folder, or into a new one, and run `run.py`. It reinstalls only when the
requirements changed. Your data is untouched.

## Removing

Delete this folder. To remove the data too, delete the data folder above. Do that only after exporting anything you
still need, because the data cannot be recovered afterwards.

## If something goes wrong

- "Python 3.11 or newer is needed". Install a newer Python as described above.
- pip says no matching distribution. Your Python is too new or too old for a library. Install Python 3.12 or 3.13.
- "checksum does not match". The zip did not copy completely. Copy it again.
- "address already in use". Another copy is running, or use `--port 9000`.
"""


def is_skipped(rel: Path) -> bool:
    if any(part in SKIP_DIRS for part in rel.parts[:-1]):
        return True
    return any(fnmatch.fnmatch(rel.name, pat) for pat in SKIP_FILES)


def is_forbidden(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    return any(fnmatch.fnmatch(p, pat) for p in parts for pat in FORBIDDEN)


def collect(root: Path, include_model: bool) -> list[tuple[Path, str]]:
    """(source file, path inside the zip, relative to the top folder)."""
    picked: dict[str, Path] = {}
    for d in DIRS:
        base = root / d
        if not base.is_dir():
            raise SystemExit(f"Missing folder {d}.")
        for p in sorted(base.rglob("*")):
            if p.is_file() and not is_skipped(p.relative_to(root)):
                picked[p.relative_to(root).as_posix()] = p
    for f in FILES:
        if not (root / f).is_file():
            raise SystemExit(f"Missing file {f}.")
        picked[f] = root / f
    if include_model:
        for name in MODEL_FILES:
            p = root / MODEL_DIR / name
            if not p.is_file():
                raise SystemExit(f"The name model is incomplete: {MODEL_DIR}/{name} is missing. "
                                 "Export it first, or pass --no-model.")
            picked[f"{MODEL_DIR}/{name}"] = p
    bad = sorted(rel for rel in picked if is_forbidden(rel))
    if bad:
        raise SystemExit("Refusing to package. These look like records or secrets, remove them from the project:\n  "
                         + "\n  ".join(bad))
    return [(src, rel) for rel, src in sorted(picked.items())]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def version_of(root: Path) -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0"


def build(root: Path = ROOT, out_dir: Path | None = None, include_model: bool = True) -> Path:
    items = collect(root, include_model)
    out_dir = out_dir or root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    version = version_of(root)
    target = out_dir / f"matter-workbench-{version}{'' if include_model else '-no-model'}.zip"
    sums = [f"{sha256_of(src)}  {rel}" for src, rel in items if rel.startswith(MODEL_DIR + "/")]
    checks = "# SHA-256 of the name model. run.py checks these on the first install.\n" + "\n".join(sums) + "\n"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for src, rel in items:
            z.write(src, f"{TOP}/{rel}")
        if sums:
            z.writestr(f"{TOP}/CHECKSUMS.txt", checks)
        z.writestr(f"{TOP}/START-HERE.md", START_HERE)
        z.writestr(f"{TOP}/NOTICE.txt", NOTICE)
        z.writestr(f"{TOP}/VERSION", version + "\n")
    # Read the finished zip back: nothing outside the top folder, and nothing that looks like a record.
    with zipfile.ZipFile(target) as z:
        names = z.namelist()
    stray = [n for n in names if not n.startswith(TOP + "/") or is_forbidden(n[len(TOP) + 1:])]
    if stray:
        target.unlink()
        raise SystemExit("The zip failed its own check and was deleted:\n  " + "\n  ".join(stray))
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the Matter Workbench zip for macOS and Windows.")
    ap.add_argument("--out", type=Path, default=ROOT / "dist", help="folder for the zip (default dist)")
    ap.add_argument("--no-model", action="store_true", help="leave the 570 MB name model out (for a quick check)")
    args = ap.parse_args(argv)
    target = build(ROOT, args.out, include_model=not args.no_model)
    mb = target.stat().st_size / 1_000_000
    print(f"Built {target}  ({mb:,.0f} MB)")
    print(f"SHA-256 {sha256_of(target)}")
    print("Contains no client records, transcripts, keys or settings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
