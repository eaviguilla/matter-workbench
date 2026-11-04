#!/usr/bin/env python3
"""Matter Workbench launcher. Run it with Python 3.11 or newer on macOS or Windows:

    python3 run.py        (macOS)
    py run.py             (Windows)

The first run builds a private environment in .venv, installs everything the app needs, installs the name
model (from the package, or by download from the GitHub release named in models/MODEL-SHA256.txt), and starts
the app. Every later run checks what is installed first. If all of it is in place it changes nothing and only
starts the app. A running copy is never touched.

Options (anything else is passed on to the app, for example --port 9000 or --demo):
    --reinstall      delete .venv and install again
    --install-only   install, then stop without starting the app
    --no-browser     do not open the web page
    -h, --help       show this text

Uses only the Python standard library. Saved clients and transcripts live outside this folder, so an
update or a reinstall never touches them.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIN_PYTHON = (3, 11)
MODEL_DIR = Path("models") / "gliner_pii"
MODEL_FILE = "model_quantized.onnx"
MANIFEST = Path("models") / "MODEL-SHA256.txt"
RELEASE_URL = "https://github.com/eaviguilla/matter-workbench/releases/download/{tag}/{name}"
VERIFIED_NAME = ".verified.json"
EXTRA = ".[ner]"
DEFAULT_PORT = 8765
STAMP_NAME = "installed.json"
IMPORTS = "import app, uvicorn, fastapi, onnxruntime, tokenizers, numpy"
SPACE_MARGIN = 200 * 1024 * 1024
RETRY_WAITS = (2, 5)                   # three tries, with these pauses between them


class Stop(Exception):
    """A problem the person can fix. The message says how."""


def say(msg: str = "") -> None:
    print(msg, flush=True)


def venv_dir(root: Path = ROOT) -> Path:
    return root / ".venv"


def venv_python(root: Path = ROOT, platform: str | None = None) -> Path:
    win = (platform or sys.platform) == "win32"
    return venv_dir(root) / ("Scripts" if win else "bin") / ("python.exe" if win else "python")


def check_python(version=None) -> None:
    version = tuple(version or sys.version_info[:2])
    if version < MIN_PYTHON:
        have = ".".join(str(n) for n in version)
        raise Stop(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is needed, and this is Python {have}.\n"
            "Install Python 3.13 from https://www.python.org/downloads/ and run this file again.\n"
            "  macOS:    python3.13 run.py\n"
            "  Windows:  py -3.13 run.py   (tick 'Add python.exe to PATH' in the installer)")


# ---- the Python environment ------------------------------------------------------------------

def deps_digest(root: Path = ROOT) -> str:
    """A fingerprint of what the libraries depend on. A version bump or a new description does not change it,
    so only a real change to the requirements reinstalls."""
    raw = (root / "pyproject.toml").read_bytes().decode("utf-8", "replace")
    try:
        data = tomllib.loads(raw)
        project = data.get("project", {})
        parts = [project.get("requires-python"), project.get("dependencies"),
                 project.get("optional-dependencies", {}).get("ner"), data.get("build-system")]
    except ValueError:
        parts = raw                              # not valid TOML, so fingerprint the whole file
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def state(root: Path = ROOT, platform: str | None = None) -> dict:
    """What the installed environment was built for."""
    return {"project": str(root), "platform": platform or sys.platform, "deps": deps_digest(root)}


def read_stamp(root: Path = ROOT) -> dict | None:
    try:
        return json.loads((venv_dir(root) / STAMP_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_stamp(root: Path = ROOT, platform: str | None = None) -> None:
    (venv_dir(root) / STAMP_NAME).write_text(json.dumps(state(root, platform), indent=2), encoding="utf-8")


def environment_works(root: Path = ROOT) -> bool:
    py = venv_python(root)
    if not py.exists():
        return False
    try:
        done = subprocess.run([str(py), "-c", IMPORTS], cwd=root, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def plan(root: Path = ROOT, platform: str | None = None) -> tuple[str, str]:
    """What the environment needs, as (action, reason). The actions are
    none     all installed, change nothing
    stamp    works already, only the note of what it was built for is rewritten
    upgrade  the requirements changed, install into the existing environment
    rebuild  there is none, or it is for another computer or is damaged, build it again"""
    platform = platform or sys.platform
    if not venv_dir(root).exists():
        return "rebuild", "first run"
    works = environment_works(root)
    stamp = read_stamp(root)
    if stamp is None or "deps" not in stamp:           # no note, or one written by an older run.py
        return ("stamp", "it was installed already") if works else ("rebuild", "the environment is damaged")
    if stamp.get("platform") != platform:
        return "rebuild", "the environment was built for another computer"
    if stamp.get("deps") != deps_digest(root):
        return "upgrade", "the requirements changed"
    if not works:
        return "rebuild", "the environment is damaged"
    if stamp.get("project") != str(root):
        return "stamp", "the folder was moved"
    return "none", ""


def pip_install(root: Path, what: str, hint: str) -> None:
    run_step([str(venv_python(root)), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-e", EXTRA],
             root, what, hint)


def run_step(cmd: list, root: Path, what: str, hint: str = "") -> None:
    say(f"  {what} ...")
    try:
        code = subprocess.call(cmd, cwd=root)
    except OSError as e:
        raise Stop(f"Could not run {cmd[0]}: {e}")
    if code != 0:
        raise Stop(f"{what} failed (exit code {code}). {hint}".strip())


NET_HINT = "Check the internet connection and run this file again."
PIP_HINT = (NET_HINT + " If pip says no matching distribution exists, install Python 3.12 or 3.13 and use it to "
            "run this file.")


def install(root: Path = ROOT, reason: str = "") -> None:
    """Build the environment from nothing. This deletes an existing .venv."""
    say(f"Installing Matter Workbench ({reason}). This takes a few minutes and needs an internet connection.")
    env = venv_dir(root)
    if env.exists():
        shutil.rmtree(env, ignore_errors=True)
    try:
        import venv
        venv.EnvBuilder(with_pip=True, clear=True).create(env)
    except Exception as e:           # ensurepip missing, no permission, and so on
        raise Stop(f"Could not create the private environment: {e}\n"
                   "On Debian or Ubuntu run: sudo apt install python3-venv")
    py = str(venv_python(root))
    run_step([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--upgrade", "pip"], root,
             "Updating pip", NET_HINT)
    pip_install(root, "Installing the app and its libraries", PIP_HINT)
    if not environment_works(root):
        raise Stop("The install finished but the app cannot be imported. Run again with --reinstall.")
    write_stamp(root)
    say("  Install complete.")


def upgrade(root: Path = ROOT, reason: str = "") -> None:
    """Install changed requirements into the existing environment. Nothing is deleted."""
    say(f"Updating the libraries ({reason}). This needs an internet connection.")
    pip_install(root, "Installing the libraries", PIP_HINT + " Run with --reinstall to start the environment over.")
    if not environment_works(root):
        raise Stop("The update finished but the app cannot be imported. Run again with --reinstall.")
    write_stamp(root)
    say("  Update complete.")


def ensure_environment(root: Path = ROOT, reinstall: bool = False) -> str:
    """Make the environment ready, doing only what is missing. Returns the action taken."""
    if reinstall:
        install(root, "requested")
        return "rebuild"
    action, reason = plan(root)
    if action == "none":
        say("Already installed.")
    elif action == "stamp":
        write_stamp(root)
        say(f"Already installed ({reason}).")
    elif action == "upgrade":
        upgrade(root, reason)
    else:
        install(root, reason)
    return action


# ---- the name model --------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_manifest(root: Path = ROOT) -> tuple[str, dict] | None:
    """(release tag, {file name: (sha256, size)}), or None when the project has no model list."""
    path = root / MANIFEST
    if not path.exists():
        return None
    tag, files = "", {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("release "):
            tag = line[len("release "):].strip()
            continue
        parts = line.split()
        if len(parts) != 3 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]) or not parts[1].isdigit() \
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", parts[2]):
            raise Stop(f"{MANIFEST.as_posix()} has a line it cannot read: {line[:80]}")
        files[parts[2]] = (parts[0], int(parts[1]))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag) or not files:
        raise Stop(f"{MANIFEST.as_posix()} is incomplete. Copy the package again.")
    return tag, files


def file_marks(dest: Path, names) -> dict:
    return {n: [(dest / n).stat().st_size, (dest / n).stat().st_mtime_ns] for n in names}


def model_verified(dest: Path, tag: str, files: dict) -> bool:
    """True when the files are the ones checked before, judged by size and time alone. No hashing."""
    try:
        done = json.loads((dest / VERIFIED_NAME).read_text(encoding="utf-8"))
        return (done.get("release") == tag and done.get("files") == file_marks(dest, files)
                and all(done["files"][n][0] == files[n][1] for n in files))
    except (OSError, ValueError, KeyError):
        return False


def pip_cacert(root: Path) -> str | None:
    """Python from python.org on macOS often lacks certificates until a post-install step is run. pip carries
    its own, so ask the environment's pip for them, and then the pip of the Python running this file."""
    for py in (venv_python(root), Path(sys.executable)):
        try:
            done = subprocess.run([str(py), "-c", "from pip._vendor import certifi; print(certifi.where())"],
                                  capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        path = done.stdout.strip()
        if done.returncode == 0 and path and Path(path).exists():
            return path
    return None


def make_opener(root: Path):
    """opener(url, start) returns an open response. It starts at byte start when start is not 0."""
    context: dict[str, ssl.SSLContext | None] = {"ctx": None}

    def fetch(url: str, start: int):
        headers = {"User-Agent": "matter-workbench-run"}
        if start:
            headers["Range"] = f"bytes={start}-"
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30,
                                      context=context["ctx"])

    def opener(url: str, start: int = 0):
        try:
            return fetch(url, start)
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLCertVerificationError) and context["ctx"] is None:
                cafile = pip_cacert(root)
                if cafile:
                    context["ctx"] = ssl.create_default_context(cafile=cafile)
                    return fetch(url, start)
            raise
    return opener


class Progress:
    """One line that updates twice a second on a terminal, or a new line every 10 percent otherwise."""

    def __init__(self, total: int, label: str, stream=None):
        self.total, self.label, self.done = total, label, 0
        self.stream = stream or sys.stdout
        self.tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.started = self.last = time.time()
        self.step = -1

    def add(self, n: int) -> None:
        self.done += n
        now = time.time()
        pct = int(self.done * 100 / self.total) if self.total else 100
        if self.tty and now - self.last >= 0.5:
            self.last = now
            rate = self.done / max(now - self.started, 0.1) / 1e6
            self.stream.write(f"\r  {self.label}, {self.done / 1e6:,.0f} of {self.total / 1e6:,.0f} MB, "
                              f"{pct} percent, {rate:.1f} MB/s   ")
            self.stream.flush()
        elif not self.tty and pct // 10 > self.step:
            self.step = pct // 10
            self.stream.write(f"  {self.label}, {pct} percent\n")
            self.stream.flush()

    def finish(self) -> None:
        if self.tty:
            self.stream.write("\r" + " " * 78 + "\r")
            self.stream.flush()


def download_file(url: str, part: Path, sha: str, size: int, opener, progress: Progress, sleep=time.sleep) -> None:
    """Fetch one file into part, continuing a partial file when the server allows it. Checks size and hash."""
    last = ""
    for attempt in range(len(RETRY_WAITS) + 1):
        if attempt:
            sleep(RETRY_WAITS[attempt - 1])
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink()
            have = 0
        try:
            if have < size:
                with opener(url, have) as resp:
                    resumed = have and getattr(resp, "status", 200) == 206
                    if have and not resumed:
                        have = 0
                    with open(part, "ab" if resumed else "wb") as out:
                        progress.add(have)
                        while True:
                            block = resp.read(1 << 20)
                            if not block:
                                break
                            out.write(block)
                            progress.add(len(block))
            if part.stat().st_size == size and sha256_of(part) == sha:
                return
            last = "the file arrived damaged"
            part.unlink(missing_ok=True)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise Stop("The name model release is not on GitHub. Tell the owner of this project.")
            if e.code == 407:
                raise Stop("A proxy needs a sign-in. Ask IT to allow downloads from github.com, or use the package zip.")
            last = f"the server answered {e.code}"
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
                raise Stop("This computer does not trust the certificate GitHub sends, so the download was refused. "
                           "On a Mac, open the folder /Applications/Python 3.13 in Finder, double-click "
                           "Install Certificates.command, and run this file again. On a work network, ask IT to "
                           "allow downloads from github.com.")
            last = str(getattr(e, "reason", e)) or "no connection"
    raise Stop(f"No internet connection, or the download kept failing ({last}). The app will start, but scrubbing "
               "stays blocked. Run this again when online. The download continues where it stopped.")


def move_into_place(src: Path, dst: Path, sleep=time.sleep) -> None:
    for attempt in range(5):
        try:
            os.replace(src, dst)
            return
        except PermissionError:          # Windows, while an antivirus program still holds the new file
            if attempt == 4:
                raise
            sleep(1)


def ensure_model(root: Path = ROOT, opener=None, sleep=time.sleep, stream=None) -> bool:
    """Make sure the name model is installed and correct. Quiet and fast when it already is. A problem is
    printed and returns False, and never stops the app from starting."""
    try:
        listed = read_manifest(root)
        if listed is None:
            return (root / MODEL_DIR / MODEL_FILE).exists()
        tag, files = listed
        dest = root / MODEL_DIR
        if dest.is_dir() and all((dest / n).is_file() for n in files) and model_verified(dest, tag, files):
            return True
        dest.mkdir(parents=True, exist_ok=True)
        need = {}
        for name, (sha, size) in files.items():
            f = dest / name
            if not (f.is_file() and f.stat().st_size == size and sha256_of(f) == sha):
                need[name] = (sha, size)
        if need:
            part_dir = dest / f".download-{tag}"
            part_dir.mkdir(exist_ok=True)
            total = sum(size for _, size in need.values())
            have = sum((part_dir / f"{n}.part").stat().st_size for n in need if (part_dir / f"{n}.part").exists())
            free = shutil.disk_usage(dest).free
            if free < total - have + SPACE_MARGIN:
                raise Stop(f"The name model needs {(total - have + SPACE_MARGIN) / 1e9:.1f} GB free and this disk "
                           f"has {free / 1e9:.1f} GB. Free some space and run this file again.")
            say(f"Downloading the name model, {total / 1e6:,.0f} MB, from github.com. This happens once.")
            opener = opener or make_opener(root)
            progress = Progress(total, "Downloading the name model", stream)
            try:
                for name, (sha, size) in need.items():
                    download_file(RELEASE_URL.format(tag=tag, name=name), part_dir / f"{name}.part", sha, size,
                                  opener, progress, sleep)
            finally:
                progress.finish()
            for name in need:
                move_into_place(part_dir / f"{name}.part", dest / name, sleep)
            shutil.rmtree(part_dir, ignore_errors=True)
        for old in dest.glob(".download-*"):
            shutil.rmtree(old, ignore_errors=True)
        (dest / VERIFIED_NAME).write_text(json.dumps({"release": tag, "files": file_marks(dest, files)}),
                                          encoding="utf-8")
        if need:
            say("  The name model is installed.")
        return True
    except Stop as e:
        say(f"Name model: {e}")
    except OSError as e:
        say(f"Name model: could not install it ({e}). The app will start, but scrubbing stays blocked.")
    return False


# ---- starting the app ------------------------------------------------------------------------

def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def open_when_ready(port: int, proc: subprocess.Popen, give_up: float = 90.0) -> None:
    url = f"http://127.0.0.1:{port}"
    end = time.time() + give_up
    while time.time() < end and proc.poll() is None:
        if port_open(port):
            webbrowser.open(url)
            return
        time.sleep(0.4)


def launch(root: Path, app_args: list, port: int, browser: bool) -> int:
    url = f"http://127.0.0.1:{port}"
    if port_open(port):
        say(f"Something is already listening on {url}. If that is Matter Workbench, it is ready to use.")
        say("If you just updated, close the other Matter Workbench window and run this file again.")
        if browser:
            webbrowser.open(url)
        return 0
    if not (root / MODEL_DIR / MODEL_FILE).exists():
        say("Note: the name model is not installed. The app starts, but scrubbing stays blocked. "
            "Run this file again while online to install it.")
    say(f"Starting Matter Workbench on {url}  (Ctrl+C to stop)")
    proc = subprocess.Popen([str(venv_python(root)), "-m", "app", *app_args], cwd=root)
    if browser:
        threading.Thread(target=open_when_ready, args=(port, proc), daemon=True).start()
    try:
        return proc.wait()
    except KeyboardInterrupt:
        try:
            return proc.wait(timeout=10)       # the app got Ctrl+C as well and is shutting down
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            proc.terminate()
            return proc.wait()


def parse(argv: list):
    mine = argparse.ArgumentParser(add_help=False)
    mine.add_argument("--reinstall", action="store_true")
    mine.add_argument("--install-only", action="store_true")
    mine.add_argument("--no-browser", action="store_true")
    mine.add_argument("-h", "--help", action="store_true")
    opts, rest = mine.parse_known_args(argv)
    ports = argparse.ArgumentParser(add_help=False)
    ports.add_argument("--port", type=int, default=DEFAULT_PORT)
    port, _ = ports.parse_known_args(rest)
    return opts, rest, port.port


def main(argv: list | None = None) -> int:
    opts, app_args, port = parse(sys.argv[1:] if argv is None else argv)
    if opts.help:
        say((__doc__ or "").strip())
        return 0
    try:
        check_python()
        # A copy that is already running is left completely alone. Checking its install could replace files it uses.
        if not (opts.reinstall or opts.install_only) and port_open(port):
            return launch(ROOT, app_args, port, browser=not opts.no_browser)
        ensure_environment(ROOT, opts.reinstall)
        ensure_model(ROOT)
        if opts.install_only:
            return 0
        return launch(ROOT, app_args, port, browser=not opts.no_browser)
    except Stop as e:
        print(f"\nStopped. {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
