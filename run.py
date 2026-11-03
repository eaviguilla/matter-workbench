#!/usr/bin/env python3
"""Matter Workbench launcher. Run it with Python 3.11 or newer on macOS or Windows:

    python3 run.py        (macOS)
    py run.py             (Windows)

The first run builds a private environment in .venv, installs everything the app needs, checks the name
model, and starts the app. Later runs see that the install is done and only start the app.

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
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIN_PYTHON = (3, 11)
MODEL_DIR = Path("models") / "gliner_pii"
MODEL_FILE = "model_quantized.onnx"
CHECKSUMS = "CHECKSUMS.txt"
EXTRA = ".[ner]"
DEFAULT_PORT = 8765
STAMP_NAME = "installed.json"


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
            "Install Python 3.12 from https://www.python.org/downloads/ and run this file again.\n"
            "  macOS:    python3.12 run.py\n"
            "  Windows:  py -3.12 run.py   (tick 'Add python.exe to PATH' in the installer)")


def state(root: Path = ROOT, platform: str | None = None) -> dict:
    """What the installed environment was built for. If any of it changes, the install is redone."""
    return {"project": str(root), "platform": platform or sys.platform,
            "pyproject": hashlib.sha256((root / "pyproject.toml").read_bytes()).hexdigest()}


def read_stamp(root: Path = ROOT) -> dict | None:
    try:
        return json.loads((venv_dir(root) / STAMP_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def environment_works(root: Path = ROOT) -> bool:
    py = venv_python(root)
    if not py.exists():
        return False
    try:
        done = subprocess.run([str(py), "-c", "import app, uvicorn, fastapi"], cwd=root, capture_output=True,
                              timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def install_needed(root: Path = ROOT, platform: str | None = None) -> str | None:
    """None when the environment is ready, else a short reason."""
    stamp = read_stamp(root)
    if stamp is None:
        return "first run"
    if stamp != state(root, platform):
        return "the folder or its requirements changed"
    if not environment_works(root):
        return "the environment is damaged"
    return None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_files(root: Path = ROOT) -> int:
    """Check every file listed in CHECKSUMS.txt. Returns how many were checked. No list means no check."""
    listing = root / CHECKSUMS
    if not listing.exists():
        return 0
    checked = 0
    for line in listing.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, rel = line.partition("  ")
        target = root / rel.strip()
        if not target.exists():
            raise Stop(f"{rel.strip()} is missing. Unzip the package again, completely, and re-run.")
        if sha256_of(target) != digest.strip():
            raise Stop(f"{rel.strip()} is damaged (its checksum does not match). Copy the package again.")
        checked += 1
    return checked


def run_step(cmd: list, root: Path, what: str, hint: str = "") -> None:
    say(f"  {what} ...")
    try:
        code = subprocess.call(cmd, cwd=root)
    except OSError as e:
        raise Stop(f"Could not run {cmd[0]}: {e}")
    if code != 0:
        raise Stop(f"{what} failed (exit code {code}). {hint}".strip())


def install(root: Path = ROOT, reason: str = "") -> None:
    say(f"Installing Matter Workbench ({reason}). This takes a few minutes and needs an internet connection.")
    n = verify_files(root)
    if n:
        say(f"  Checked {n} file{'s' if n != 1 else ''} against {CHECKSUMS}.")
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
    net = "Check the internet connection and run this file again."
    run_step([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--upgrade", "pip"], root,
             "Updating pip", net)
    run_step([py, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-e", EXTRA], root,
             "Installing the app and its libraries",
             net + " If pip says no matching distribution exists, install Python 3.12 or 3.13 and use it to run this file.")
    if not environment_works(root):
        raise Stop("The install finished but the app cannot be imported. Run again with --reinstall.")
    (env / STAMP_NAME).write_text(json.dumps(state(root), indent=2), encoding="utf-8")
    say("  Install complete.")


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
        if browser:
            webbrowser.open(url)
        return 0
    if not (root / MODEL_DIR / MODEL_FILE).exists():
        say(f"Note: the name model is not in {MODEL_DIR}. The app starts, but scrubbing stays blocked until it is added.")
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
        if opts.reinstall:
            reason = "requested"
        else:
            reason = install_needed(ROOT)
        if reason:
            install(ROOT, reason)
        else:
            say("Already installed.")
        if opts.install_only:
            return 0
        return launch(ROOT, app_args, port, browser=not opts.no_browser)
    except Stop as e:
        print(f"\nStopped. {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
