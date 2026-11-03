"""Shared helpers for tests that drive the web app."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.scrub.evaluate import load_annotated
from app.scrub.ner import NerModel
from app.web import create_app
from tests.fake_ner import FakeBackend

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "http://127.0.0.1:8765"


def make_app(tmp_path, table=None, **kw):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    ner = NerModel(backend_factory=lambda: FakeBackend(table or {}))
    return create_app(tmp_path / "data", env={}, home=home, ner=ner, **kw)


class Session:
    """A browser stand-in: keeps the cookie, reads the CSRF token from the page like app.js does."""

    def __init__(self, app):
        self.c = TestClient(app, base_url=BASE)
        self.token = self._token(self.c.get("/", follow_redirects=False))

    @staticmethod
    def _token(resp):
        m = re.search(r'name="csrf" content="([0-9a-f]+)"', resp.text)
        return m.group(1) if m else None

    def get(self, url, **kw):
        r = self.c.get(url, **kw)
        self.token = self._token(r) or self.token
        return r

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf", self.token)
        r = self.c.post(url, data=data, **kw)
        self.token = self._token(r) or self.token
        return r

    def stored_text(self, tx_id: str) -> str:
        """The scrubbed text kept on disk for a transcript. The page now shows real values, so tests that check what
        was scrubbed read it here."""
        from app.store import Store
        app = self.c.app
        with Store.open(app.state.data_dir, env={}, home=app.state.home) as s:
            return s.get_transcript(tx_id)["scrubbed_text"]

    def post_json(self, url, body):
        return self.c.post(url, json=body, headers={"X-CSRF-Token": self.token})


def fixture_text(n=1):
    p = sorted(FIXTURES.glob("*.ann.txt"))[n - 1]
    return load_annotated(p.stem, p.read_text(encoding="utf-8")).text


def review_form(html, decision="scrub"):
    """Fields a browser would send from the review page, with one decision for every flag."""
    form = {}
    for name, value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', html):
        if name != "csrf":
            form[name] = value
    form["text"] = re.search(r'<textarea name="text"[^>]*>(.*?)</textarea>', html, re.S).group(1)
    import html as h
    form["text"] = h.unescape(form["text"])
    form["carry"] = h.unescape(form.get("carry", "{}"))
    for k in [k for k in form if re.fullmatch(r"w\d+", k)]:
        form[k] = h.unescape(form[k])
        form["d" + k[1:]] = decision
    return form


def saved_tx(response) -> str:
    """The transcript ID from the redirect that follows a save. It lands on the client log with ?saved=TX-..."""
    loc = response.headers["location"]
    assert "/clients/" in loc and "?saved=" in loc, loc
    return loc.split("?saved=", 1)[1]
