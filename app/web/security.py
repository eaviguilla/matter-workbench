"""Host check, session cookie, CSRF token and response headers for the local web app."""
import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
SESSION_COOKIE = "mw_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# A paste of MAX_PASTE characters can be 4-byte characters (emoji), which a form posts as 12 bytes each. A lower cap
# would refuse a paste the app says it accepts, and the pasted text would be lost with the page.
MAX_BODY = 6_000_000


async def read_form(request: Request):
    """The posted form. Starlette's defaults (one field up to 1 MB, 1000 fields) are lower than what the app accepts: a
    long paste is one big field, and the review form posts three fields for every flagged word. The body cap above
    already bounds the total. The first read is kept for the rest of the request, so the CSRF guard must use this
    too."""
    return await request.form(max_fields=float("inf"), max_files=0, max_part_size=MAX_BODY)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
       "font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def host_allowed(header: str | None) -> bool:
    if not header:
        return False
    host = header.rsplit(":", 1)[0] if not header.endswith("]") and ":" in header else header
    return host.lower() in ALLOWED_HOSTS


class Csrf:
    def __init__(self, secret: bytes | None = None):
        self._secret = secret or secrets.token_bytes(32)

    def token(self, session_id: str) -> str:
        return hmac.new(self._secret, session_id.encode(), hashlib.sha256).hexdigest()

    def valid(self, session_id: str | None, token: str | None) -> bool:
        return bool(session_id and token) and hmac.compare_digest(self.token(session_id), token)


async def csrf_guard(request: Request) -> None:
    """Dependency on every router: a state-changing request must carry the token for its session."""
    if request.method in SAFE_METHODS:
        return
    token = request.headers.get("x-csrf-token")
    if token is None and request.headers.get("content-type", "").startswith(("application/x-www-form-urlencoded",
                                                                              "multipart/form-data")):
        token = (await read_form(request)).get("csrf")
    if not request.app.state.csrf.valid(request.state.sid, token):
        raise HTTPException(403, "Missing or invalid CSRF token. Reload the page and try again.")
