"""run.py installs the name model by download or from the package, and does nothing when it is already right."""
import hashlib
import http.server
import io
import threading
import urllib.error
from pathlib import Path

import pytest

import run

FILES = {"a.json": b"{}", "model.onnx": b"m" * 5000, "tok.json": b"t" * 300}


def listing(files: dict, tag: str = "model-v1") -> str:
    lines = [f"release {tag}"]
    lines += [f"{hashlib.sha256(body).hexdigest()}  {len(body)}  {name}" for name, body in files.items()]
    return "# list\n" + "\n".join(lines) + "\n"


def project(tmp_path: Path, files: dict = FILES, tag: str = "model-v1", present: dict | None = None) -> Path:
    root = tmp_path / "my project"                          # a space in the path on purpose
    (root / "models").mkdir(parents=True)
    (root / run.MANIFEST).write_text(listing(files, tag))
    if present:
        (root / run.MODEL_DIR).mkdir(parents=True)
        for name, body in present.items():
            (root / run.MODEL_DIR / name).write_bytes(body)
    return root


class Resp(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status


class Server:
    """A fake release. It records every request and can be told to misbehave."""

    def __init__(self, files: dict, ranges: bool = True):
        self.files, self.ranges, self.calls, self.fail = dict(files), ranges, [], []

    def __call__(self, url: str, start: int = 0):
        name = url.rsplit("/", 1)[1]
        self.calls.append((name, start))
        if self.fail:
            raise self.fail.pop(0)
        body = self.files[name]
        if start and self.ranges:
            return Resp(body[start:], 206)
        return Resp(body, 200)


def quiet(monkeypatch):
    monkeypatch.setattr(run.shutil, "disk_usage", lambda p: type("U", (), {"free": 10**12})())


def test_a_missing_model_is_downloaded_checked_and_placed(tmp_path, monkeypatch, capsys):
    quiet(monkeypatch)
    root = project(tmp_path)
    server = Server(FILES)
    assert run.ensure_model(root, opener=server, sleep=lambda s: None) is True
    for name, body in FILES.items():
        assert (root / run.MODEL_DIR / name).read_bytes() == body
    assert sorted(n for n, _ in server.calls) == sorted(FILES)
    assert not list((root / run.MODEL_DIR).glob(".download-*"))
    assert (root / run.MODEL_DIR / run.VERIFIED_NAME).exists()
    assert "installed" in capsys.readouterr().out


def test_the_urls_point_at_the_release_named_in_the_list(tmp_path, monkeypatch):
    quiet(monkeypatch)
    urls = []
    root = project(tmp_path, tag="model-v7")
    server = Server(FILES)
    run.ensure_model(root, opener=lambda u, s=0: (urls.append(u), server(u, s))[1], sleep=lambda s: None)
    assert {u.rsplit("/", 1)[0] for u in urls} == {
        "https://github.com/eaviguilla/matter-workbench/releases/download/model-v7"}


def test_a_second_run_does_nothing_at_all(tmp_path, monkeypatch):
    quiet(monkeypatch)
    root = project(tmp_path)
    assert run.ensure_model(root, opener=Server(FILES), sleep=lambda s: None)
    monkeypatch.setattr(run, "sha256_of", lambda p: pytest.fail("hashed a file that was already checked"))
    monkeypatch.setattr(run.shutil, "disk_usage", lambda p: pytest.fail("looked at the disk"))
    assert run.ensure_model(root, opener=lambda *a: pytest.fail("used the network")) is True


def test_files_from_the_zip_are_checked_once_and_nothing_is_downloaded(tmp_path, monkeypatch):
    root = project(tmp_path, present=FILES)
    assert run.ensure_model(root, opener=lambda *a: pytest.fail("used the network")) is True
    assert (root / run.MODEL_DIR / run.VERIFIED_NAME).exists()
    monkeypatch.setattr(run, "sha256_of", lambda p: pytest.fail("hashed again"))
    assert run.ensure_model(root, opener=lambda *a: pytest.fail("used the network")) is True


def test_a_changed_file_is_noticed_and_only_that_file_is_fetched(tmp_path, monkeypatch):
    quiet(monkeypatch)
    root = project(tmp_path, present=FILES)
    assert run.ensure_model(root)
    newer = dict(FILES, **{"model.onnx": b"n" * 6000})
    (root / run.MANIFEST).write_text(listing(newer, "model-v2"))
    server = Server(newer)
    assert run.ensure_model(root, opener=server, sleep=lambda s: None) is True
    assert server.calls == [("model.onnx", 0)]
    assert (root / run.MODEL_DIR / "model.onnx").read_bytes() == newer["model.onnx"]


def test_the_old_file_stays_until_the_new_one_is_verified(tmp_path, monkeypatch):
    quiet(monkeypatch)
    root = project(tmp_path, present=FILES)
    assert run.ensure_model(root)
    newer = dict(FILES, **{"model.onnx": b"n" * 6000})
    (root / run.MANIFEST).write_text(listing(newer, "model-v2"))
    bad = Server(dict(newer, **{"model.onnx": b"x" * 6000}))               # right size, wrong content
    assert run.ensure_model(root, opener=bad, sleep=lambda s: None) is False
    assert (root / run.MODEL_DIR / "model.onnx").read_bytes() == FILES["model.onnx"]


def test_an_interrupted_download_continues_where_it_stopped(tmp_path, monkeypatch):
    quiet(monkeypatch)
    root = project(tmp_path)
    part = root / run.MODEL_DIR / ".download-model-v1" / "model.onnx.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(FILES["model.onnx"][:2000])
    server = Server(FILES)
    assert run.ensure_model(root, opener=server, sleep=lambda s: None) is True
    assert ("model.onnx", 2000) in server.calls
    assert (root / run.MODEL_DIR / "model.onnx").read_bytes() == FILES["model.onnx"]


def test_a_server_that_ignores_the_range_request_restarts_the_file(tmp_path, monkeypatch):
    quiet(monkeypatch)
    root = project(tmp_path)
    part = root / run.MODEL_DIR / ".download-model-v1" / "model.onnx.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(FILES["model.onnx"][:2000])
    assert run.ensure_model(root, opener=Server(FILES, ranges=False), sleep=lambda s: None) is True
    assert (root / run.MODEL_DIR / "model.onnx").read_bytes() == FILES["model.onnx"]


def test_a_damaged_download_is_discarded_and_tried_again(tmp_path, monkeypatch):
    quiet(monkeypatch)
    root = project(tmp_path)
    server = Server(FILES)
    first = {"done": False}

    def flaky(url, start=0):
        if url.endswith("model.onnx") and not first["done"]:
            first["done"] = True
            return Resp(b"x" * len(FILES["model.onnx"]))
        return server(url, start)
    assert run.ensure_model(root, opener=flaky, sleep=lambda s: None) is True
    assert (root / run.MODEL_DIR / "model.onnx").read_bytes() == FILES["model.onnx"]


def test_no_connection_is_reported_plainly_and_does_not_stop_the_app(tmp_path, monkeypatch, capsys):
    quiet(monkeypatch)
    root = project(tmp_path)
    pauses = []
    server = Server(FILES)
    server.fail = [urllib.error.URLError("offline")] * 3
    assert run.ensure_model(root, opener=server, sleep=pauses.append) is False
    out = capsys.readouterr().out
    assert "Name model:" in out and "Run this again when online" in out
    assert pauses == list(run.RETRY_WAITS)
    assert not (root / run.MODEL_DIR / "model.onnx").exists()


def test_a_missing_release_and_a_proxy_have_their_own_messages(tmp_path, monkeypatch, capsys):
    quiet(monkeypatch)
    for code, words in ((404, "not on GitHub"), (407, "proxy")):
        root = project(tmp_path / str(code))
        server = Server(FILES)
        server.fail = [urllib.error.HTTPError("u", code, "x", {}, None)]
        assert run.ensure_model(root, opener=server, sleep=lambda s: None) is False
        assert words in capsys.readouterr().out


def test_too_little_disk_space_stops_before_any_download(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run.shutil, "disk_usage", lambda p: type("U", (), {"free": 1000})())
    root = project(tmp_path)
    assert run.ensure_model(root, opener=lambda *a: pytest.fail("used the network")) is False
    out = capsys.readouterr().out
    assert "Free some space" in out and "GB" in out


def test_without_a_list_the_model_file_decides(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    assert run.ensure_model(root) is False
    (root / run.MODEL_DIR).mkdir(parents=True)
    (root / run.MODEL_DIR / run.MODEL_FILE).write_bytes(b"x")
    assert run.ensure_model(root) is True


def test_a_list_with_an_unsafe_name_is_refused(tmp_path):
    root = project(tmp_path)
    sha = hashlib.sha256(b"x").hexdigest()
    for name in ("../evil.bin", "a/b.bin", ".hidden", "a b"):
        (root / run.MANIFEST).write_text(f"release model-v1\n{sha}  1  {name}\n")
        with pytest.raises(run.Stop):
            run.read_manifest(root)
    (root / run.MANIFEST).write_text(f"release ../x\n{sha}  1  ok.bin\n")
    with pytest.raises(run.Stop):
        run.read_manifest(root)
    (root / run.MANIFEST).write_text("release model-v1\n")
    with pytest.raises(run.Stop):
        run.read_manifest(root)


def test_progress_on_a_terminal_and_in_a_log(capsys):
    log = io.StringIO()
    p = run.Progress(1000, "Downloading", log)
    for _ in range(10):
        p.add(100)
    lines = log.getvalue().strip().splitlines()
    assert lines[-1].endswith("100 percent") and len(lines) <= 11 and "\r" not in log.getvalue()


def test_a_real_download_over_a_socket(tmp_path, monkeypatch):
    quiet(monkeypatch)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = FILES.get(self.path.rsplit("/", 1)[1])
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Length", str(len(body or b"")))
            self.end_headers()
            self.wfile.write(body or b"")

        def log_message(self, *a):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setattr(run, "RELEASE_URL", f"http://127.0.0.1:{httpd.server_port}/{{tag}}/{{name}}")
    try:
        root = project(tmp_path)
        assert run.ensure_model(root, sleep=lambda s: None) is True
        assert (root / run.MODEL_DIR / "model.onnx").read_bytes() == FILES["model.onnx"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_moving_a_file_retries_while_windows_holds_it(tmp_path, monkeypatch):
    src, dst = tmp_path / "a.part", tmp_path / "a"
    src.write_bytes(b"x")
    real, tries = run.os.replace, []

    def busy(a, b):
        tries.append(1)
        if len(tries) < 3:
            raise PermissionError("held")
        real(a, b)
    monkeypatch.setattr(run.os, "replace", busy)
    run.move_into_place(src, dst, sleep=lambda s: None)
    assert dst.read_bytes() == b"x" and len(tries) == 3


def test_data_folders_are_never_touched(tmp_path, monkeypatch):
    home, local = tmp_path / "home", tmp_path / "local"
    home.mkdir()
    local.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    quiet(monkeypatch)
    root = project(tmp_path)
    run.ensure_model(root, opener=Server(FILES), sleep=lambda s: None)
    assert list(home.iterdir()) == [] and list(local.iterdir()) == []


def test_a_certificate_failure_says_how_to_fix_it(tmp_path, monkeypatch, capsys):
    quiet(monkeypatch)
    root = project(tmp_path)
    server = Server(FILES)
    server.fail = [urllib.error.URLError(run.ssl.SSLCertVerificationError("bad"))]
    assert run.ensure_model(root, opener=server, sleep=lambda s: None) is False
    out = capsys.readouterr().out
    assert "Install Certificates.command" in out and "No internet connection" not in out


def test_pip_certificates_are_tried_from_the_environment_then_from_this_python(tmp_path, monkeypatch):
    cafile = tmp_path / "cacert.pem"
    cafile.write_text("x")
    asked = []

    def fake_run(cmd, **kwargs):
        asked.append(cmd[0])
        return type("R", (), {"returncode": 0 if len(asked) == 2 else 1, "stdout": str(cafile) + "\n"})()
    monkeypatch.setattr(run.subprocess, "run", fake_run)
    assert run.pip_cacert(tmp_path) == str(cafile)
    assert asked == [str(run.venv_python(tmp_path)), run.sys.executable]
