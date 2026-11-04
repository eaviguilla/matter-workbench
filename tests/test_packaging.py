"""The package script ships no records, and run.py only installs when it has to."""
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import run
from scripts import package


def tree(tmp_path: Path, extra: dict | None = None) -> Path:
    root = tmp_path / "proj"
    files = {"run.py": "x", "pyproject.toml": 'version = "1.2.3"\n', "README.md": "r", "samples/sample_call.txt": "s",
             "app/__init__.py": "", "app/web/static/style.css": "", "mcp_server/__init__.py": "",
             "tests/test_x.py": "t", "design/p.html": "d", "CLAUDE.md": "c", ".venv/bin/python": "v",
             "app/__pycache__/a.pyc": "c", "models/gliner_pii/gliner_config.json": "{}",
             "models/gliner_pii/model_quantized.onnx": "m", "models/gliner_pii/tokenizer.json": "{}",
             "models/gliner_pii/tokenizer_config.json": "{}", "samples/other_real_call.txt": "private",
             "INSTALL-ZIP.md": "the guide"}
    files.update(extra or {})
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    package.write_manifest(root, "model-v1")
    return root


def names(zpath: Path) -> set:
    with zipfile.ZipFile(zpath) as z:
        return {n.split("/", 1)[1] for n in z.namelist() if "/" in n}


def test_the_zip_holds_only_what_the_app_needs(tmp_path):
    z = package.build(tree(tmp_path), tmp_path / "out")
    got = names(z)
    assert {"run.py", "pyproject.toml", "START-HERE.md", "NOTICE.txt", "models/MODEL-SHA256.txt", "app/__init__.py",
            "app/web/static/style.css", "mcp_server/__init__.py", "models/gliner_pii/model_quantized.onnx",
            "samples/sample_call.txt"} <= got
    assert "CHECKSUMS.txt" not in got
    assert "INSTALL-ZIP.md" not in got and "INSTALL-GIT.md" not in got      # shipped once, as START-HERE.md
    with zipfile.ZipFile(z) as zf:
        assert zf.read("matter-workbench/START-HERE.md").decode() == "the guide"
    assert not [n for n in got if n.startswith(("tests/", "design/", ".venv/")) or "__pycache__" in n]
    assert "CLAUDE.md" not in got and "samples/other_real_call.txt" not in got      # allow list, not block list
    assert z.name == "matter-workbench-1.2.3.zip"


def test_a_record_or_secret_in_the_pack_stops_the_build(tmp_path):
    for stray in ("app/client.json", "app/web/.env", "mcp_server/clients.csv", "app/key.pem", "app/notes.docx"):
        root = tree(tmp_path / stray.replace("/", "_"), {stray: "secret"})
        with pytest.raises(SystemExit, match="Refusing"):
            package.build(root, tmp_path / "out")
    assert not list((tmp_path / "out").glob("*.zip")) if (tmp_path / "out").exists() else True


def test_the_model_list_matches_the_files(tmp_path):
    root = tree(tmp_path)
    z = package.build(root, tmp_path / "out")
    with zipfile.ZipFile(z) as zf:
        listed = zf.read("matter-workbench/models/MODEL-SHA256.txt").decode()
    assert "release model-v1" in listed and "model_quantized.onnx" in listed
    assert sum(1 for ln in listed.splitlines() if len(ln.split()) == 3 and ln.split()[1].isdigit()) == 4
    assert run.read_manifest(root)[0] == "model-v1"                     # run.py reads what package.py wrote
    (root / "models/gliner_pii/model_quantized.onnx").write_text("changed")
    with pytest.raises(SystemExit, match="do not match"):
        package.build(root, tmp_path / "out2")


def test_a_zip_without_the_model_still_carries_the_list(tmp_path):
    got = names(package.build(tree(tmp_path), tmp_path / "out", include_model=False))
    assert "models/MODEL-SHA256.txt" in got and "models/gliner_pii/model_quantized.onnx" not in got


def test_the_list_is_required(tmp_path):
    root = tree(tmp_path)
    (root / "models/MODEL-SHA256.txt").unlink()
    with pytest.raises(SystemExit, match="--manifest"):
        package.build(root, tmp_path / "out")


def test_no_model_build_and_a_missing_model_file(tmp_path):
    root = tree(tmp_path)
    assert "models/gliner_pii/tokenizer.json" not in names(package.build(root, tmp_path / "o1", include_model=False))
    (root / "models/gliner_pii/tokenizer.json").unlink()
    with pytest.raises(SystemExit, match="incomplete"):
        package.build(root, tmp_path / "o2")


def test_the_real_project_packs_cleanly():
    # The real tree, without the 570 MB model. Fails if a record-like file ever lands in an allowed folder.
    package.collect(package.ROOT, include_model=False)


def test_the_committed_model_list_is_readable_and_not_ignored():
    tag, files = run.read_manifest(package.ROOT)
    assert tag and set(files) == set(package.MODEL_FILES)
    ignore = (package.ROOT / ".gitignore").read_text()
    assert "models/*" in ignore and "!models/MODEL-SHA256.txt" in ignore


# ---- run.py ----------------------------------------------------------------------------------

GOOD = """[project]
name = "x"
version = "0.1.0"
description = "words"
requires-python = ">=3.11"
dependencies = ["fastapi"]
[project.optional-dependencies]
ner = ["numpy"]
"""


def project(tmp_path, text: str = GOOD) -> Path:
    root = tmp_path / "p"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text(text)
    return root


def test_old_python_is_refused_with_instructions():
    with pytest.raises(run.Stop, match="3.13"):
        run.check_python((3, 9))
    run.check_python((3, 11))


def stamped(root, platform=None):
    (root / ".venv").mkdir(exist_ok=True)
    run.write_stamp(root, platform)


def test_nothing_to_do_when_the_stamp_matches_and_the_environment_works(tmp_path, monkeypatch):
    root = project(tmp_path)
    assert run.plan(root) == ("rebuild", "first run")                      # no .venv at all
    stamped(root)
    monkeypatch.setattr(run, "environment_works", lambda r: True)
    assert run.plan(root) == ("none", "")
    monkeypatch.setattr(run, "environment_works", lambda r: False)
    assert run.plan(root) == ("rebuild", "the environment is damaged")


def test_a_working_environment_without_a_note_is_adopted_not_rebuilt(tmp_path, monkeypatch):
    root = project(tmp_path)
    (root / ".venv").mkdir()
    monkeypatch.setattr(run, "environment_works", lambda r: True)
    assert run.plan(root)[0] == "stamp"                                    # a hand-made or older environment
    (root / ".venv" / run.STAMP_NAME).write_text(json.dumps({"project": str(root), "platform": sys.platform,
                                                              "pyproject": "old format"}))
    assert run.plan(root)[0] == "stamp"                                    # a note written by an older run.py
    monkeypatch.setattr(run, "environment_works", lambda r: False)
    assert run.plan(root)[0] == "rebuild"                                  # only a broken one is rebuilt


def test_only_a_change_to_the_requirements_upgrades_in_place(tmp_path, monkeypatch):
    root = project(tmp_path)
    stamped(root)
    monkeypatch.setattr(run, "environment_works", lambda r: True)
    (root / "pyproject.toml").write_text(GOOD.replace('version = "0.1.0"', 'version = "9.9.9"')
                                         .replace('"words"', '"other words"'))
    assert run.plan(root)[0] == "none"                                     # version and description are not requirements
    (root / "pyproject.toml").write_text(GOOD.replace('["fastapi"]', '["fastapi", "jinja2"]'))
    assert run.plan(root) == ("upgrade", "the requirements changed")
    (root / "pyproject.toml").write_text(GOOD.replace('["numpy"]', '["numpy", "tokenizers"]'))
    assert run.plan(root)[0] == "upgrade"
    (root / "pyproject.toml").write_text("not = [valid toml")
    assert run.plan(root)[0] == "upgrade"                                  # still fingerprinted, never an error


def test_moving_the_folder_keeps_a_working_environment(tmp_path, monkeypatch):
    a, b = project(tmp_path / "a"), project(tmp_path / "b")
    assert run.state(a) != run.state(b)
    stamped(b)
    (b / ".venv" / run.STAMP_NAME).write_text(json.dumps(run.state(a)))   # built where a is, now living at b
    monkeypatch.setattr(run, "environment_works", lambda r: True)
    assert run.plan(b) == ("stamp", "the folder was moved")


def test_another_computer_type_rebuilds(tmp_path, monkeypatch):
    root = project(tmp_path)
    assert run.state(root, "win32") != run.state(root, "darwin")
    stamped(root, "win32")
    monkeypatch.setattr(run, "environment_works", lambda r: True)
    assert run.plan(root, "darwin")[0] == "rebuild"


def test_ensure_environment_deletes_and_installs_nothing_when_all_is_in_place(tmp_path, monkeypatch, capsys):
    root = project(tmp_path)
    stamped(root)
    marker = root / ".venv" / "keep.txt"
    marker.write_text("x")
    monkeypatch.setattr(run, "environment_works", lambda r: True)
    for name in ("install", "upgrade", "run_step", "pip_install"):
        monkeypatch.setattr(run, name, lambda *a, **k: pytest.fail("changed the environment"))
    assert run.ensure_environment(root) == "none"
    assert marker.read_text() == "x" and "Already installed" in capsys.readouterr().out


def test_ensure_environment_picks_the_smallest_action(tmp_path, monkeypatch):
    calls = []
    root = project(tmp_path)
    monkeypatch.setattr(run, "install", lambda r, why="": calls.append(("install", why)))
    monkeypatch.setattr(run, "upgrade", lambda r, why="": calls.append(("upgrade", why)))
    monkeypatch.setattr(run, "plan", lambda r: ("upgrade", "the requirements changed"))
    assert run.ensure_environment(root) == "upgrade" and calls == [("upgrade", "the requirements changed")]
    monkeypatch.setattr(run, "plan", lambda r: ("rebuild", "first run"))
    run.ensure_environment(root)
    run.ensure_environment(root, reinstall=True)
    assert [c[0] for c in calls] == ["upgrade", "install", "install"] and calls[-1][1] == "requested"


def test_venv_python_path_per_platform(tmp_path):
    assert run.venv_python(tmp_path, "win32") == tmp_path / ".venv" / "Scripts" / "python.exe"
    assert run.venv_python(tmp_path, "darwin") == tmp_path / ".venv" / "bin" / "python"


def test_arguments_split_between_the_launcher_and_the_app():
    opts, rest, port = run.parse(["--no-browser", "--port", "9100", "--demo"])
    assert opts.no_browser and not opts.reinstall and rest == ["--port", "9100", "--demo"] and port == 9100
    assert run.parse(["--port=9200"])[2] == 9200 and run.parse([])[2] == run.DEFAULT_PORT


def test_help_does_not_install_anything(capsys, monkeypatch):
    monkeypatch.setattr(run, "install", lambda *a, **k: pytest.fail("installed"))
    assert run.main(["--help"]) == 0 and "--reinstall" in capsys.readouterr().out


def test_a_copy_that_is_already_running_is_left_alone(monkeypatch, capsys):
    launched = []
    monkeypatch.setattr(run, "port_open", lambda p, host="127.0.0.1": True)
    monkeypatch.setattr(run, "webbrowser", type("W", (), {"open": staticmethod(lambda u: launched.append(u))}))
    for name in ("ensure_environment", "ensure_model", "install", "upgrade"):
        monkeypatch.setattr(run, name, lambda *a, **k: pytest.fail("touched the install of a running app"))
    assert run.main(["--port", "9111"]) == 0
    assert launched == ["http://127.0.0.1:9111"] and "already listening" in capsys.readouterr().out


def test_install_only_checks_both_even_when_something_answers_the_port(monkeypatch):
    seen = []
    monkeypatch.setattr(run, "port_open", lambda p, host="127.0.0.1": True)
    monkeypatch.setattr(run, "ensure_environment", lambda root, reinstall=False: seen.append("environment"))
    monkeypatch.setattr(run, "ensure_model", lambda root: seen.append("model"))
    assert run.main(["--install-only"]) == 0 and seen == ["environment", "model"]


def test_the_install_guides_exist_and_agree_with_run_py():
    zip_guide = (package.ROOT / "INSTALL-ZIP.md").read_text(encoding="utf-8")
    git_guide = (package.ROOT / "INSTALL-GIT.md").read_text(encoding="utf-8")
    for guide in (zip_guide, git_guide):
        for flag in ("--port", "--no-browser", "--reinstall", "--install-only"):
            assert flag in guide
        assert "python3 run.py" in guide and "py run.py" in guide
        assert not [ch for ch in ("\u2014", "\u2013") if ch in guide]                  # no em or en dashes
    assert run.venv_dir(package.ROOT).name in zip_guide                       # the app.check path
    assert "git clone https://github.com/eaviguilla/matter-workbench.git" in git_guide
    assert "MODEL-SHA256.txt" in git_guide
