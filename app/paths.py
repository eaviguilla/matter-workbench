"""Where the data lives, and the check that keeps it out of synced and Git-tracked folders.

The data folder holds real names in plain text, and a sync service or a Git history would copy them to places the
user does not control. So the app refuses to start there instead of warning.
"""
import json
import os
import sys
from pathlib import Path

APP_NAME = "MatterWorkbench"
ENV_HOME = "MATTER_WORKBENCH_HOME"      # override for the data folder; the same check applies to it
SETTINGS_NAME = "settings.json"
AUDIT_NAME = "audit.jsonl"
LOCK_NAME = ".lock"
CLIENTS_DIR = "clients"
CLIENT_FILE = "client.json"
TRANSCRIPTS_DIR = "transcripts"
TRANSCRIPT_FILE = "transcript.txt"
MACOS_DIR_NAME = APP_NAME + ".noindex"        # Spotlight skips a folder with this ending; tested, a marker file was ignored
_NOT_CONTENT_INDEXED = 0x2000                 # the same request to Windows Search, inherited by new files

# Folder names, lower case. Matched against every part of the resolved path.
_SYNC_NAMES = ("onedrive", "icloud drive", "icloud~", "mobile documents", "dropbox", "cloudstorage")


class UnsafeLocation(Exception):
    """The data folder is somewhere that syncs or is tracked by Git."""


def _fold(p: Path | str) -> str:
    return os.path.normcase(str(p)).casefold()


def _under(path: Path, root: Path) -> bool:
    a, b = _fold(path), _fold(root)
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def default_data_dir(env=None, home: Path | None = None, platform: str | None = None) -> Path:
    env = os.environ if env is None else env
    home = home or Path.home()
    platform = platform or sys.platform
    if env.get(ENV_HOME):
        return Path(env[ENV_HOME]).expanduser()
    if platform == "win32":
        base = env.get("LOCALAPPDATA")
        return (Path(base) if base else home / "AppData" / "Local") / APP_NAME
    if platform == "darwin":
        return home / "Library" / "Application Support" / MACOS_DIR_NAME
    return Path(env.get("XDG_DATA_HOME") or home / ".local" / "share") / APP_NAME


def _sync_roots(env, home: Path) -> list[Path]:
    roots = [Path(env[k]) for k in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer") if env.get(k)]
    roots.append(home / "Library" / "Mobile Documents")
    roots.append(home / "Library" / "CloudStorage")
    for info in (home / ".dropbox" / "info.json",
                 *(Path(env[k]) / "Dropbox" / "info.json" for k in ("APPDATA", "LOCALAPPDATA") if env.get(k))):
        try:
            for account in json.loads(info.read_text(encoding="utf-8")).values():
                if isinstance(account, dict) and account.get("path"):
                    roots.append(Path(account["path"]))
        except (OSError, ValueError):
            continue
    return roots


def check_storage_location(path: Path, env=None, home: Path | None = None) -> Path:
    """Return the resolved folder, or raise UnsafeLocation. The folder need not exist yet."""
    env = os.environ if env is None else env
    home = home or Path.home()
    resolved = Path(path).expanduser().resolve()
    for part in resolved.parts:
        low = part.casefold()
        if any(low == n or low.startswith(n) for n in _SYNC_NAMES):
            raise UnsafeLocation(f"{resolved} is inside a synced folder ({part}). Move the data folder out of it.")
    for root in _sync_roots(env, home):
        if _under(resolved, root.resolve()):
            raise UnsafeLocation(f"{resolved} is inside the synced folder {root}.")
    for folder in (resolved, *resolved.parents):
        if (folder / ".git").exists():            # a directory, or a file for worktrees and submodules
            raise UnsafeLocation(f"{resolved} is inside the Git repository at {folder}.")
    return resolved


def prepare_data_dir(path: Path | None = None, env=None, home: Path | None = None) -> Path:
    """Check the location, create the folder owner-only and out of desktop search, and return it."""
    folder = check_storage_location(path if path is not None else default_data_dir(env, home), env, home)
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        folder.chmod(0o700)
    _exclude_from_search(folder)
    return folder


def _exclude_from_search(folder: Path) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(folder), _NOT_CONTENT_INDEXED)
