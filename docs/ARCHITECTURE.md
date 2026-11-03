# Matter Workbench, full documentation for the next agent

Read this first, then `CLAUDE.md` (rules and per-round notes), then `README.md` (user-facing guide). `docs/FUNCTIONS.md` lists every Python function, method and class with its line number (regenerate it if you add many).

Last updated 4 Nov 2026. 721 tests pass (`.venv/bin/python -m pytest -q`, about 2 minutes).

## 1. What this is and who uses it

A local web app for one paralegal at a law office. She pastes a client call transcript. The app removes names, emails and street addresses and swaps each for a code such as `[PERSON_1]`. She copies the scrubbed text into a claude.ai Project chat. Claude writes three outputs (Clio Note, Overview for Jordan's calendar notes, Clio form note) using the codes. She pastes Claude's reply back, and the app puts the real values back so she can copy the outputs into Clio.

The one promise the app makes is that a real name, email or address never reaches Claude. "A miss is a leak" is the guiding rule. Over-scrubbing only costs readability.

The user is not technical. She uses macOS or Windows. Keep every screen plain, and keep every action explicit. The owner of the project (the user in this repo) asks to approve a plan before any change that touches more than three files, and wants short replies that end with a line starting "Next action:". See `~/.claude/CLAUDE.md` for the owner's writing style rules (no em dashes, no mid-sentence colons, no bold labels in lists).

## 2. How to run it

macOS or Linux:
```bash
cd matter-workbench
.venv/bin/python -m app            # http://127.0.0.1:8765, opens the browser
.venv/bin/python -m pytest -q      # about 2 minutes
```
Windows PowerShell:
```powershell
cd matter-workbench
.venv\Scripts\python -m app
.venv\Scripts\python -m pytest -q
```
`python3 run.py` (macOS) or `py run.py` (Windows) is the entry point for end users. It builds `.venv` on first run, installs the libraries, checks the model against `CHECKSUMS.txt`, starts the app and opens the browser. `python -m app --demo` loads synthetic data (not available from the zip). There is no `--no-browser` flag.

Data folder: `~/Library/Application Support/MatterWorkbench.noindex` on macOS, `%LOCALAPPDATA%\MatterWorkbench` on Windows. `MATTER_WORKBENCH_HOME` overrides it. `app/paths.py` refuses a folder inside OneDrive, iCloud Drive, Dropbox, a macOS CloudStorage folder or a Git repository. To start from zero, stop the app, empty `clients/` and `audit.jsonl`, and keep `settings.json` (it holds the form secret).

Never run `scripts/seed_test_cases.py` against the real data folder unless the owner asks. Use `--data-dir` or `MATTER_WORKBENCH_HOME` with a folder ending in `.noindex`.

## 3. Directory map

| Path | What it is |
|---|---|
| `app/__main__.py` | Starts uvicorn, opens the browser, picks the data folder. |
| `app/web/app.py` | All FastAPI routes (`create_app`). Thin: parse the request, call `workflow`, render a template. |
| `app/web/security.py` | Host check, session cookie, CSRF token, security headers, body cap. |
| `app/web/templates/*.html` | Jinja2 templates. No inline script or style, no `|safe`, no inline handlers. |
| `app/web/static/app.js`, `style.css`, `theme.js`, `icon.svg` | All browser code and styling. No remote assets. |
| `app/workflow.py` | The business logic, with no web code. About 120 functions. Almost every feature lives here. |
| `app/store.py` | File storage, locking, transactions, delete, audit log. |
| `app/scrub/` | The scrubber. `parse.py`, `regex_rules.py`, `ner.py` (GLiNER via ONNX), `pipeline.py`, `registry.py`, `spans.py`, `evaluate.py`. |
| `app/rehydrate.py` | Turns codes in text back into real values, and warns about unknown codes and plain real values. |
| `app/outputs.py` | The three outputs, defined once (slug, name, default instructions, `[OUTPUT: slug]` parser). |
| `app/ids.py` | Client and transcript ID formats, the header line `[CLIENT: id | TX: id]`. |
| `app/paths.py` | Data folder choice and safety checks. |
| `app/check.py` | `python -m app.check [--fix]`, a report of stored files with no stored values in it. |
| `app/demo.py` | The `--demo` data. |
| `mcp_server/server.py` | Optional MCP connector with one write-only tool, `save_output`. |
| `run.py` | Stdlib-only installer and launcher for end users. |
| `scripts/` | `package.py` (zip builder), `seed_test_cases.py`, `eval_scrub.py`, `export_onnx.py`, `check_onnx_parity.py`. |
| `tests/` | pytest. `webhelp.py` has `Session` and `make_app` (fake NER). Fixtures in `tests/fixtures` are synthetic only. |
| `models/gliner_pii` | The ONNX name model (about 570 MB, gitignored). Tests that need it skip when it is missing. |
| `samples/` | Synthetic transcripts for trying the UI (`sample_call.txt`, `review_may.txt`, `long_call.txt`). |
| `docs/` | This file and `FUNCTIONS.md`. |
| `README.md`, `CLAUDE.md` | User guide, and agent rules with per-round notes. Both stay at the project root. |
| `docs/history/PLAN.md`, `docs/history/UI-PLAN.md` | History only. The storage plan and the UI plan with update notes per round, kept for the reasons behind earlier choices. Superseded by this file where they disagree. |

## 4. Data model on disk

All plain files, no database, no encryption (the owner decided that). Every real value is in plain text in `client.json`, so never read a real `client.json` and never send one to Claude. Use `python -m app.check` instead.

```
<data folder>/
  .lock                       global write lock
  settings.json               {schema, settings:{...}, form_secret}
  audit.jsonl                 one JSON line per action: time, action, client_id, transcript_id, byte count. Never content.
  clients/<client id>/
    client.json               the client, its registry (real values), transcript metadata, messages, review decisions
    transcripts/<tx id>/
      transcript.txt          the scrubbed text (codes, no real values at first save)
      clio-note.json          one file per output, append-only list of versions
      jordan-calendar-overview.json
      clio-form-note.json
```

IDs. A client ID is the first name plus the creation date plus a counter, such as `Maria-20261102-1`. Renaming a client changes the display name and never the ID. The ID goes to Claude in the header line of every copy, which is a known leak of the client's first name (see section 13). A transcript ID is `TX-<call date>-<n>`.

Settings in `settings.json` (keys): `threshold`, `idle_minutes`, `mcp_enabled`, `last_outputs`, `instructions.<slug>` (editable output instructions), and per-client options `client.<id>.types`, `client.<id>.first_names`, `client.<id>.last_names`. The old global `keep_first_names` is no longer settable. `load_settings` ignores any stored value.

Output versions have a `source`: `import` (pasted), `mcp` (connector), `edit` (hand edit), `hide` (a name was scrubbed after the fact, label "Name hidden"), `unhide` (a name was unscrubbed, label "Name restored"). Versions are never rewritten. A change adds a version.

Save order, which makes a crash safe. New transcript files first, then one atomic rename of `client.json` (that is the save), then replaced text and output files. All writes go through `Store.transaction` under the global lock. One transaction changes one client. Deleting a client or transcript removes the folder after the `client.json` commit, by renaming it to a `.trash-` name and removing it (`_remove_folder`). `Store.clean_up()` removes leftovers.

Pending clients. A new client from New transcript is created as `pending` and is added to the sidebar only when the transcript is saved. `purge_pending` removes stale ones.

## 5. Placeholders (the code grammar)

`PLACEHOLDER_RE` in `app/scrub/registry.py`. Forms, all inside square brackets:
`[PERSON_1]` full name, `[PERSON_1.first]`, `[PERSON_1.last]`, `[PERSON_1.nick]`, `[PERSON_1.rest]` (everything after the first word, worked out from the full name), `[EMAIL_1]`, `[ADDRESS_1]`.

A code is never a name. Registry writes refuse a value that is or holds a code (`PlaceholderValue`). `has_token` and `token_spans` find codes. `mask_known_values` and `_scrub` ignore anything overlapping a code. Numbers are never reused: `Registry.high` records the highest number ever issued per type, so an old chat message cannot resolve to a new person.

`Registry` (in `app/scrub/registry.py`) holds `Entity` objects. Fields to know: `forms` (part to real text), `aliases`, `surname_only` (a lone name after a title), `merged_into`, `local` (hidden for one transcript only, never matched in new text), `office` (office staff), `only` (transcripts a local entity was hidden for from a typed box), `via` (the transcript that added it). `Registry.surface(ent, part)` resolves `rest` and falls back for `first` when only a full name is stored.

## 6. The scrubber

`scrub_transcript(text, registry, config, ner)` in `app/scrub/pipeline.py`. Stages: lenient parse (`parse_lenient` reads `Name: text` and bullet speaker lines, marks role labels as `generic`, otherwise scrubs the whole text), speaker harvest, regex and cue rules (`regex_rules.py`, one `Rule` per entity type, includes spoken emails and spelled-out numbers), the GLiNER model, registry propagation across the whole text (`_propagation`), span merge (longest span wins, priority in `SOURCE_PRIORITY`), replacement, then review flags for capitalised words the model was unsure about. The NER model is lazy-loaded and freed after idle minutes (`NerModel.start_reaper`). When the model is missing, scrubbing is blocked and Settings shows the status.

Flags are groups of words with places. The review page lets the user Scrub or Keep each word, or choose per place ("Choose each place"). `ScrubConfig` carries `keep_first_names`, `types`, `require_ner`. `ALLOW_CAPS` and `REQUEST_WORDS` list plain words that are not flagged. A flag must cover a whole word or a Scrub decision can never clear it. `tests/test_real_model_save.py` must stay green because other web tests use `tests/fake_ner.py`.

The scrub at first save only applies the first-name keep. Everything else about the name options (last name, split names, types switched off) is applied later, at copy, view and import time (section 8).

## 7. Request flow, screen by screen

Routes live in `app/web/app.py`. Every POST goes through the CSRF guard and `security.read_form`. Form errors render `error.html`, JSON scripts keep JSON errors.

Intake.
1. `GET /intake` or `GET /clients/{cid}/intake`: paste text, set call date (not in the future, not before 1990).
2. `POST /intake` (no client chosen): `wf.detect_client` scrubs against an empty registry and guesses the client (the first speaker is office staff). If a person matches an existing client, by full name or by the same first name, it renders `choose_client.html` with the matching client's last call date and an "Add to this client" button per match, plus "Start a new client". If nothing matches and a name was found, it creates a pending client and goes straight to review. If no name was found, it asks for a first name.
3. `POST /intake/start`: the choose-page buttons post `client=<id>` or `client=new` with `first_name`.
4. `POST /clients/{cid}/intake` renders the review page (`review.html`): original (never stored) beside scrubbed text, flag list with Scrub all or Keep all, Choose each place, Something else to scrub, title, outputs checklist, directions.
5. `POST /clients/{cid}/intake/rescan`, `.../directions-preview` (live flag check of the directions), `.../intake/save` (saves, status `reviewed`). Saving the same call twice (same client, date, scrubbed text) returns the existing transcript.

Client page. `GET /clients/{cid}` is the single working page. `?tx=` picks a transcript (newest by default, 404 if unknown). `?view=outputs|transcript` (default: Transcript until something is requested or received). Per-output version params `<slug>=<n>` and `cmp-<slug>=<n>` are kept. `GET /transcripts/{id}` redirects here. Templates: `client.html`, `_workspace.html` (header, selector, delete link), `_transcript_view.html`, `_outputs_view.html`, `_options_row.html`, `_hide_form.html` (the Scrub this form), `_macros.html` (`copy_box`, `csrf_field`, `segs`).

Transcript view. Shows real values with scrubbed ones highlighted (`wf.real_segments`). Under it the options row, the output checklist, directions, Copy for Claude, then Scrub this. `POST /transcripts/{id}/copy` (JSON) calls `wf.copy_for_claude`. `POST /transcripts/{id}/hide` (form) calls `wf.hide_in_transcript`. After a copy the page goes to Outputs.

Outputs view. Three columns always. Per column: version arrows and drop-down, Compare, Copy (real names), Copy with hidden names, Edit, Ask Claude to change this (`POST /transcripts/{id}/outputs/{slug}/request-change`), Ask Claude for this (empty column). Under the board are the paste box (`POST /clients/{cid}/import`, then `/import/save`) and the always-open "Request more outputs" section. The board polls `GET /transcripts/{id}/latest` for new versions. `POST /transcripts/{id}/scrub-preview` and `.../hide-word` serve the typed boxes (live flag lists with a Hide button).

Other routes. `POST /clients/{cid}/options` (scrubbing options, autosaved), `/rename`, `/archive`, `/export` (Markdown history with real names), `GET|POST /clients/{cid}/delete` and `/transcripts/{id}/delete` (confirm pages with counts), `GET /clients/{cid}/outgoing` plus `/preview`, `/hide-word`, `/copy` (Message to Claude), `GET|POST /clients/{cid}/import` (standalone import for outputs or a summary), `GET /clients/{cid}/registry` and `POST /clients/{cid}/registry/{add|save|edit|merge|delete}` (the Hidden names page; the button reads "Unscrub"), `GET /settings`, `POST /settings`, `POST /settings/outputs`. `POST /clients` still exists (tests use it to create clients) but the UI no longer has a form for it.

## 8. Scrubbing options and how a copy is built

Per client, stored as settings. Types ticked: PERSON, EMAIL, ADDRESS. First names and Last names are two separate ticks (`first_names`: inherit, scrub, keep; `last_names`: scrub, keep). In the page the row shows Names, First names, Last names, Email addresses, Street addresses. Names is derived: ticked only while both First and Last are, setting both when ticked, and unticking either unticks it. Both unticked means PERSON is removed from `types`.

The first name is the first word of a name, the last name is everything after it. There is no middle-name detection. `person_pieces(ent, part, hide_first, hide_last)` splits a code into pieces: "Maria Elena Lopez" with First names unticked leaves as `Maria [PERSON_1.rest]`, with Last names unticked as `[PERSON_1.first] Elena Lopez`. One-word names count as a first name unless `surname_only` or the entity has a `first` form (`lone_name_is_first`).

`copy_for_claude(store, client_id, tx_id, outputs, directions, ...)`:
1. Refuses until the review is done (status not `draft`) and when no output is ticked.
2. Scrubs the directions like a change request. Flagged words raise `DirectionsFlagged` (HTTP 409) until each is confirmed.
3. `hide_known_now` masks any real value the registry knows now that the saved text still holds (a name hidden after the call was saved). If it changed anything it saves the masked text back and writes an audit line. A word kept at review (`Store.decided_keep`) stays as written, and so does the client's own first name.
4. `restore_switched_off` puts real values back for types switched off and for name parts the options leave visible.
5. The message stored in `client.json` keeps the hidden form. Only the clipboard text has the restored values.
6. Order of the copied text: intro (`copy_intro`), ticked outputs and their instructions, directions, header line `[CLIENT: id | TX: id]`, transcript.

`prepare_change_request` does the same for a change box: intro, the output's instructions, header, scrubbed change request, the chosen version with codes, the transcript. A stale version is refused. `prepare_message` does it for the Message page. Typed boxes (change, directions, message) always hide last names.

`copy_intro` and `change_intro` mention the `save_output` tool only when the connector is on in Settings.

## 9. Import and rehydration

`check_import(store, client_id, text, tx_id, keep_first_names, output)` reads the pasted reply, finds the header line to learn the client and transcript (if there is none it uses the transcript open on screen), splits `[OUTPUT: slug]` sections, masks any real value the registry knows (`mask_known_values`), rehydrates a preview (`rehydrate`), and lists replaced words, unknown codes and plain real values. Nothing is saved until the user confirms (`POST /clients/{cid}/import/save`, one transaction, one new version per output). Output files only accept slugs from `app/outputs.py`. Any text leaving as codes goes through `wf.placeholder_text`, which masks known values again for every version.

`rehydrate` flags `unknown` codes (not in the registry, so Claude may have invented them) and `possible_real` (a real value in plain text in the reply).

## 10. Hide, unhide and delete

Scrub this (`hide_in_transcript`): one transaction. Adds the value to the registry, replaces whole-word matches in the transcript, and adds a new `hide` version of each output that holds it. Refuses overlap with a code, empty text and text over `MAX_HIDE`. There is no undo.

Unscrub (`delete_hidden_name` in `workflow.py`, the Hidden names Delete route): one transaction. Puts the real words back in every saved transcript of the client and adds an `unhide` version to each output that held the code, then removes the entry. From the next copy that name goes to Claude as written. Chat text already copied with the code shows as unknown.

Delete transcript (`wf.delete_transcript`) removes the transcript, its outputs and its messages, and removes names hidden for that transcript only unless another call uses them. Client-wide names stay. Delete client removes the whole folder. Both have confirm pages with counts and write an audit line with IDs only.

Registry edits happen on the Hidden names page (`registry.html`). Merge keeps one entity and aliases the other. Entities marked office are ignored when matching clients.

## 11. Browser side (`app/web/static/app.js`)

No frameworks. Notable behaviours, all with tests that read the file:
- Scroll position is saved on submit (`sessionStorage`, key `mwb-scroll`) and restored.
- Copy buttons (`data-copy-text`, `data-copy-url`) use the clipboard API and a fallback. Copy for Claude stays disabled until an output is ticked and every flagged word in the directions is settled.
- The selection popup (`.hidepop`) appears over text inside `[data-hide-source]` (the Transcript view only) and fills the Scrub this form. It ignores selections that touch an already highlighted code.
- Typed text. `textarea[data-keep]` boxes (paste reply, directions, change box) count as typed text (`hasTyped()`). The paste and directions boxes are saved in `sessionStorage` under `mwb-typed:<path+query>#<id>` as the user types, restored on load, and cleared on submit or a successful copy. The change box has its own keeping through `data-store-key`. A `beforeunload` warning covers any exit while text is unsent, and is skipped for an intended form submit or after the app's own confirm. Polling reloads and the after-copy redirect are skipped while text is typed.
- The options row autosaves on change (`form[data-autosave]`) and keeps Names, First names and Last names in sync.
- Settings: the connector checkbox saves on change and swaps the "Instructions to save in Claude" text.
- Theme: `theme.js` applies the saved light or dark choice before paint, the top bar button flips it.
- CSP is strict (`default-src 'self'`, no inline script or style). Tests enforce no inline script, no remote assets.

## 12. The MCP connector

`python -m mcp_server` speaks MCP over stdio (JSON lines). One tool, `save_output(client_id, transcript_id, output, content)`. Write-only. It uses the same code as the Import box, so known real values are masked before saving, and its replies never include stored data. Verified end to end with a real subprocess (`scratchpad/mcp_e2e.py` in an earlier session). It is NOT registered in Claude Desktop. Registering means adding an `mcpServers` entry to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS), and the owner has not asked for that yet. Do not edit their Claude config without their word. Until then the user pastes replies into the Paste Claude's reply box.

## 13. Known limits and open items

Open decisions and known gaps, roughly by importance.
1. The client's first name goes to Claude in every copy, because the client ID (first name plus date) is in the header line whatever the First names option says. Planned fix: opaque IDs such as `C-20261102-1` plus a migration for existing clients. The owner has not approved it yet. Decide it before more chats start, because Claude chats keep the ID they were given.
2. No backup, no undo. Deletes are immediate. Idea: automatic snapshot before each delete and once a day, a "Back up now" button, show the data path in Settings.
3. No merge for two clients that are the same person.
4. A reply pasted with no header line is filed under the transcript open on screen, with only a soft notice. Idea: require an explicit pick.
5. Typed boxes (change request, directions, message) always hide last names, whatever the options say.
6. A lone one-word name with no other information counts as a first name. A lone surname with no first name known goes out as real text when First names is unticked.
7. Windows is unit-tested by simulation only. Nothing has been run on a real Windows machine. The Windows search-index exclusion (`.noindex` is macOS only) is untested.
8. Copy buttons have not been tried against a real system clipboard in a test.
9. Extra entity types (phone, date of birth, SSN, case numbers) wait for the owner's list.
10. The "Copy with hidden names" button: the owner has not said whether to remove it.
11. Starting the app needs a terminal. The owner said that is fine.
12. A review by a second model (Opus) in Nov 2026 suggested more removals and merges (Compare, Keep all, the three paths to request more outputs, Rescan as a button, the threshold box). The owner accepted none of those except as listed in the change log below. Ask before removing a feature.

## 14. Change log of decisions (newest last)

- Transcript tab shows real values, scrubbed ones highlighted. No transcript copy in the Outputs page.
- Scrubbing options are one horizontal row under the transcript (and on the intake page), applied at copy time to saved calls as well.
- Three name boxes (Names derived, First names, Last names). First name is the first word, last name is everything after. No middle-name detection.
- Delete client and Delete transcript, with confirm pages that show counts.
- Settings page shows the "Instructions to save in Claude".
- Unscrub (formerly Delete) on Hidden names puts the real words back. It writes a new output version and keeps older ones.
- "Hide this" became "Scrub this", "Text to hide" became "Text to scrub", and the selection popup says Scrub 'word'. The flagged-word "Hide" buttons in typed boxes and the page title "Hidden names" were not renamed.
- Scrub this is on the Transcript view only. Request more outputs is an always-open section under the outputs.
- The sidebar "Add a client by name" box is removed. Clients come from New transcript only.
- The global Keep first names box in Settings is removed.
- A new transcript that matches a client by full name or by the same first name stops and asks, showing the last call date.
- A name added to Hidden names after a call was saved is hidden in every later copy and change request, and shown highlighted on the Transcript tab.
- Typed reply and directions boxes survive a reload, and unsent text asks before the page is left.

## 15. How to work in this repo

- Run the full test suite before you finish. All tests use temp folders and synthetic data. Never touch the real data folder in tests.
- Fixtures are synthetic. Never commit real transcripts. Never commit `.env`, generated `.docx`, build output or credentials.
- No network calls and no logging of transcript text. The audit log holds actions and IDs only.
- New UI rules. No inline script or style, no `|safe`, no remote assets, every POST through the CSRF guard. Check new screens at about 800 and 390 px for horizontal overflow. Breakpoints are in the last block of `style.css`.
- Packaging. `scripts/package.py` builds `dist/matter-workbench-<version>.zip` from an allow list. New runtime files must be added to `DIRS` or `FILES` there.
- `tests/webhelp.py` `Session.stored_text(tx)` reads the saved scrubbed text from disk. Pages show real values, so tests that check what was scrubbed must read the file, not the page.
- After a UI change, restart the app (`pkill -f "Python -m app$"` then start it again) and look at it in a browser at two widths.
- The owner wants a plan and an OK before changes that touch more than three files, no destructive git commands without asking, and conventional commit messages. The project folder is not a git repository at the time of writing.
