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
DIRS = ["app", "mcp_server", "clio_filler"]
FILES = ["run.py", "pyproject.toml", "README.md", "samples/sample_call.txt"]
MODEL_DIR = "models/gliner_pii"
MODEL_FILES = ["gliner_config.json", "model_quantized.onnx", "tokenizer.json", "tokenizer_config.json"]
# The list of model files and their checksums. It is committed to git and shipped in every zip. A copy that has no
# model files downloads them from the GitHub release named on its first line.
MANIFEST = "models/MODEL-SHA256.txt"

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

# The guide for the person who receives the zip. It is kept in the project as INSTALL-ZIP.md and shipped as START-HERE.md.
GUIDE = "INSTALL-ZIP.md"


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
    if not (root / MANIFEST).is_file():
        raise SystemExit(f"Missing {MANIFEST}. Write it first with:  python scripts/package.py --manifest model-v1")
    picked[MANIFEST] = root / MANIFEST
    if include_model:
        for name in MODEL_FILES:
            p = root / MODEL_DIR / name
            if not p.is_file():
                raise SystemExit(f"The name model is incomplete: {MODEL_DIR}/{name} is missing. "
                                 "Export it first, or pass --no-model.")
            picked[f"{MODEL_DIR}/{name}"] = p
        wrong = manifest_problems(root)
        if wrong:
            raise SystemExit(f"The model files do not match {MANIFEST}:\n  " + "\n  ".join(wrong)
                             + "\nIf the model changed on purpose, write the list again with --manifest.")
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


def write_manifest(root: Path, tag: str) -> Path:
    """Write models/MODEL-SHA256.txt from the model files on this computer."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
        raise SystemExit(f"{tag!r} is not a usable release tag.")
    lines = [f"release {tag}"]
    for name in MODEL_FILES:
        p = root / MODEL_DIR / name
        if not p.is_file():
            raise SystemExit(f"The name model is incomplete: {MODEL_DIR}/{name} is missing.")
        lines.append(f"{sha256_of(p)}  {p.stat().st_size}  {name}")
    target = root / MANIFEST
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# SHA-256, size in bytes and name of each name model file. run.py checks and downloads by this.\n"
                      + "\n".join(lines) + "\n", encoding="utf-8")
    return target


def manifest_problems(root: Path) -> list[str]:
    """Differences between the manifest and the model files. Empty when they match."""
    listed = {}
    for line in (root / MANIFEST).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1].isdigit():
            listed[parts[2]] = (parts[0], int(parts[1]))
    problems = []
    for name in MODEL_FILES:
        p = root / MODEL_DIR / name
        if name not in listed:
            problems.append(f"{name} is not in the list")
        elif not p.is_file() or (p.stat().st_size, sha256_of(p)) != (listed[name][1], listed[name][0]):
            problems.append(f"{name} differs from the list")
    problems += [f"{name} is listed but is not a model file" for name in listed if name not in MODEL_FILES]
    return problems


def version_of(root: Path) -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0"


def build(root: Path = ROOT, out_dir: Path | None = None, include_model: bool = True) -> Path:
    items = collect(root, include_model)
    if not (root / GUIDE).is_file():
        raise SystemExit(f"Missing {GUIDE}, the guide that ships as START-HERE.md.")
    out_dir = out_dir or root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    version = version_of(root)
    target = out_dir / f"matter-workbench-{version}{'' if include_model else '-no-model'}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for src, rel in items:
            z.write(src, f"{TOP}/{rel}")
        z.writestr(f"{TOP}/START-HERE.md", (root / GUIDE).read_text(encoding="utf-8"))
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
    ap.add_argument("--no-model", action="store_true",
                    help="leave the 570 MB name model out. run.py then downloads it on the first run")
    ap.add_argument("--manifest", metavar="TAG",
                    help="write models/MODEL-SHA256.txt for release TAG from the model files here, then stop")
    args = ap.parse_args(argv)
    if args.manifest:
        print(f"Wrote {write_manifest(ROOT, args.manifest)}")
        print(f"Upload the four files in {MODEL_DIR} to the GitHub release {args.manifest} before pushing this list.")
        return 0
    target = build(ROOT, args.out, include_model=not args.no_model)
    mb = target.stat().st_size / 1_000_000
    print(f"Built {target}  ({mb:,.0f} MB)")
    print(f"SHA-256 {sha256_of(target)}")
    print("Contains no client records, transcripts, keys or settings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
