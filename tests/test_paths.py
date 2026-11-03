import json
import os
import sys

import pytest

from app.paths import UnsafeLocation, check_storage_location, default_data_dir, prepare_data_dir


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def test_default_folder_per_platform(home):
    mac = default_data_dir(env={}, home=home, platform="darwin")
    assert mac == home / "Library" / "Application Support" / "MatterWorkbench.noindex"
    win = default_data_dir(env={"LOCALAPPDATA": r"C:\Users\e\AppData\Local"}, home=home, platform="win32")
    assert win.name == "MatterWorkbench" and "AppData" in str(win)
    assert default_data_dir(env={}, home=home, platform="linux") == home / ".local" / "share" / "MatterWorkbench"


def test_env_override_is_used_and_still_checked(home, tmp_path):
    target = tmp_path / "elsewhere"
    assert default_data_dir(env={"MATTER_WORKBENCH_HOME": str(target)}, home=home) == target
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(UnsafeLocation):
        prepare_data_dir(env={"MATTER_WORKBENCH_HOME": str(tmp_path / "repo" / "data")}, home=home)


def test_safe_folder_is_accepted_and_created_owner_only(home, tmp_path):
    folder = prepare_data_dir(tmp_path / "data" / "app", env={}, home=home)
    assert folder.is_dir()
    if os.name == "posix":
        assert folder.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("parts", [("OneDrive", "x"), ("OneDrive - Contoso Ltd", "x"), ("ONEDRIVE",),
                                   ("iCloud Drive", "x"), ("Dropbox", "x"), ("Library", "Mobile Documents", "x"),
                                   ("Library", "CloudStorage", "GoogleDrive-a@b.com", "x")])
def test_synced_folder_names_are_refused(home, tmp_path, parts):
    with pytest.raises(UnsafeLocation):
        check_storage_location(tmp_path.joinpath(*parts), env={}, home=home)


def test_onedrive_env_var_root_is_refused(home, tmp_path):
    root = tmp_path / "work files"
    with pytest.raises(UnsafeLocation):
        check_storage_location(root / "data", env={"OneDriveCommercial": str(root)}, home=home)
    check_storage_location(tmp_path / "other", env={"OneDriveCommercial": str(root)}, home=home)


def test_dropbox_folder_from_info_json_is_refused(home, tmp_path):
    box = tmp_path / "my stuff"
    (home / ".dropbox").mkdir()
    (home / ".dropbox" / "info.json").write_text(json.dumps({"personal": {"path": str(box)}}))
    with pytest.raises(UnsafeLocation):
        check_storage_location(box / "data", env={}, home=home)


def test_git_directory_or_file_in_any_parent_is_refused(home, tmp_path):
    (tmp_path / "a" / ".git").mkdir(parents=True)
    with pytest.raises(UnsafeLocation, match="Git"):
        check_storage_location(tmp_path / "a" / "b" / "c", env={}, home=home)
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / ".git").write_text("gitdir: ../elsewhere")     # worktree or submodule
    with pytest.raises(UnsafeLocation):
        check_storage_location(tmp_path / "w" / "data", env={}, home=home)


def test_symlink_into_a_synced_folder_is_resolved(home, tmp_path):
    if sys.platform == "win32":
        pytest.skip("symlinks need privileges on Windows")
    (tmp_path / "Dropbox").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "Dropbox")
    with pytest.raises(UnsafeLocation):
        check_storage_location(tmp_path / "link" / "data", env={}, home=home)
