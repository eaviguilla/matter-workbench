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
             "models/gliner_pii/tokenizer_config.json": "{}", "samples/other_real_call.txt": "private"}
    files.update(extra or {})
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return root


def names(zpath: Path) -> set:
    with zipfile.ZipFile(zpath) as z:
        return {n.split("/", 1)[1] for n in z.namelist() if "/" in n}


def test_the_zip_holds_only_what_the_app_needs(tmp_path):
    z = package.build(tree(tmp_path), tmp_path / "out")
    got = names(z)
    assert {"run.py", "pyproject.toml", "START-HERE.md", "NOTICE.txt", "CHECKSUMS.txt", "app/__init__.py",
            "app/web/static/style.css", "mcp_server/__init__.py", "models/gliner_pii/model_quantized.onnx",
            "samples/sample_call.txt"} <= got
    assert not [n for n in got if n.startswith(("tests/", "design/", ".venv/")) or "__pycache__" in n]
    assert "CLAUDE.md" not in got and "samples/other_real_call.txt" not in got      # allow list, not block list
    assert z.name == "matter-workbench-1.2.3.zip"


def test_a_record_or_secret_in_the_pack_stops_the_build(tmp_path):
    for stray in ("app/client.json", "app/web/.env", "mcp_server/clients.csv", "app/key.pem", "app/notes.docx"):
        root = tree(tmp_path / stray.replace("/", "_"), {stray: "secret"})
        with pytest.raises(SystemExit, match="Refusing"):
            package.build(root, tmp_path / "out")
    assert not list((tmp_path / "out").glob("*.zip")) if (tmp_path / "out").exists() else True


def test_the_model_checksums_match_the_files(tmp_path):
    z = package.build(tree(tmp_path), tmp_path / "out")
    with zipfile.ZipFile(z) as zf:
        sums = zf.read("matter-workbench/CHECKSUMS.txt").decode()
    assert "model_quantized.onnx" in sums and sum(1 for ln in sums.splitlines() if not ln.startswith("#")) == 4


def test_no_model_build_and_a_missing_model_file(tmp_path):
    root = tree(tmp_path)
    assert "models/gliner_pii/tokenizer.json" not in names(package.build(root, tmp_path / "o1", include_model=False))
    (root / "models/gliner_pii/tokenizer.json").unlink()
    with pytest.raises(SystemExit, match="incomplete"):
        package.build(root, tmp_path / "o2")


def test_the_real_project_packs_cleanly():
    # The real tree, without the 570 MB model. Fails if a record-like file ever lands in an allowed folder.
    package.collect(package.ROOT, include_model=False)


# ---- run.py ----------------------------------------------------------------------------------

def project(tmp_path) -> Path:
    root = tmp_path / "p"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text("x")
    return root


def test_old_python_is_refused_with_instructions():
    with pytest.raises(run.Stop, match="3.12"):
        run.check_python((3, 9))
    run.check_python((3, 11))


def test_install_is_needed_until_the_stamp_matches(tmp_path, monkeypatch):
    root = project(tmp_path)
    assert run.install_needed(root) == "first run"
    (root / ".venv").mkdir()
    (root / ".venv" / run.STAMP_NAME).write_text(json.dumps(run.state(root)))
    monkeypatch.setattr(run, "environment_works", lambda r: True)
    assert run.install_needed(root) is None
    monkeypatch.setattr(run, "environment_works", lambda r: False)
    assert run.install_needed(root) == "the environment is damaged"
    monkeypatch.setattr(run, "environment_works", lambda r: True)
    (root / "pyproject.toml").write_text("changed requirements")
    assert "changed" in run.install_needed(root)


def test_moving_the_folder_or_changing_platform_reinstalls(tmp_path):
    a, b = project(tmp_path / "a"), project(tmp_path / "b")
    assert run.state(a) != run.state(b)
    assert run.state(a, "win32") != run.state(a, "darwin")


def test_venv_python_path_per_platform(tmp_path):
    assert run.venv_python(tmp_path, "win32") == tmp_path / ".venv" / "Scripts" / "python.exe"
    assert run.venv_python(tmp_path, "darwin") == tmp_path / ".venv" / "bin" / "python"


def test_checksum_verification(tmp_path):
    root = project(tmp_path)
    f = root / "models" / "gliner_pii" / "m.bin"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"abc")
    assert run.verify_files(root) == 0                                   # no list, no check
    (root / run.CHECKSUMS).write_text(f"# c\n{run.sha256_of(f)}  models/gliner_pii/m.bin\n")
    assert run.verify_files(root) == 1
    f.write_bytes(b"abd")
    with pytest.raises(run.Stop, match="damaged"):
        run.verify_files(root)
    f.unlink()
    with pytest.raises(run.Stop, match="missing"):
        run.verify_files(root)


def test_arguments_split_between_the_launcher_and_the_app():
    opts, rest, port = run.parse(["--no-browser", "--port", "9100", "--demo"])
    assert opts.no_browser and not opts.reinstall and rest == ["--port", "9100", "--demo"] and port == 9100
    assert run.parse(["--port=9200"])[2] == 9200 and run.parse([])[2] == run.DEFAULT_PORT


def test_help_and_a_second_copy_do_not_install_anything(capsys, monkeypatch):
    monkeypatch.setattr(run, "install", lambda *a, **k: pytest.fail("installed"))
    assert run.main(["--help"]) == 0 and "--reinstall" in capsys.readouterr().out
