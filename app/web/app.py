"""The local web app. Binds to 127.0.0.1 (see app/__main__.py) and rejects any other Host header."""
import json
import logging
import re
import secrets
import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import workflow as wf
from ..ids import CLIENT_ID_RE, TX_ID_RE
from ..scrub.ner import NerConfig, NerModel, NerUnavailable
from ..scrub.parse import TranscriptFormatError
from ..rehydrate import rehydrate
from ..scrub.registry import PlaceholderValue
from ..store import Busy, Damaged, Store
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import security

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = HERE.parent.parent / "models" / "gliner_pii"
log = logging.getLogger("matterworkbench")      # IDs and counts only, never transcript text or values
PENDING_KEEP_MINUTES = 60      # an unsaved new-client review survives a restart for this long
MCP_COMMAND = f"{sys.executable} -m mcp_server"
DONE_NOTICES = {"renamed": "Renamed to {name}. The ID {cid} stays the same.",
                "archived": "Client archived. Find it under Archived in the sidebar.",
                "restored": "Client restored to the sidebar."}
KEEP_PARAM = re.compile(r"^(?:\d{1,6}|prev)$")


VIEWS = ("outputs", "transcript")
STATE_KEYS = tuple(k for slug in wf.OUTPUT_SLUGS for k in (slug, f"cmp-{slug}"))     # per-output version and compare


def client_url(cid: str, tx: str | None = None, view: str | None = None, extra: dict | None = None, anchor: str = "") -> str:
    """The client page with a call selected. Only IDs, numbers and fixed words go in the address, never a value."""
    q = {k: v for k, v in (("tx", tx), ("view", view)) if v}
    q.update(extra or {})
    return f"/clients/{cid}" + (f"?{urlencode(q)}" if q else "") + anchor


def create_app(data_dir: Path | None = None, env=None, home=None,
               ner: NerModel | None = None, model_dir: Path | None = None) -> FastAPI:
    first = Store.open(data_dir, env=env, home=home)                # refuses unsafe folders now
    first.clean_up()                                                # what a crash can leave behind
    first.purge_pending(older_than_minutes=PENDING_KEEP_MINUTES)    # reviews that were never saved, not one just open
    csrf_secret = first.form_secret()                               # same after a restart, so open pages still save
    first.close()

    @asynccontextmanager
    async def lifespan(app):
        app.state.ner.start_reaper()
        yield
        app.state.ner.stop_reaper()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.csrf = security.Csrf(csrf_secret)
    app.state.flash = {}                      # one-time notices by session, kept in memory only
    app.state.ner = ner or NerModel(NerConfig(model_dir=model_dir or DEFAULT_MODEL_DIR))
    app.state.data_dir, app.state.home = data_dir, home
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals["FORM_SLUGS"] = wf.FORM_SLUGS
    templates.env.filters["local_day"] = wf.local_day
    templates.env.filters["local_time"] = wf.local_time
    templates.env.filters["long_day"] = wf.long_day
    templates.env.filters["short_day"] = wf.short_day
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def open_store() -> Store:
        s = Store.open(data_dir, env=env, home=home)
        wf.apply_settings(app.state.ner, wf.load_settings(s))
        return s

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not security.host_allowed(request.headers.get("host")):
            return PlainTextResponse("Forbidden host", status_code=403)
        if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
            return PlainTextResponse("Cross-site requests are not allowed", status_code=403)
        if int(request.headers.get("content-length") or 0) > security.MAX_BODY:
            return PlainTextResponse("Request too large", status_code=413)
        sid = request.cookies.get(security.SESSION_COOKIE)
        fresh = sid is None or len(sid) < 20
        request.state.sid = secrets.token_urlsafe(32) if fresh else sid
        request.state.csrf = app.state.csrf.token(request.state.sid)
        try:
            response = await call_next(request)
        except Exception as e:                  # type name only: messages can hold real values
            log.error("unhandled %s on %s %s", type(e).__name__, request.method, request.url.path)
            response = PlainTextResponse("Something went wrong. Check the terminal for the error type.", 500)
        if fresh:
            response.set_cookie(security.SESSION_COOKIE, request.state.sid, httponly=True, samesite="strict",
                                path="/")
        for k, v in security.HEADERS.items():
            response.headers[k] = v
        return response

    router = APIRouter(dependencies=[Depends(security.csrf_guard)])

    def render(request: Request, name: str, **ctx) -> HTMLResponse:
        with open_store() as s:
            if "clients" not in ctx:
                everyone = wf.client_rows(s, include_archived=True)
                ctx["clients"] = [c for c in everyone if not c["archived"]]
            ctx["archived_clients"] = [c for c in wf.client_rows(s, include_archived=True) if c["archived"]]
            ctx["damaged_clients"] = s.damaged
        ctx.update(request=request, csrf=request.state.csrf, model_ok=app.state.ner.available,
                   status_labels=wf.STATUS_LABELS)
        return templates.TemplateResponse(request, name, ctx)

    @app.exception_handler(StarletteHTTPException)
    async def friendly_errors(request: Request, exc: StarletteHTTPException):
        """A person who submitted a form sees a page with a way back. Scripts keep the JSON they expect."""
        wants_page = ("text/html" in request.headers.get("accept", "")
                      and "json" not in request.headers.get("content-type", "")
                      and hasattr(request.state, "csrf") and not request.url.path.startswith("/static/"))
        if not wants_page:
            return await http_exception_handler(request, exc)
        heading = {403: "This page expired", 404: "Not found"}.get(exc.status_code, "Something went wrong")
        detail = ("Your session expired. Go back, reload the page, and submit again. Pasted text was not saved."
                  if exc.status_code == 403 else str(exc.detail))
        resp = render(request, "error.html", status=exc.status_code, heading=heading, detail=detail)
        resp.status_code = exc.status_code
        return resp

    @app.exception_handler(Damaged)
    @app.exception_handler(Busy)
    async def storage_errors(request: Request, exc: Exception):
        """A damaged file affects one client, so the page names it and the rest of the app keeps working."""
        heading = "The workbench is busy" if isinstance(exc, Busy) else "A saved file needs repair"
        detail = str(exc) if isinstance(exc, Busy) else (f"{exc} Run python -m app.check for a report that is safe to "
                                                         "share. Do not share the file itself, which holds real names.")
        if not hasattr(request.state, "csrf"):
            return PlainTextResponse(detail, status_code=503)
        resp = render(request, "error.html", status=503, heading=heading, detail=detail)
        resp.status_code = 503
        return resp

    def call_day(day: str) -> date:
        """The call date, or ValueError. A future date is almost always a typo, and it would sort wrongly. So is
        a year like 0001 or 0202, which would also make a transcript ID that other tools read as a different date."""
        d = date.fromisoformat(day)
        if d > date.today():
            raise ValueError("The call date is in the future.")
        if d < wf.EARLIEST_CALL:
            raise ValueError("The call date is too far in the past.")
        return d

    def maybe_int(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def bad_form(detail="The form data was damaged. Go back and submit the page again."):
        return HTTPException(400, detail)

    def client_or_404(s: Store, cid: str):
        c = s.get_client(cid) if CLIENT_ID_RE.match(cid) else None
        if c is None:
            raise HTTPException(404, "No such client")
        return c

    def tx_or_404(s: Store, tx_id: str):
        t = s.get_transcript(tx_id) if TX_ID_RE.match(tx_id) else None
        if t is None:
            raise HTTPException(404, "No such transcript")
        return t

    def go(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def workspace(request, s, cid, name, **ctx):
        c = client_or_404(s, cid)
        reg = s.load_registry(cid)
        ctx.setdefault("options", wf.load_client_options(s, cid))
        first_hidden, last_hidden = wf.name_hidden(wf.client_settings(s, cid, wf.load_settings(s)))
        ctx.setdefault("first_hidden", first_hidden)
        ctx.setdefault("last_hidden", last_hidden)
        ctx.setdefault("type_labels", wf.TYPE_LABELS)
        ctx.setdefault("all_types", wf.ALL_TYPES)
        ctx.setdefault("options_error", None)
        ctx.update(client=c, full_name=wf.client_full_name(c["first_name"], reg), cid=cid,
                   transcripts=s.list_transcripts(cid))
        return render(request, name, **ctx)

    # ---- home and clients -------------------------------------------------------------------

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        with open_store() as s:
            rows = wf.client_rows(s)
        if rows:
            return go(f"/clients/{rows[0]['id']}")
        return render(request, "home.html", clients=[])

    @router.post("/clients")
    async def new_client(request: Request):
        form = await security.read_form(request)
        name = str(form.get("first_name", "")).strip()
        try:
            with open_store() as s:
                cid = s.create_client(name)
        except ValueError:
            return render(request, "home.html", error="Enter the client's first name.")
        log.info("client created %s", cid)
        return go(f"/clients/{cid}")

    def overview(request, s, cid, **extra):
        """The client's page. extra can carry a notice, an error or the selected call."""
        ctx = dict(tab="overview", summaries=[m for m in s.list_messages(cid) if m["kind"] == "summary"]
                   if CLIENT_ID_RE.match(cid) else [], summary_prompt=wf.SUMMARY_PROMPT, just_saved=None,
                   options=wf.load_client_options(s, cid), type_labels=wf.TYPE_LABELS, all_types=wf.ALL_TYPES,
                   options_error=None, sel=None, view="transcript", selector=None, output_choices=wf.OUTPUTS,
                   ticked=[], more_ticked=[], tags={}, title_typed=None, seen=False, blocks=[], total_versions=0, segs=[],
                   warning=None, hide_error=None, hide_typed=None, directions="", directions_ok=[], mcp_on=False, keep_params=[],
                   manage_open=False, summary_open=False, waiting_any=False)
        ctx.update(extra if "calls" in extra else client_context(request, s, cid, **extra))
        return workspace(request, s, cid, "client.html", **ctx)

    def call_rows(s: Store, cid: str, transcripts: list) -> list:
        """Each call with the state of the outputs in the fixed order: received (latest version), waiting or none,
        its title, and the one line the selector shows."""
        rows = []
        for t in transcripts:
            outs = []
            for slug, name in wf.OUTPUTS:
                n = len(s.list_outputs(t["id"], slug))
                outs.append(dict(slug=slug, name=name, short=wf.SHORT_NAMES[slug], version=n,
                                 state="received" if n else ("waiting" if slug in t["requested_outputs"] else "none")))
            got, waiting = sum(o["state"] == "received" for o in outs), sum(o["state"] == "waiting" for o in outs)
            state = (f"{got} of {got + waiting} outputs received" if got
                     else ("Copied, waiting for Claude" if waiting else wf.STATUS_LABELS.get(t["status"], t["status"])))
            title = t["title"]
            # The title leads, then the date and the state. The ID stays in the page (data-id) but is not read out.
            label = ", ".join((title or "Untitled", wf.long_day(t["call_date"]), state))
            rows.append(dict(t, outs=outs, got=got, waiting=waiting, title_shown=title, label=label, state=state))
        return rows

    def display_args(s, cid, full):
        reg = s.load_registry(cid)
        # Only the names that are replaced without asking come back as words in the box. A name that still needs a choice
        # at each place stays a code there, which scrubbing leaves alone.
        return reg, full["directions"], wf.local_scope(reg, full["scrubbed_text"], full["id"])[0]

    def pick_view(view, row) -> str:
        """Transcript while nothing has been requested or received, otherwise Outputs, unless the address says."""
        if view in VIEWS:
            return view
        return "outputs" if row["got"] or row["requested_outputs"] else "transcript"

    def hide_notice(places: int, outs: int) -> str:
        msg = f"Hidden in {places} place{'s' if places != 1 else ''} in the transcript"
        if outs:
            msg += f" and in {outs} output{'s' if outs != 1 else ''}, each saved as a new version with the text masked"
        return msg + ". There is no undo here."

    def client_context(request, s, cid, tx=None, view=None, saved=None, **extra):
        # (defined after overview, which calls it)
        """Everything the client page needs, with the call chosen by ?tx= (else the one just saved, else the newest)."""
        calls = call_rows(s, cid, s.list_transcripts(cid))
        if not calls:
            if tx:
                raise HTTPException(404, "No such transcript")
            return dict(extra, calls=[])
        wanted = tx or (saved if saved and TX_ID_RE.match(saved) else None)
        ix = 0
        if wanted:
            ix = next((i for i, c in enumerate(calls) if c["id"] == wanted), None)
            if ix is None:
                if tx:
                    raise HTTPException(404, "No such transcript")
                ix = 0
        sel = calls[ix]
        view = pick_view(view, sel)
        newer = calls[ix - 1] if ix > 0 else None
        older = calls[ix + 1] if ix + 1 < len(calls) else None
        selector = dict(
            options=[dict(id=c["id"], label=c["label"], selected=c["id"] == sel["id"]) for c in calls],
            position=ix + 1, total=len(calls),
            older=client_url(cid, older["id"]) if older else None, newer=client_url(cid, newer["id"]) if newer else None)
        blocks = output_blocks(s, sel, request.query_params, cid)
        full = s.get_transcript(sel["id"])
        ctx = dict(extra, calls=calls, sel=sel, view=view, selector=selector, blocks=blocks,
                   total_versions=sum(len(b["versions"]) for b in blocks), tx=full,
                   segs=wf.real_segments(s, cid, full["scrubbed_text"], sel["id"]), seen=wf.claude_has_seen(s, full),
                   output_choices=wf.OUTPUTS, ticked=wf.preticked_outputs(s, sel["requested_outputs"], full["planned_outputs"]),
                   directions=wf.directions_for_display(*display_args(s, cid, full)), directions_ok=full["directions_ok"], mcp_on=wf.load_settings(s).mcp_enabled,
                   keep_params=[(k, v) for k, v in request.query_params.items() if k in STATE_KEYS and KEEP_PARAM.match(v)],
                   waiting_any=any(b["waiting"] for b in blocks),
                   more_ticked=wf.more_ticked(blocks), tags={b["slug"]: "waiting" if b["waiting"] else "on this page" for b in blocks if b["on_page"]},
                   href_outputs=client_url(cid, sel["id"], "outputs"), href_transcript=client_url(cid, sel["id"], "transcript"),
                   href_after_copy=client_url(cid, sel["id"], "outputs"))
        return ctx

    @router.get("/clients/{cid}", response_class=HTMLResponse)
    async def client_page(request: Request, cid: str, tx: str | None = None, view: str | None = None,
                          saved: str | None = None, options: str | None = None, done: str | None = None,
                          edited: str | None = None, masked: str | None = None, hid: str | None = None,
                          hidout: str | None = None, titled: str | None = None, manage: str | None = None,
                          summary: str | None = None, gone: str | None = None):
        with open_store() as s:
            client_or_404(s, cid)
            if tx is not None and not TX_ID_RE.match(tx):
                raise HTTPException(404, "No such transcript")
            ctx = client_context(request, s, cid, tx, view, saved)
            t = s.get_transcript(saved) if saved and TX_ID_RE.match(saved) else None
            ctx["just_saved"] = t["id"] if t is not None and t["client_id"] == cid and not tx else None
            notice = warning = None
            if options == "saved":
                notice = "Options saved. Copy for Claude and the text shown below now follow them for every transcript of this client."
            elif done == "archived":
                notice = None          # the Archived bar at the top of the page already says it
            elif done in DONE_NOTICES:
                notice = DONE_NOTICES[done].format(name=client_or_404(s, cid)["first_name"], cid=cid)
            elif edited in wf.OUTPUT_NAMES:
                n = maybe_int(masked) or 0
                notice = f"Saved a new version of {wf.OUTPUT_NAMES[edited]}." + (
                    f" {n} real value{'s' if n != 1 else ''} typed in the text {'were' if n != 1 else 'was'} replaced "
                    "with hidden names." if n else "")
            elif hid is not None and maybe_int(hid) is not None and ctx.get("sel"):
                notice = hide_notice(maybe_int(hid), maybe_int(hidout) or 0)
                if ctx["seen"]:
                    warning = ("Claude already received this transcript, so text it holds cannot be changed. Text hidden "
                               "now protects new copies and new versions.")
            elif gone == "1":
                notice = "Transcript deleted."
            elif titled:
                notice = "Title saved." if titled == "1" else "Title removed."
            elif summary == "saved":
                notice = "Summary saved. It is listed under More, Running summary."
            return overview(request, s, cid, notice=notice, warning=warning, manage_open=manage == "1",
                            summary_open=summary == "saved", **ctx)

    @router.post("/clients/{cid}/archive")
    async def archive(cid: str):
        with open_store() as s:
            c = client_or_404(s, cid)
            s.set_archived(cid, not c["archived"])
        return go(f"/clients/{cid}?done={'restored' if c['archived'] else 'archived'}")

    @router.post("/clients/{cid}/export")
    async def export(cid: str):
        with open_store() as s:
            client_or_404(s, cid)
            body = wf.export_markdown(s, cid)
            s.audit("export", cid, None, len(body.encode("utf-8")))
        # Header values are Latin-1, and a client ID can hold any letters, so send an ASCII name plus the real one.
        ascii_name = cid.encode("ascii", "ignore").decode().strip("-") or "client"
        return Response(body, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition":
                                 f"attachment; filename=\"{ascii_name}.md\"; filename*=UTF-8''{quote(cid)}.md"})

    # ---- intake and review ------------------------------------------------------------------

    @router.get("/clients/{cid}/intake", response_class=HTMLResponse)
    async def intake_form(request: Request, cid: str):
        with open_store() as s:
            return workspace(request, s, cid, "intake.html", tab="intake", today=date.today().isoformat())

    def flag_body(groups) -> dict:
        """The open flags for the page: the words, and (only when there are any) the places that need a choice."""
        body = {"flags": [g.text for g in groups]}
        asks = wf.ask_list(groups)
        if asks:
            body["ask"] = asks
        return body

    def review_extras(s, form, dir_flags=(), dir_ask=()):
        """The checklist, directions and any flagged words in them for the review page. A first review starts from the
        last choice made anywhere in the app. A rescan or a failed save keeps what was typed."""
        if form is None:
            ticked, directions = wf.preticked_outputs(s, []), ""
        else:
            ticked = [o for o in form.getlist("output") if o in wf.OUTPUT_NAMES]
            directions = str(form.get("directions", ""))
        return dict(output_choices=wf.OUTPUTS, ticked=ticked, directions=directions, dir_flags=list(dir_flags), dir_ask=list(dir_ask),
                    dir_confirmed=set(form.getlist("dir_confirm")) if form is not None else set(),
                    dir_hidden=hide_words(form), dir_hidden_wide=hide_words(form, "dir_hide_client"),
                    dir_places=place_fields(form))

    def hide_words(form, field="dir_hide") -> list:
        """Words hidden with the Hide button in the review's directions box (for this transcript only, or for the client
        with the second field), kept across a rescan or a failed save."""
        seen = []
        for w in (form.getlist(field) if form is not None else []):
            w = " ".join(str(w).split())
            if w and len(w) <= wf.MAX_HIDE and w not in seen:
                seen.append(w)
        return seen

    def place_fields(form) -> list:
        """Choices for the typed places that need one, from fields "start|hide|word" or "start|send|word"."""
        out = []
        for v in (form.getlist("dir_place") if form is not None else []):
            start, _, rest = str(v).partition("|")
            choice, _, word = rest.partition("|")
            if start.isdigit() and choice in ("hide", "send") and word and len(word) <= wf.MAX_HIDE:
                out.append({"start": int(start), "word": word, "choice": choice})
        return out

    def begin_review(request, s, cid, text, day, notice=None):
        """Scrub the pasted text for this client and show the review page, or the paste form with the problem."""
        client_or_404(s, cid)
        settings = wf.load_settings(s)
        try:
            call_date = call_day(day)
        except ValueError:
            return workspace(request, s, cid, "intake.html", tab="intake", text=text, today=day,
                             error="Enter a valid call date, not in the future and not before 1990.")
        try:
            result = wf.run_intake(s, cid, text, app.state.ner, settings)
        except TranscriptFormatError as e:
            return workspace(request, s, cid, "intake.html", tab="intake", text=text, today=day,
                             issues=[f"Line {i.line}: {i.message}" if i.line else i.message for i in e.issues])
        except NerUnavailable as e:
            return workspace(request, s, cid, "intake.html", tab="intake", text=text, today=day, error=str(e))
        log.info("intake preview client=%s chars=%d flags=%d", cid, len(text), len(result.groups))
        return workspace(request, s, cid, "review.html", tab="intake", text=text, call_date=call_date.isoformat(),
                         result=result, carry_json="{}", notice=notice, title="", **review_extras(s, None))

    @router.post("/clients/{cid}/intake", response_class=HTMLResponse)
    async def intake_review(request: Request, cid: str):
        form = await security.read_form(request)
        with open_store() as s:
            return begin_review(request, s, cid, str(form.get("text", "")), str(form.get("call_date", "")))

    # A new transcript with no client chosen yet. The app reads the names, suggests who the client is, and
    # the user confirms or changes it before anything is created.

    @router.get("/intake", response_class=HTMLResponse)
    async def intake_new_form(request: Request):
        return render(request, "intake_new.html", today=date.today().isoformat())

    @router.post("/intake", response_class=HTMLResponse)
    async def intake_new(request: Request):
        form = await security.read_form(request)
        text, day = str(form.get("text", "")), str(form.get("call_date", ""))
        try:
            call_day(day)
        except ValueError:
            return render(request, "intake_new.html", text=text, today=day,
                          error="Enter a valid call date, not in the future and not before 1990.")
        with open_store() as s:
            try:
                found = wf.detect_client(s, text, app.state.ner, wf.load_settings(s))
            except TranscriptFormatError as e:
                return render(request, "intake_new.html", text=text, today=day,
                              issues=[f"Line {i.line}: {i.message}" if i.line else i.message for i in e.issues])
            except NerUnavailable as e:
                return render(request, "intake_new.html", text=text, today=day, error=str(e))
            # A pasted call starts a new client only when no existing client could be this person. A full name the
            # app knows, or the same first name as a client, stops here and asks, with the date of that client's last
            # call, because a second record would split the registry and give Claude new codes for the same person.
            # When nobody but the first speaker was found there is no name to use, so ask that too.
            if found.suggested and not found.matches:
                s.purge_pending(older_than_minutes=PENDING_KEEP_MINUTES)
                cid = s.create_client(found.suggested, pending=True)
                log.info("client created %s", cid)
                return begin_review(request, s, cid, text, day,
                                    notice=f"New client {found.suggested} created from this transcript. It is added to the "
                                           "sidebar when you save. Wrong name? After saving, open More, then "
                                           "Manage client, and use Rename.")
        return render(request, "choose_client.html", text=text, call_date=day, found=found)

    @router.post("/intake/start", response_class=HTMLResponse)
    async def intake_start(request: Request):
        form = await security.read_form(request)
        text, day = str(form.get("text", "")), str(form.get("call_date", ""))
        name = str(form.get("first_name", "")).strip()
        choice = str(form.get("client") or ("new" if name else ""))
        with open_store() as s:
            if not choice:
                try:
                    found = wf.detect_client(s, text, app.state.ner, wf.load_settings(s))
                except (ValueError, NerUnavailable) as e:      # includes TranscriptFormatError, e.g. an empty paste
                    issues = [f"Line {i.line}: {i.message}" if i.line else i.message for i in getattr(e, "issues", [])]
                    return render(request, "intake_new.html", text=text, today=day,
                                  **({"issues": issues} if issues else {"error": str(e)}))
                return render(request, "choose_client.html", text=text, call_date=day, found=found,
                              error="Choose a client above, or type a first name for a new client.")
            if choice != "new":
                picked = client_or_404(s, choice)
                if picked["archived"]:
                    s.set_archived(choice, False)      # adding a call to an archived client brings them back
                return begin_review(request, s, choice, text, day)
            try:
                found = wf.detect_client(s, text, app.state.ner, wf.load_settings(s)) if not name else None
                cid = s.create_client(name, pending=True) if name else None
            except (ValueError, NerUnavailable):      # includes TranscriptFormatError, e.g. an empty paste
                found, cid = None, None
            if cid is None:
                return render(request, "choose_client.html", text=text, call_date=day,
                              found=found or wf.Detection([], "", []),
                              error="Enter the client's first name, with letters.")
            log.info("client created %s", cid)
            return begin_review(request, s, cid, text, day)

    @router.post("/clients/{cid}/options")
    async def client_options(request: Request, cid: str):
        """Save the client's scrubbing options and come back to the page they were changed on."""
        form = await security.read_form(request)
        if form.get("parts"):
            # The page sends First names and Last names boxes. Names are on while either is ticked, and each box
            # decides whether that part of a name is hidden from Claude.
            types = {t for t in form.getlist("types") if t in wf.ALL_TYPES and t != "PERSON"}
            if form.get("first_hide") or form.get("last_hide"):
                types.add("PERSON")
            opts = wf.ClientOptions(frozenset(types), "scrub" if form.get("first_hide") else "keep",
                                    "scrub" if form.get("last_hide") else "keep")
        else:
            opts = wf.ClientOptions(frozenset(t for t in form.getlist("types") if t in wf.ALL_TYPES),
                                    str(form.get("first_names", "inherit")))
        tx = str(form.get("tx", ""))
        tx = tx if TX_ID_RE.match(tx) else None
        intake = form.get("back") == "intake"
        with open_store() as s:
            client_or_404(s, cid)
            try:
                wf.save_client_options(s, cid, opts)
            except ValueError as e:
                if intake:
                    return workspace(request, s, cid, "intake.html", tab="intake", today=date.today().isoformat(),
                                     options_error=str(e))
                return overview(request, s, cid, tx=tx, view="transcript", options_error=str(e))
        if intake:
            return go(f"/clients/{cid}/intake?options=saved")
        return go(client_url(cid, tx, "transcript", {"options": "saved"}))

    def delete_counts(s: Store, cid: str, tx_ids) -> dict:
        outs = sum(len(s.list_outputs(t, slug)) for t in tx_ids for slug in wf.OUTPUT_SLUGS)
        return dict(n_tx=len(tx_ids), n_versions=outs)

    @router.get("/clients/{cid}/delete", response_class=HTMLResponse)
    async def delete_client_page(request: Request, cid: str):
        """Asks first. Deleting is final, so the page says what goes and has one red button and a way back."""
        with open_store() as s:
            client_or_404(s, cid)
            ids = [t["id"] for t in s.list_transcripts(cid)]
            return workspace(request, s, cid, "confirm_delete.html", tab="", what="client", target=None,
                             **delete_counts(s, cid, ids))

    @router.post("/clients/{cid}/delete")
    async def delete_client(request: Request, cid: str):
        await security.read_form(request)
        with open_store() as s:
            client_or_404(s, cid)
            s.delete_client(cid)
        log.info("client deleted %s", cid)
        return go("/")

    @router.get("/transcripts/{tx_id}/delete", response_class=HTMLResponse)
    async def delete_transcript_page(request: Request, tx_id: str):
        with open_store() as s:
            tx = tx_or_404(s, tx_id)
            cid = tx["client_id"]
            label = call_rows(s, cid, [t for t in s.list_transcripts(cid) if t["id"] == tx_id])[0]["label"]
            return workspace(request, s, cid, "confirm_delete.html", tab="", what="transcript", target=dict(id=tx_id, label=label),
                             **delete_counts(s, cid, [tx_id]))

    @router.post("/transcripts/{tx_id}/delete")
    async def delete_transcript(request: Request, tx_id: str):
        await security.read_form(request)
        with open_store() as s:
            tx = tx_or_404(s, tx_id)
            cid = tx["client_id"]
            wf.delete_transcript(s, cid, tx_id)
        log.info("transcript deleted %s", tx_id)
        return go(client_url(cid, None, None, {"gone": "1"}))

    @router.post("/clients/{cid}/rename")
    async def rename_client(request: Request, cid: str):
        form = await security.read_form(request)
        with open_store() as s:
            client_or_404(s, cid)
            try:
                s.rename_client(cid, str(form.get("first_name", "")))
            except ValueError:
                return overview(request, s, cid, error="Enter a first name to rename the client.")
        return go(f"/clients/{cid}?done=renamed")

    def carried_decision(d):
        """One decision carried through a rescan, or None when it is not the shape this app writes."""
        if not isinstance(d, dict) or d.get("decision") not in ("scrub", "keep") or not isinstance(d.get("text"), str):
            return None
        spans = d.get("spans")
        if not isinstance(spans, list):
            spans = []
        spans = [(int(p[0]), int(p[1])) for p in spans
                 if isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(n, int) for n in p)]
        return {"text": d["text"], "decision": d["decision"], "spans": spans, **({"each": True} if d.get("each") else {})}

    def parse_review_form(form):
        """Decisions and extra values from the review form, plus what earlier rescans carried forward. A carry
        value that is not what this app wrote is ignored, and a damaged flag field is refused with a page."""
        try:
            carried = json.loads(str(form.get("carry") or "{}"))
        except ValueError:
            carried = {}
        if not isinstance(carried, dict):
            carried = {}
        decisions = [d for d in map(carried_decision, carried["decisions"] if isinstance(carried.get("decisions"), list)
                                    else []) if d]
        extras = [(x[0], x[1]) for x in (carried["extras"] if isinstance(carried.get("extras"), list) else [])
                  if isinstance(x, (list, tuple)) and len(x) == 2 and x[0] in ("PERSON", "EMAIL", "ADDRESS")
                  and isinstance(x[1], str)]
        n_flags = maybe_int(form.get("n_flags") or 0)
        if n_flags is None or not 0 <= n_flags <= 100_000:
            raise bad_form()
        for i in range(n_flags):
            decision = str(form.get(f"d{i}", ""))
            if decision in ("scrub", "keep", "each"):
                try:
                    spans = [tuple(map(int, p.split(":"))) for p in str(form.get(f"s{i}", "")).split(",") if p]
                except ValueError:
                    raise bad_form() from None
                if any(len(p) != 2 for p in spans):
                    raise bad_form()
                word = str(form.get(f"w{i}", ""))
                if decision == "each":       # one choice for each place: only the places that got one are decided
                    for j, span in enumerate(spans):
                        choice = str(form.get(f"p{i}_{j}", ""))
                        if choice in ("scrub", "keep"):
                            decisions.append({"text": word, "decision": choice, "spans": [span], "each": True})
                else:
                    decisions.append({"text": word, "decision": decision, "spans": spans})
        for type_, value in zip(form.getlist("extra_type"), form.getlist("extra_text")):
            if str(value).strip() and type_ in ("PERSON", "EMAIL", "ADDRESS"):
                extras.append((str(type_), str(value).strip()))
        return decisions, extras

    def carry_json(decisions, extras) -> str:
        return json.dumps({"decisions": decisions, "extras": extras})

    @router.post("/clients/{cid}/intake/rescan", response_class=HTMLResponse)
    async def intake_rescan(request: Request, cid: str):
        form = await security.read_form(request)
        text, day = str(form.get("text", "")), str(form.get("call_date", ""))
        decisions, extras = parse_review_form(form)
        with open_store() as s:
            client_or_404(s, cid)
            try:
                result = wf.run_intake(s, cid, text, app.state.ner, wf.load_settings(s), extras, (), decisions)
            except (ValueError, NerUnavailable) as e:
                return workspace(request, s, cid, "intake.html", tab="intake", text=text, today=day, error=str(e))
            return workspace(request, s, cid, "review.html", tab="intake", text=text, call_date=day, result=result,
                             carry_json=carry_json(decisions, extras), title=str(form.get("title", "")),
                             **review_extras(s, form))

    @router.post("/clients/{cid}/intake/directions-preview")
    async def intake_directions_preview(request: Request, cid: str):
        """Flagged words in the directions box on the review page, for the review as it stands: the choices made so far,
        including Choose each place, decide which names are hidden. The page posts its own form, so nothing about the
        pasted text is kept here. Stores nothing."""
        form = await security.read_form(request)
        decisions, extras = parse_review_form(form)
        with open_store() as s:
            client_or_404(s, cid)
            try:
                groups = wf.review_directions_groups(s, cid, str(form.get("text", "")), app.state.ner, wf.load_settings(s),
                                                     extras, decisions, str(form.get("directions", "")), hide_words(form),
                                                     hide_words(form, "dir_hide_client"), place_fields(form))
            except (ValueError, NerUnavailable, wf.ImportProblem) as e:    # includes TranscriptFormatError
                return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse(flag_body(groups))

    @router.post("/clients/{cid}/intake/save", response_class=HTMLResponse)
    async def intake_save(request: Request, cid: str):
        form = await security.read_form(request)
        text = str(form.get("text", ""))
        decisions, extras = parse_review_form(form)
        with open_store() as s:
            client_or_404(s, cid)
            settings = wf.load_settings(s)
            try:
                call_date = call_day(str(form.get("call_date", "")))
                tx = wf.save_transcript(s, cid, text, call_date, app.state.ner, settings, decisions, extras,
                                        str(form.get("title", "")), form.getlist("output"),
                                        str(form.get("directions", "")), form.getlist("dir_confirm"), hide_words(form),
                                        hide_words(form, "dir_hide_client"), place_fields(form))
            except (wf.ReviewIncomplete, wf.DirectionsFlagged) as e:   # stay on the review: this page holds the only copy
                result = wf.run_intake(s, cid, text, app.state.ner, settings, extras, (), decisions)
                flagged = isinstance(e, wf.DirectionsFlagged)
                return workspace(request, s, cid, "review.html", tab="intake", text=text,
                                 call_date=str(form.get("call_date", "")), result=result,
                                 carry_json=carry_json(decisions, extras), title=str(form.get("title", "")),
                                 error=("Not saved yet. Some capitalized words in the directions were left as they are. "
                                        "Tick each one to send it as written, hide it, or edit the directions." if flagged else
                                        f"Not saved yet. These words still need a decision: {e}."),
                                 **review_extras(s, form, e.words if flagged else (), wf.ask_list(e.groups) if flagged else ()))
            except wf.ImportProblem as e:
                return workspace(request, s, cid, "intake.html", tab="intake", text=text,
                                 today=str(form.get("call_date", "")), error=str(e))
            except (ValueError, NerUnavailable) as e:    # includes TranscriptFormatError
                return workspace(request, s, cid, "intake.html", tab="intake", text=text,
                                 today=str(form.get("call_date", "")), error=str(e))
            log.info("transcript saved %s %s", cid, tx)
        return go(f"/clients/{cid}?saved={tx}")

    # ---- transcript view, copy, outputs -----------------------------------------------------

    def output_blocks(s: Store, tx: dict, params, cid: str) -> list:
        """One block for each of the 7 outputs, in the app's order (the 3 text outputs make the board, the 4 forms sit
        under it as panels). The page shows only the blocks with `on_page`: a block that has a version or was asked for at
        the last copy. A block is received (has a version), waiting (asked for, no version yet) or none. Each block opens on its latest
        version. ?<output>=N shows an older one and ?cmp-<output>=M (or "prev") compares it, per output, so choosing
        in one column leaves the others as they are."""
        state = {}
        for slug in wf.OUTPUT_SLUGS:
            if (n := maybe_int(params.get(slug))) is not None:
                state[slug] = n
            cmp = params.get(f"cmp-{slug}")
            if cmp == "prev" or (n := maybe_int(cmp)) is not None:
                state[f"cmp-{slug}"] = "prev" if cmp == "prev" else n

        def href(slug: str, v: int | None = None, cmp=None) -> str:
            q = {k: n for k, n in state.items() if k not in (slug, f"cmp-{slug}")}
            if v is not None:
                q[slug] = v
            if cmp is not None:
                q[f"cmp-{slug}"] = cmp
            return client_url(cid, tx["id"], "outputs", q, f"#out-{slug}")

        blocks, registry = [], s.load_registry(cid)
        for slug, name in wf.OUTPUTS:
            versions = s.list_outputs(tx["id"], slug)
            block = dict(slug=slug, name=name, is_form=wf.is_form(slug), rows=[], answered=0, versions=versions, waiting=not versions and slug in tx["requested_outputs"],
                         on_page=bool(versions) or slug in tx["requested_outputs"],
                         current=None, raw="", shown=None, compare=None, diff=None, latest=None, plain_href=None,
                         version_options=[], compare_options=[], older_href=None, newer_href=None, back_href=None,
                         hidden=[], compare_value="", is_latest=True)
            if versions:
                current = next((o for o in versions if o["version"] == state.get(slug)), versions[-1])
                latest = versions[-1]["version"]
                at = versions.index(current)
                other = None
                cmp = state.get(f"cmp-{slug}")
                if cmp == "prev" and at > 0:
                    other = versions[at - 1]
                elif cmp not in (None, "prev"):
                    other = next((o for o in versions if o["version"] == cmp and o["version"] != current["version"]), None)
                block.update(
                    current=current, raw=wf.placeholder_text(s, cid, current["content"], registry),
                    shown=(wf.view_form if wf.is_form(slug) else wf.view_output)(s, tx["client_id"], *(
                        (slug,) if wf.is_form(slug) else ()), current["content"]), latest=latest,
                    plain_href=href(slug, v=current["version"]), is_latest=current is versions[-1],
                    version_options=[dict(value=o["version"], selected=o is current, label=", ".join((
                        f"v{o['version']}" + (" latest" if o["version"] == latest else ""), wf.short_day(o["created_at"]),
                        wf.SOURCE_WORDS.get(o["source"], o["source"])))) for o in reversed(versions)],
                    older_href=href(slug, versions[at - 1]["version"], state.get(f"cmp-{slug}")) if at > 0 else None,
                    newer_href=href(slug, versions[at + 1]["version"], state.get(f"cmp-{slug}")) if at + 1 < len(versions) else None,
                    back_href=href(slug) if current is not versions[-1] else None,
                    compare_options=[dict(value="", label="Off", selected=other is None)]
                    + ([dict(value="prev", label=f"Previous, v{versions[at - 1]['version']}",
                             selected=other is versions[at - 1])] if at > 0 else [])
                    + [dict(value=o["version"], label=f"v{o['version']}", selected=o is other)
                       for o in reversed(versions) if o is not current and not (at > 0 and o is versions[at - 1])],
                    hidden=[("tx", tx["id"]), ("view", "outputs")] + [(k, v) for k, v in state.items()
                                                                       if k not in (slug, f"cmp-{slug}")])
                if wf.is_form(slug):
                    rows = block["shown"][1]
                    block.update(rows=rows, counts=wf.form_counts(rows), entries=wf.form_items(rows),
                                 all_text=wf.clio_text(slug, rows, s.get_client(cid)["first_name"], str(tx["call_date"]),
                                                       current["version"]),
                                 all_raw=wf.forms_listing(rows, "raw"))
                if other and wf.is_form(slug):
                    block.update(compare=other, diff=wf.form_diff(
                        slug, wf.view_form(s, tx["client_id"], slug, other["content"])[0].text, block["shown"][0].text))
                elif other:
                    block.update(compare=other, diff=wf.diff_rows(wf.view_output(s, tx["client_id"], other["content"])[0].text,
                                                                   block["shown"][0].text))
            blocks.append(block)
        return blocks

    @router.get("/transcripts/{tx_id}")
    async def transcript_page(request: Request, tx_id: str):
        """The call page moved into the client page. Old links land on the right call, with every version and compare
        choice and the notices kept. A link that names an output state opens the Outputs view."""
        with open_store() as s:
            tx = tx_or_404(s, tx_id)
        keep = {k: v for k, v in request.query_params.items() if k in STATE_KEYS or k in ("view", "edited", "masked")}
        if "view" not in keep and any(k in STATE_KEYS for k in keep):
            keep["view"] = "outputs"
        return go(client_url(tx["client_id"], tx_id, extra=keep))

    @router.get("/transcripts/{tx_id}/latest")
    async def latest_version(tx_id: str):
        """Only a number, so the page can notice a version saved by the connector. It counts the versions of all
        the outputs, so a new one in any of them raises it."""
        with open_store() as s:
            tx_or_404(s, tx_id)
            total = sum(len(s.list_outputs(tx_id, slug)) for slug in wf.OUTPUT_SLUGS)
        return JSONResponse({"version": total})

    async def copy_choice(request) -> tuple:
        """The ticked output slugs, the optional directions and the confirmed flagged words, from JSON
        {"outputs": [...], "directions": "", "confirm": []} or from form fields named output and directions."""
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                data = await request.json()
            except ValueError:
                raise bad_form("The request body is not valid JSON.") from None
            if not isinstance(data, dict):
                data = {}
            picked, confirm = data.get("outputs"), data.get("confirm")
            return (picked if isinstance(picked, list) else [], str(data.get("directions") or ""),
                    [c for c in confirm if isinstance(c, str)] if isinstance(confirm, list) else [], data.get("places"))
        form = await security.read_form(request)
        return form.getlist("output"), str(form.get("directions") or ""), form.getlist("confirm"), None

    @router.post("/transcripts/{tx_id}/copy")
    async def copy_transcript(request: Request, tx_id: str):
        picked, directions, confirm, places = await copy_choice(request)
        with open_store() as s:
            tx = tx_or_404(s, tx_id)
            try:
                text = wf.copy_for_claude(s, tx["client_id"], tx_id, picked, directions, app.state.ner,
                                          wf.load_settings(s), confirm, places or ())
            except wf.ReviewIncomplete:
                raise HTTPException(409, "The review is not finished.")
            except wf.DirectionsFlagged as e:
                return JSONResponse({"error": "Some capitalized words in the directions were left as they are. Tick "
                                              "each one to send it as written, hide it, or edit the directions.",
                                     **flag_body([g for g in e.groups if g.text in e.words])}, status_code=409)
            except (wf.ImportProblem, NerUnavailable) as e:
                raise HTTPException(400, str(e))
        log.info("copied for claude %s outputs=%d bytes=%d", tx_id, len(picked), len(text))
        return JSONResponse({"text": text})

    @router.post("/transcripts/{tx_id}/outputs/{slug}/request-change")
    async def request_change(request: Request, tx_id: str, slug: str):
        """Copy text that asks Claude to change one output. The typed request is scrubbed first. Words the scrubber
        flags are listed, and the copy waits until each one is confirmed. Only the scrubbed text is stored."""
        data = await json_object(request)
        confirmed = data.get("confirm")
        confirmed = {c for c in confirmed if isinstance(c, str)} if isinstance(confirmed, list) else set()
        with open_store() as s:
            tx = tx_or_404(s, tx_id)
            try:
                out = wf.prepare_change_request(s, tx["client_id"], tx_id, slug, data.get("version"),
                                                str(data.get("text", "")), app.state.ner, wf.load_settings(s),
                                                data.get("latest"), data.get("places") or ())
            except wf.StaleVersion as e:
                return JSONResponse({"error": str(e), "stale": True}, status_code=409)
            except (wf.ImportProblem, NerUnavailable) as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            waiting = wf.open_groups(out.groups, confirmed)
            if waiting:
                return JSONResponse({"error": "Some capitalized words were left as they are. Tick each one to send it "
                                              "as written, hide it, or edit the text.", **flag_body(waiting)}, status_code=409)
            with s.transaction():
                copied = wf.commit_message(s, tx["client_id"], out, "correction", tx_id, output=slug)
        log.info("change requested %s %s bytes=%d", tx_id, slug, len(copied))
        return JSONResponse({"text": copied})

    async def json_object(request) -> dict:
        try:
            data = await request.json()
        except (ValueError, RuntimeError):      # a form body was already read by the CSRF guard
            raise bad_form("The request body is not valid JSON.") from None
        if not isinstance(data, dict):
            raise bad_form("The request body must be a JSON object.")
        return data

    @router.post("/transcripts/{tx_id}/scrub-preview")
    async def scrub_preview(request: Request, tx_id: str):
        """The capitalized words still flagged in text typed for Claude (a change request or directions), checked the
        way a copy checks them. A name already hidden for this client is replaced, never flagged. Stores nothing."""
        data = await json_object(request)
        with open_store() as s:
            tx = tx_or_404(s, tx_id)
            try:
                _, groups, _ = wf.prepare_directions(s, tx["client_id"], str(data.get("text", "")), app.state.ner,
                                                     wf.load_settings(s), tx_id)
            except (wf.ImportProblem, NerUnavailable) as e:
                return JSONResponse({"error": str(e)}, status_code=400)
        return JSONResponse(flag_body(groups))

    @router.post("/transcripts/{tx_id}/hide-word")
    async def hide_word(request: Request, tx_id: str):
        """Hide one flagged word in the text being sent. By default it is hidden for this transcript only: later text
        typed about this transcript recognises it, and nothing else ever matches it. With "client": true it joins the
        client's hidden names from now on. The transcript and the outputs are not changed and no version is made (that
        is what the Scrub this form is for). Returns the code the word is written as and the scope that was used."""
        data = await json_object(request)
        with open_store() as s:
            tx = tx_or_404(s, tx_id)
            try:
                done = wf.hide_for_request(s, tx["client_id"], str(data.get("text", "")), tx_id, data.get("client") is True)
            except (wf.ImportProblem, PlaceholderValue) as e:
                return JSONResponse({"error": str(e)}, status_code=400)
        log.info("word hidden from a request %s %s", tx_id, done["scope"])
        return JSONResponse(done)

    def editable(s: Store, tx_id: str, slug: str, v: str | None):
        """The transcript and the version shown in the editor. 404 unless the output has a version to start from."""
        tx = tx_or_404(s, tx_id)
        versions = s.list_outputs(tx_id, slug) if slug in wf.OUTPUT_NAMES else []
        if not versions:
            raise HTTPException(404, "No such output")
        return tx, next((o for o in versions if o["version"] == maybe_int(v)), versions[-1])

    def form_fields(s: Store, cid: str, slug: str, content: str, typed: dict | None = None) -> list:
        """The edit page's boxes for a form: [(number, question, text, hint, yesno)], the text with hidden names as stored."""
        if not wf.is_form(slug):
            return []
        shown = wf.forms.parse(slug, wf.placeholder_text(s, cid, content)).answers
        seen = wf.forms.visibility(slug, shown if typed is None else typed)
        def yes_no(n, text):         # a Yes or No box holds only Yes or No, so "Yes, two homes" is shown as Yes
            if wf.forms.DETAILS[slug][n - 1].kind != "yesno":
                return text
            got = wf.forms.choice(slug, n, text)
            if got:
                return got[0][0]
            # Not discussed is shown as itself, so saving the page never turns it into "no answer"
            return "Not discussed" if text.strip(" .").lower() == wf.forms.NOT_DISCUSSED else ""
        return [(n, q, typed[n] if typed is not None else yes_no(n, shown.get(n, "")),
                 " ".join(x for x in (wf.forms.hint(slug, n),
                                      f"Clio does not show this box now, {seen[n][2]}." if seen[n][0] == "closed" else "") if x),
                 wf.forms.DETAILS[slug][n - 1].kind == "yesno")
                for n, q in enumerate(wf.forms.QUESTIONS[slug], 1)]

    @router.get("/transcripts/{tx_id}/outputs/{slug}/edit", response_class=HTMLResponse)
    async def output_edit_page(request: Request, tx_id: str, slug: str, v: str | None = None):
        with open_store() as s:
            tx, base = editable(s, tx_id, slug, v)
            return workspace(request, s, tx["client_id"], "output_edit.html", tab="overview", tx=tx, slug=slug,
                             out_name=wf.OUTPUT_NAMES[slug], base=base,
                             text=wf.placeholder_text(s, tx["client_id"], base["content"]),
                             qrows=form_fields(s, tx["client_id"], slug, base["content"]),
                             back=client_url(tx["client_id"], tx_id, "outputs", anchor=f"#out-{slug}"))

    @router.post("/transcripts/{tx_id}/outputs/{slug}/edit", response_class=HTMLResponse)
    async def output_edit_save(request: Request, tx_id: str, slug: str, v: str | None = None):
        form = await security.read_form(request)
        with open_store() as s:
            tx, base = editable(s, tx_id, slug, v)
            text = str(form.get("content", ""))
            typed = None
            want = maybe_int(v)                 # the version the page started from; a newer one makes the save stale
            keep_first = wf.load_settings(s).keep_first_names
            if wf.is_form(slug):
                typed = {n: " | ".join(str(x) for x in form.getlist(f"answer_{n}")) for n in range(1, wf.forms.count(slug) + 1)}
                text = wf.forms.render(slug, typed)
            try:
                if typed is not None:
                    # Only the answers the person changed are saved. Every other one is copied from the latest
                    # version as stored, so an answer nobody touched is never rewritten.
                    shown = {n: t for n, _q, t, _h, _y in form_fields(s, tx["client_id"], slug, base["content"])}
                    changes = {n: t for n, t in typed.items() if not wf.same_answer(slug, n, t, shown[n])}
                    version, masked = wf.edit_answers(s, tx["client_id"], tx_id, slug, changes, keep_first, want)
                else:
                    version, masked = wf.edit_output(s, tx["client_id"], tx_id, slug, text, keep_first, want)
            except wf.ImportProblem as e:
                return workspace(request, s, tx["client_id"], "output_edit.html", tab="overview", tx=tx, slug=slug,
                                 out_name=wf.OUTPUT_NAMES[slug], base=base, text=text, error=str(e),
                                 qrows=form_fields(s, tx["client_id"], slug, base["content"], typed),
                                 back=client_url(tx["client_id"], tx_id, "outputs", anchor=f"#out-{slug}"))
        log.info("output edited %s %s v%d", tx_id, slug, version)
        return go(client_url(tx["client_id"], tx_id, "outputs", {"edited": slug, "masked": masked}, f"#out-{slug}"))

    @router.post("/transcripts/{tx_id}/outputs/{slug}/answers")
    async def save_answer(request: Request, tx_id: str, slug: str):
        """Save the edited answers of a form as one new version (JSON: changes {number: text}, version, or the older
        shape n and text for one answer). version is the one the page showed. If a newer one exists nothing is saved
        and the answer is 409 stale. Every other answer is copied as stored. The reply holds the Copy for Clio texts of
        the version just saved, so a copy right after a save needs no second request."""
        data = await json_object(request)
        base, changes = data.get("version"), data.get("changes")
        if changes is None and isinstance(data.get("n"), int) and not isinstance(data.get("n"), bool):
            changes = {data["n"]: data.get("text", "")}
        try:
            changes = {int(n): str(t) for n, t in changes.items()} if isinstance(changes, dict) and changes else None
        except ValueError:
            changes = None
        if not wf.is_form(slug) or not changes or not isinstance(base, int) or isinstance(base, bool):
            return JSONResponse({"error": "The request is not a form answer."}, status_code=400)
        with open_store() as s:
            tx = tx_or_404(s, tx_id)
            try:
                version, masked = wf.edit_answers(s, tx["client_id"], tx_id, slug, changes,
                                                  wf.load_settings(s).keep_first_names, base)
            except wf.StaleVersion as e:
                return JSONResponse({"error": str(e), "stale": True}, status_code=409)
            except wf.ImportProblem as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            saved = s.list_outputs(tx_id, slug)[-1]
            rows = wf.view_form(s, tx["client_id"], slug, saved["content"])[1]
        log.info("answers edited %s %s q%s v%d", tx_id, slug, ",".join(map(str, sorted(changes))), version)
        return JSONResponse({"ok": True, "version": version, "masked": masked,
                             "all": wf.clio_text(slug, rows, s.get_client(tx["client_id"])["first_name"], str(tx["call_date"]), version),
                             "allraw": wf.forms_listing(rows, "raw")})

    @router.post("/transcripts/{tx_id}/hide", response_class=HTMLResponse)
    async def hide_text(request: Request, tx_id: str):
        """Hide a word, email or address in a saved call: the value joins the client's hidden names, the transcript
        and any output that holds it are masked. The text comes from a form, so it works without a selection."""
        form = await security.read_form(request)
        typed = str(form.get("text", ""))
        view = str(form.get("view")) if form.get("view") in VIEWS else "transcript"
        with open_store() as s:
            tx = tx_or_404(s, tx_id)
            cid = tx["client_id"]
            try:
                result = wf.hide_in_transcript(s, cid, tx_id, str(form.get("type", "")), typed)
            except wf.ImportProblem as e:
                ctx = client_context(request, s, cid, tx_id, view)
                resp = overview(request, s, cid, hide_error=str(e), hide_typed=typed, **ctx)
                resp.status_code = 400
                return resp
        log.info("hidden in %s places=%d outputs=%d", tx_id, result.places, result.outputs)
        return go(client_url(cid, tx_id, view, {"hid": result.places, "hidout": result.outputs}))

    @router.post("/transcripts/{tx_id}/title", response_class=HTMLResponse)
    async def set_call_title(request: Request, tx_id: str):
        """Set or clear the optional call title. It is stored as typed, shown on screen only and never sent to Claude."""
        form = await security.read_form(request)
        typed = str(form.get("title", ""))
        view = str(form.get("view")) if form.get("view") in VIEWS else None
        kept = {k: str(form.get(k)) for k in STATE_KEYS if KEEP_PARAM.match(str(form.get(k) or ""))}
        with open_store() as s:
            tx = tx_or_404(s, tx_id)
            cid = tx["client_id"]
            try:
                stored = wf.set_title(s, cid, tx_id, typed)
            except wf.ImportProblem as e:
                ctx = client_context(request, s, cid, tx_id, view or "transcript")
                resp = overview(request, s, cid, title_typed=typed, error=str(e), **ctx)
                resp.status_code = 400
                return resp
        log.info("title set %s", tx_id)
        return go(client_url(cid, tx_id, view, {**kept, "titled": "1" if stored else "0"}))

    # ---- outgoing messages ------------------------------------------------------------------

    @router.get("/clients/{cid}/outgoing", response_class=HTMLResponse)
    async def outgoing_page(request: Request, cid: str):
        with open_store() as s:
            return workspace(request, s, cid, "outgoing.html", tab="outgoing")

    async def message_input(request):
        """text, kind, transcript ID and the raw fields of an outgoing message, from JSON or a form."""
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                data = await request.json()
            except ValueError:
                raise bad_form("The request body is not valid JSON.") from None
            if not isinstance(data, dict):
                raise bad_form("The request body must be a JSON object.")
        else:
            data = dict(await security.read_form(request))
        tx_id = data.get("tx_id")
        return str(data.get("text", "")), str(data.get("kind", "comment")), (str(tx_id) if tx_id else None), data

    @router.post("/clients/{cid}/outgoing/preview")
    async def outgoing_preview(request: Request, cid: str):
        text, kind, tx_id, data = await message_input(request)
        with open_store() as s:
            client_or_404(s, cid)
            try:
                out = wf.prepare_message(s, cid, text, kind, tx_id, app.state.ner, wf.load_settings(s), data.get("places") or ())
            except (wf.ImportProblem, NerUnavailable) as e:
                return JSONResponse({"error": str(e)})
        # The list of flagged places never shrinks as choices are made, or the page would lose them. Only the preview
        # text follows the choices.
        listed = wf.prepare_message(s, cid, text, kind, tx_id, app.state.ner, wf.load_settings(s)).groups \
            if data.get("places") else out.groups
        return JSONResponse({"segments": out.segments, **flag_body(listed)})

    @router.post("/clients/{cid}/outgoing/hide-word")
    async def outgoing_hide_word(request: Request, cid: str):
        """Hide one flagged word in a message. With a transcript chosen it is hidden for that transcript only unless
        "client": true. A message about no transcript can only hide it for the client, from now on."""
        data = await json_object(request)
        tx_id = str(data.get("tx_id") or "") or None
        with open_store() as s:
            client_or_404(s, cid)
            try:
                done = wf.hide_for_request(s, cid, str(data.get("text", "")), tx_id, data.get("client") is True)
            except (wf.ImportProblem, PlaceholderValue) as e:
                return JSONResponse({"error": str(e)}, status_code=400)
        log.info("word hidden from a message %s %s", cid, done["scope"])
        return JSONResponse(done)

    @router.post("/clients/{cid}/outgoing/copy")
    async def outgoing_copy(request: Request, cid: str):
        text, kind, tx_id, data = await message_input(request)
        with open_store() as s:
            client_or_404(s, cid)
            try:
                out = wf.prepare_message(s, cid, text, kind, tx_id, app.state.ner, wf.load_settings(s), data.get("places") or ())
            except (wf.ImportProblem, NerUnavailable) as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            # "confirm" settles capitalized words sent as written. It never settles a place that needs a choice.
            waiting = [g for g in out.groups if wf.is_ask(g) or not data.get("confirm")]
            if waiting:
                return JSONResponse({"error": "Flagged words need a look first.", **flag_body(waiting)}, status_code=409)
            copied = wf.commit_message(s, cid, out, kind, tx_id)
        log.info("message copied client=%s kind=%s bytes=%d", cid, kind, len(copied))
        return JSONResponse({"text": copied})

    # ---- import -----------------------------------------------------------------------------

    @router.get("/clients/{cid}/import", response_class=HTMLResponse)
    async def import_page(request: Request, cid: str, kind: str | None = None, tx: str | None = None):
        """kind=summary opens the page with Running summary chosen. tx= picks the call the reply is for, and the
        output of that call's latest change request is offered."""
        with open_store() as s:
            client_or_404(s, cid)
            tx_id = tx if tx and TX_ID_RE.match(tx) and (s.get_transcript(tx) or {}).get("client_id") == cid else None
            return workspace(request, s, cid, "import.html", tab="import", output_choices=wf.OUTPUTS,
                             kind="summary" if kind == "summary" else "output", pick_tx=tx_id,
                             suggested_output=wf.last_change_output(s, cid, tx_id) if tx_id else None)

    @router.post("/clients/{cid}/import", response_class=HTMLResponse)
    async def import_check(request: Request, cid: str):
        form = await security.read_form(request)
        text, tx_id = str(form.get("text", "")), str(form.get("tx_id") or "") or None
        output = str(form.get("output") or "") or None
        with open_store() as s:
            client_or_404(s, cid)
            try:
                check = wf.check_import(s, cid, text, tx_id, wf.load_settings(s).keep_first_names, output)
            except wf.ImportProblem as e:
                return workspace(request, s, cid, "import.html", tab="import", text=text, error=str(e),
                                 output_choices=wf.OUTPUTS, kind="summary" if form.get("kind") == "summary" else "output",
                                 pick_tx=tx_id, suggested_output=None)
            # A reply with no [OUTPUT: ...] lines is most likely the answer to the latest change request.
            return workspace(request, s, cid, "import_check.html", tab="import", text=text, check=check,
                             kind=str(form.get("kind", "output")), output_choices=wf.OUTPUTS, chosen_output=output,
                             suggested_output=wf.last_change_output(s, cid, check.tx_id) if check.tx_id else None)

    @router.post("/clients/{cid}/import/save")
    async def import_save(request: Request, cid: str):
        form = await security.read_form(request)
        with open_store() as s:
            client_or_404(s, cid)
            kind = "summary" if form.get("kind") == "summary" else "output"
            try:
                check = wf.check_import(s, cid, str(form.get("content", "")), str(form.get("tx_id") or "") or None,
                                        wf.load_settings(s).keep_first_names, str(form.get("output") or "") or None)
                result = wf.save_import(s, cid, check, kind)
            except wf.ImportProblem as e:
                return workspace(request, s, cid, "import.html", tab="import", error=str(e), output_choices=wf.OUTPUTS,
                                 kind=kind, pick_tx=None, suggested_output=None)
            log.info("import saved client=%s tx=%s %s", cid, check.tx_id, result)
            return go(client_url(cid, check.tx_id, "outputs") if kind == "output" else f"/clients/{cid}?summary=saved")

    # ---- registry editor --------------------------------------------------------------------

    @router.get("/clients/{cid}/registry", response_class=HTMLResponse)
    async def registry_page(request: Request, cid: str, error: str | None = None):
        with open_store() as s:
            client_or_404(s, cid)
            return workspace(request, s, cid, "registry.html", tab="registry", notice=app.state.flash.pop(request.state.sid, None),
                             rows=wf.registry_rows(s.load_registry(cid), s.list_transcripts(cid)), error=error)

    @router.post("/clients/{cid}/registry/{action}")
    async def registry_edit(request: Request, cid: str, action: str):
        form = await security.read_form(request)
        with open_store() as s:
            client_or_404(s, cid)
            reg = s.load_registry(cid)
            try:
                if action == "add":
                    if form.get("type") not in ("PERSON", "EMAIL", "ADDRESS") or not str(form.get("value", "")).strip():
                        raise ValueError("Choose a type and enter a value.")
                    reg.add_value(str(form["type"]), wf.clean_text(str(form["value"]).strip()))
                else:
                    ent = wf.find_entity(reg, str(form.get("type")), int(form.get("n") or 0))
                    if action == "save":           # every form of one hidden name, with one Save
                        wf.save_entity_forms(reg, ent, {p: form.get(f"value_{p}") for p in ("full", "first", "last", "nick")
                                                        if form.get(f"value_{p}") is not None},
                                             bool(form.get("office")) if ent.type == "PERSON" else None)
                    elif action == "edit":
                        part = {"full": None}.get(str(form.get("part")), str(form.get("part")))
                        if part not in ent.forms:         # only a form the entry already has, never a new made-up one
                            raise ValueError("That entry has no such form.")
                        reg.set_form(ent, part, wf.clean_text(str(form.get("value", ""))))
                    elif action == "merge":
                        reg.merge(wf.find_entity(reg, ent.type, int(form.get("into") or 0)), ent)
                    elif action == "delete":
                        deleted = (ent.forms.get(None) or "").strip()
                        wf.delete_hidden_name(s, cid, ent.type, ent.n)
                        reg = s.load_registry(cid)
                    else:
                        raise HTTPException(404)
                if action != "delete":
                    s.save_registry(cid, reg)
                    s.audit(f"registry_{action}", cid)
                if action == "delete":
                    # The notice waits here, in memory, for the page the redirect opens. A real name must never be put
                    # in an address, where logs and history keep it.
                    app.state.flash[request.state.sid] = f"Unscrubbed {deleted}"
            except (ValueError, wf.ImportProblem) as e:
                return workspace(request, s, cid, "registry.html", tab="registry", rows=wf.registry_rows(reg, s.list_transcripts(cid)), error=str(e))
        return go(f"/clients/{cid}/registry")

    # ---- settings ---------------------------------------------------------------------------

    def wants_json(request: Request) -> bool:
        return "application/json" in request.headers.get("accept", "")

    def settings_view(request, s, **extra):
        ner_model = app.state.ner
        ctx = dict(settings=wf.load_settings(s), ner=ner_model, saved=False, error=None, saved_section=None,
                   model_dir=str(ner_model.config.model_dir), mcp_command=MCP_COMMAND,
                   project_on=wf.project_instructions(True), project_off=wf.project_instructions(False))
        ctx.update(extra)
        return render(request, "settings.html", **ctx)

    def settings_done(request: Request, section: str, error: str | None = None, **extra):
        """Saved in place when the page asked for JSON, else back to the page with the result shown."""
        if wants_json(request):
            return JSONResponse({"error": error} if error else {"ok": True}, status_code=400 if error else 200)
        if error is None:
            return go(f"/settings?saved={section}")
        with open_store() as s:
            return settings_view(request, s, error=error, **extra)

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request, saved: str = ""):
        with open_store() as s:
            return settings_view(request, s, saved_section=saved if saved in ("model", "connector") else ("all" if saved == "1" else None))

    @router.post("/settings")
    async def settings_save(request: Request):
        """One section at a time: section=model saves the name finder settings, section=connector the connector switch.
        Without a section every field is read, as before."""
        form = await security.read_form(request)
        section = str(form.get("section", ""))
        try:
            with open_store() as s:
                cur = wf.load_settings(s)
                new = wf.Settings(
                    threshold=float(form.get("threshold", cur.threshold)) if section != "connector" else cur.threshold,
                    idle_minutes=int(form.get("idle_minutes", cur.idle_minutes)) if section != "connector" else cur.idle_minutes,
                    keep_first_names=False,
                    mcp_enabled=bool(form.get("mcp_enabled")) if section != "model" else cur.mcp_enabled)
                wf.save_settings(s, new)
        except ValueError as e:
            return settings_done(request, section or "model", str(e))
        return settings_done(request, section or "model")


    app.include_router(router)
    app.state.api_router = router            # tests walk it to check every POST route
    return app
