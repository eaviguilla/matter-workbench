# Matter Workbench

A local tool for turning call transcripts into text that is safe to paste into claude.ai, and for turning Claude's replies back into text with the real names in it. Names, emails and addresses are replaced with placeholders on this computer. The only data that leaves is what you paste into claude.ai.

## What you need

- Python 3.11 or newer.
- About 0.6 GB of disk and 1 to 2 GB of RAM while the name model is loaded.
- Full-disk encryption on (FileVault on macOS, BitLocker or Device Encryption on Windows) and the OS firewall on. The app stores real names as plain text, so this is what protects them when the computer is off. The app cannot check these for you.

## Install

macOS or Linux:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,ner]"
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -e ".[dev,ner]"
```

## Installing on another computer

Step by step guides for the person doing the install are `INSTALL-GIT.md` (from GitHub) and `INSTALL-ZIP.md` (from the
zip, shipped inside it as `START-HERE.md`).

There are two ways to install on a fresh machine. Both end with one command, and both install the name model.
Install Python 3.13 first (python.org). On Windows the installer provides the `py` launcher. Use a short folder
that is not synced, such as `~/matter-workbench` on a Mac or `C:\MatterWorkbench` on Windows.

Route 1, git. Needs git, or use Download ZIP on GitHub.

```bash
git clone https://github.com/eaviguilla/matter-workbench.git ~/matter-workbench
cd ~/matter-workbench && python3 run.py
```

```powershell
git clone https://github.com/eaviguilla/matter-workbench.git C:\MatterWorkbench
cd C:\MatterWorkbench; py run.py
```

The model is not in git. `run.py` downloads it once (about 570 MB) from the GitHub release named on the first line
of `models/MODEL-SHA256.txt`, checks every file against the SHA-256 in that list, and only then puts the file in
`models/gliner_pii`. A download that stops continues on the next run. If the machine is offline, the app still
starts and the banner says scrubbing is blocked until `run.py` is run again while online. To update, run `git pull`
and then `run.py`.

Route 2, the zip. On the machine that has the model, build the zip.

```bash
.venv/bin/python scripts/package.py
```

```powershell
.venv\Scripts\python scripts\package.py
```

It lands in `dist/` (about 580 MB) and holds the app, the connector, `run.py`, a sample call, the model, and
`models/MODEL-SHA256.txt`, `START-HERE.md` (a copy of `INSTALL-ZIP.md`) and `NOTICE.txt`. The build stops if the model files do not match the
list, or if it finds a client file, key, `.env` or Word file. `--no-model` builds a small zip, and `run.py` then
downloads the model on the first run. Send the zip, unzip it into a new folder, and run `python3 run.py` or `py run.py`
there. The model is already in the zip, so nothing is downloaded for it. The libraries still come from the internet
on the first run. To update, unzip the new zip into a new folder, run it, and delete the old folder.

What `run.py` does on every start, in order. If something already answers on the port, it opens the page and stops,
and touches nothing. Otherwise it checks the private environment in `.venv`. If the environment works and matches
`pyproject.toml`, it installs nothing and deletes nothing. An environment that works but has no note of how it was
built is kept and only noted. A change to the requirements installs into the existing environment, and only
a broken environment, or one built for another kind of computer, is built again. Then it checks the model. If the
model files are the ones it checked before (same size and time), it reads and downloads nothing. A version bump,
new code or a moved folder never reinstalls. `--reinstall` rebuilds the environment, and `--install-only`
installs both and stops.

To release a new model, export it, write the list with `.venv/bin/python scripts/package.py --manifest model-v2`,
create a GitHub release with that tag and upload the four files in `models/gliner_pii`, and only then push the list.
Machines that pull the list before the upload would get a 404. Never delete an older release, because older copies
still use it.

## Turn the model on

Scrubbing is blocked until the model is installed. `run.py` installs it for you, from the package or by download, so you only need these steps to build or change the model on your own machine. The app still starts without it, and Settings shows the model status. The model is GLiNER `urchade/gliner_multi_pii-v1` (Apache 2.0). The export script checks the license first and refuses anything that is not Apache 2.0 or MIT. Export is a one-time step that needs the heavy `export` extra (torch). It writes about 570 MB to `models/gliner_pii`.

macOS or Linux:

```bash
.venv/bin/pip install -e ".[export]"
.venv/bin/python scripts/export_onnx.py --model urchade/gliner_multi_pii-v1 --out models/gliner_pii
.venv/bin/python scripts/eval_scrub.py --model-dir models/gliner_pii
```

Windows PowerShell:

```powershell
.venv\Scripts\pip install -e ".[export]"
.venv\Scripts\python scripts\export_onnx.py --model urchade/gliner_multi_pii-v1 --out models\gliner_pii
.venv\Scripts\python scripts\eval_scrub.py --model-dir models\gliner_pii
```

The model loads on first use and unloads after 10 idle minutes (Settings). You can remove the `export` extra and torch afterwards. Runtime needs only onnxruntime, tokenizers and numpy.

## Run it

```bash
.venv/bin/python -m app
```

```powershell
.venv\Scripts\python -m app
```

Open http://127.0.0.1:8765. The server listens on 127.0.0.1 only and rejects any other Host header. To look around without touching real data, run `python -m app --demo`. It uses synthetic clients and a temporary folder that is removed when it stops.

Data lives in `~/Library/Application Support/MatterWorkbench` (macOS) or `%LOCALAPPDATA%\MatterWorkbench` (Windows). Set `MATTER_WORKBENCH_HOME` to move it. The app refuses to start if the folder is inside OneDrive, iCloud Drive, Dropbox, a macOS CloudStorage folder or a Git repository.

## What transcript layouts are accepted

Any text. The app never refuses a transcript for its layout. It looks for speaker lines and uses them when it finds them: a bullet with a name and time (on one line or split over several), `[0:01] Name:`, `Name 0:01`, `Name (0:01)` and `Name: text`. Plain `Name: text` lines count as speakers when a label repeats, or when there are at least two different labels and these lines are a third of the text (full names or roles such as Caller) or more than half of it (single first names). One heading such as `Plan: call back` stays plain text. A name used as a speaker label is known to be a person before the model reads anything, so it is scrubbed for certain. Role labels such as `Caller`, `Agent` and `Speaker 1` are kept, not scrubbed. Text with no recognizable speaker lines is scanned as plain text, and the review page says so. In that case the name model is the only thing finding names, so read the flagged words closely. On the test calls with all speaker lines removed, the model left 2 of 211 tagged values, and both were flagged for review.

## Daily use

1. For someone new, click New transcript, pick the call date and paste. The app reads the names, takes the first name of the person who is not the first speaker (the first speaker is usually the office), and creates that client at once. You go straight to the review, and a note says which client was made. Rename it under Manage client on the client page if the guess was wrong. Renaming changes the display name only, so the ID (for example `Maria-20261102-1`) and earlier chats still match.
2. For a returning client, click them in the sidebar and use Add transcript. Their registry keeps each person's placeholder the same across calls.
   - If you paste a call into New transcript and the app already knows someone in it by full name, it stops and asks, to avoid a second copy of the same client.
   - If it finds nobody but the first speaker, it asks for a first name.
   - A client made for a review you never saved can be deleted with Delete client at the top right of its page.
3. Review. Capitalized words the scrubber could not place are listed with context. Choose scrub or keep for each, or add text it missed. Choose each place shows every occurrence of a word with its own Scrub or Keep, for words such as May that are a name in one sentence and a month in the next. Your choice is kept by position, so a kept place is not flagged or hidden again and the word is not made known or kept for other text. Saving needs every flag decided. Copy for Claude stays off until the transcript is saved.
4. Open the transcript. A client has one page, `/clients/<id>`. At the top is the client name and ID, then a transcript selector with an older arrow, a drop-down and a newer arrow, and a label such as "3 of 14". Each option shows the date, the optional title, the transcript ID and its output state. Under it sit only the status and Edit title, because the selected option already reads the title. The newest transcript opens by default, and `?tx=<transcript id>` picks another. Below the selector, a switch chooses Outputs or Transcript. It opens on Transcript while nothing has been requested or received, and on Outputs after that. The Transcript view shows the real values with the words Claude will not receive highlighted by kind (a quiet key on the heading row names Person, Email, Address), and plain text for any kind the options send as written. Under the text is one row of scrubbing options (Names, First names, Last names, Email addresses, Street addresses). It saves when changed and also sits under Add transcript. The first name is the first word of a name and the last name is everything after it, so Names is ticked only while both are. The options apply at copy time, also for calls saved earlier, so a box you untick is sent to Claude as real text, and a name hidden in part is split: "Maria Elena Lopez" with First names unticked goes out as "Maria [PERSON_1.rest]", and with Last names unticked as "[PERSON_1.first] Elena Lopez". `[PERSON_1.rest]` stands for everything after the first word and comes back whole in Claude's reply. Unticking both is the same as switching names off. Typed boxes (change requests, directions, messages) still hide last names. The saved copy record keeps the hidden form. Then the output checklist, an optional "Specific directions for Claude" box and Copy for Claude, then the Scrub this box. Copy for Claude comes first so the main action shows without scrolling on a 1440x900 window. After a copy the page moves to Outputs, which shows the board of 3 columns, the box for Claude's reply and an always open "Request more outputs" section under the outputs. Old `/transcripts/<id>` addresses redirect to the client page. Text typed in the reply box or a directions box is kept in the browser tab as you type, comes back after a reload or a click away, and is cleared when you submit or copy it. Closing or leaving the page with unsent text asks first. A pasted call that matches a client by full name or by the same first name stops and asks, showing that client's last call, so a second record is never started by accident. A client with no transcripts shows an invitation with an Add transcript button. Scrubbing options, the running summary, the message route and Manage client are under More.
   - Versions. Each output column has an older arrow, a drop-down (for example "v9 latest, 3 Nov, Claude", where the source is Claude, Pasted or Hand edit), a newer arrow, and a Compare with drop-down (Off, Previous with its version number, or any other version, with no version listed twice). Compare marks changed words and ignores differences in punctuation alone. A Back to latest link shows when an older version is on screen. Columns are independent.
   - Scrub this. If a name, email or address got through, select it in the transcript (or type it) and press Scrub this. The app hides it in this call, adds it to the client's hidden names and updates any output that contains it as a new hand-edit version. It tells you how many places changed. There is no undo, and it warns when Claude has already received the call. It refuses text that overlaps a placeholder, empty text and over-long text. Scrub this is on the Transcript view only. Selecting text there also shows a small Scrub 'text' button beside the selection, with a type choice. It fills this form and submits it with the same confirmation.
   - Title. A call can have a short optional title, set on the review page or from Edit title on the client page. It is saved as typed, with no flagged-word check, because it is shown on this computer only and is never part of any text copied for Claude.
5. Copy for Claude, in the request bar. Tick the outputs you want from the checklist, grouped as Notes (Clio Note, Overview for Jordan's calendar notes, Clio form note) and Intake forms (Probate Intake Form, Estate Plan - General Intake form, General Intake Form, Trust Admin Intake Form). Copy stays off until at least one is ticked, and the app refuses a copy with none. The copied text starts with one line, `Outputs to write: Clio Note (clio-note), ...`, then your directions, then the line `[CLIENT: <id> | TX: <id>]`, then the scrubbed transcript. The app writes no rules for how an output is written. Those rules live in your claude.ai Project, and Settings has the text that tells Claude the format this app reads. The directions box shows the saved directions with real names, because a copy scrubs whatever it holds. The directions are stored only in scrubbed form and stay in the box after a copy, so a second copy sends them again, until you clear the box and copy. Paste it into that client's chat in your claude.ai Project. The next Copy starts with the same boxes ticked. There is no Output instructions section in Settings any more. Jordan is staff, so the name in the output title is sent as written.
6. When Claude replies, the page shows only the outputs this call asked for or already has. The text outputs sit in a board in the same order (one, two or three columns, depending on how many are on the page), and the intake forms sit below it in full-width Intake forms panels. An output you asked for shows "Waiting for Claude" until it arrives. An output you did not ask for is not on the page, and Request more outputs, at the bottom, is where you add one. It pre-ticks only what is still waiting, so asking for one more does not make Claude write the others again. A form shows every question Clio would show now. A follow-up that Clio shows only after an earlier answer (for example "Please explain" after a Yes) is folded into a closed row under its question when that answer does not open it and the follow-up is empty. A follow-up that holds an answer is never hidden, it is marked as one that Clio will not show and Copy all leaves it out. Board columns sit side by side from about 1200px of window width and stack below that. Each answer of a form has its own box with a Copy button and an Edit link (Ctrl or Cmd plus Enter saves, Esc cancels). A reply that answers only some questions changes only those answers, and writing Not discussed clears one. A form reply needs a line `[ANSWER: 5]` above each answer, and a repeated or unknown number blocks the save. There are two ways to get the reply in, and both work.
   - Connector. If Claude has the `save_output` tool, each output is saved as it is written, and an open call page picks it up within a few seconds.
   - Paste Claude's reply, under the board. Paste the whole reply and choose Check reply. It is saved to this call after you confirm. If it has `[OUTPUT: slug]` lines, the app splits it and saves each part as a new version of that output, all in one save. If a marker names an unknown output, the check page says so and nothing is saved until you fix the line. If the reply has no markers, you choose which output it is. The older Import page still works and is linked from Running summary on the client page, which is where a summary is imported.
   Each column opens on its latest version, shown with the latest marked. The version chips switch only that column. Compare appears once an output has 2 or more versions. "Copy" is the one button and copies the version on screen with real values filled in. "Copy with placeholders" and "Edit" are quieter text actions beside it. The first copies the placeholder text and the second opens the placeholder text, where a save adds a new version with the source `edit`. Old versions are never changed. The import check still reports placeholders the reply did not use. A version saved before a name was hidden still shows the real name on screen, but "Copy with placeholders", the edit form and a change request mask every known real value again, for any version, and the saved file is not rewritten.
7. To change one output, type the change in that column's "Ask Claude to change this" box and choose Copy for Claude. The app replaces known names, emails and addresses in what you typed, using this client's registry, before anything is copied or stored. The copied text holds, in order, `Change request for <name> (output ID <slug>).`, the header line, your scrubbed request, the current text of the version on screen with placeholders, and the scrubbed transcript. It is saved as a message of kind `correction`. If the scrubber flags capitalized words it could not place, the column lists them and the copy waits until you tick each one or edit the text.
8. Text you typed is never thrown away by the page. While a change box or the reply box holds text, the automatic refresh and the reload after a copy are skipped. A "New version available" note with a reload link appears instead, and version links ask before leaving.
9. For a comment that is not about one output, use "More" on the client page, which links to Message to Claude. Real names typed there are replaced before you copy. Corrections add `[CORRECTION]` and the header.

Checks on every imported reply and every hand edit: unknown placeholders (red, left as written, copy asks for confirmation), placeholders never used (info), and real values already in plain text (warning that the chat may hold a real name). Real values the registry knows are replaced with placeholders before an output is stored, so stored files never hold restored text.

When a client's chat gets long, use "Copy the summary request" under Running summary on the client page, import Claude's summary there with "Import a summary" and "Running summary" selected, and paste it first in a new chat.

### First names

Each client's scrubbing options row decides this (the First names box). With First names unticked, "Maria Lopez" goes to Claude as "Maria [PERSON_1.rest]". There is no global setting for it any more. The client's own first name is always visible in the client ID and the header.

## Set up the Claude Project

One claude.ai Project holds all client work. Each client gets one chat, titled with the client ID only. Check these once:

- Privacy settings: whether chats may be used for model training.
- Project memory: keep it separate from account memory so client context stays out of other chats.

Paste this into the Project instructions, and adjust it if you wish. Settings has the current text. Add your own rules for how each note and form is written, because the app does not send any:

```
You help a law office with client intake. Every message starts with a header line, [CLIENT: <client ID> | TX: <transcript ID>].

Personal data has been replaced with placeholders such as [PERSON_1], [PERSON_1.first], [PERSON_1.last], [PERSON_1.rest], [EMAIL_1] and [ADDRESS_1].

Rules
- Copy placeholders exactly as written. Never change their case or format, never invent new ones, and never guess the real values.
- The same placeholder always means the same person or thing across this chat.
- Do only the outputs the message asks for. Do not write the others.
- Use only what the transcript says. Never invent, assume or fill in a fact, name, date, amount or answer that was not said. If it was not said, leave it out, or write Not discussed in a form answer.
- Start every output with the header line of the transcript it is based on.
- Saving. Reply with each output under a line that reads exactly like [OUTPUT: clio-note], using the output ID (clio-note, jordan-calendar-overview or clio-form-note, probate-intake-form, estate-plan-intake-form), with nothing else on that line. The person saves your reply into the app.
- The intake forms (probate-intake-form, Probate Intake Form and estate-plan-intake-form, Estate Plan - General Intake form; general-intake-form, General Intake Form; trust-admin-intake-form, Trust Admin Intake Form) are answered question by question. Write each answer under its own line that reads exactly [ANSWER: <question number>], for example [ANSWER: 5], with nothing else on that line. Use the question numbers of the form. Leave out a question you have nothing for, or write Not discussed.

Changes
- A message that starts with "Change request" revises one output for the transcript named in its header. Return the full revised output, not only the changes, and save it the same way as above.

Summaries
- If asked for a running summary of the chat, keep every placeholder exactly as written.
```

## Where the data is

Everything is in the data folder, `~/Library/Application Support/MatterWorkbench.noindex` on macOS and `%LOCALAPPDATA%\MatterWorkbench` on Windows.

```text
settings.json
audit.jsonl
clients/Tomas-20261102-1/
  client.json
  transcripts/TX-20261102-1/
    transcript.txt
    clio-note.json
    jordan-calendar-overview.json
    clio-form-note.json
```

`client.json` holds real names, emails and addresses in plain text, next to the client's status, options and messages. `client.json` also lists, for each transcript, which outputs you ticked at the last copy (`requested_outputs`). A transcript's folder holds only scrubbed text and placeholders, unless the scrubber missed a name. Each output has its own file, which exists once that output has a version. A file is only ever added to, so earlier versions stay, and saving one output never rewrites another's file.

To back up, copy the data folder while no save is running. To restore, copy it back. Keep backups as private as the original, because they hold the same real names.

Never send `client.json` to Claude or anyone else. If a saved file is damaged, the app names the client and keeps the others working. This command reports what is wrong using file and field names only, so its report is safe to share:

```bash
.venv/bin/python -m app.check
```

```powershell
.venv\Scripts\python -m app.check
```

A hidden name whose value is a code such as `[PERSON_1]` (saved by an earlier version, which scrubbed its own codes again) is reported by ID, never by value. The Hidden names page can delete it. To remove every such entry in one step, with a count and nothing else shown, run this. It changes nothing else, and outputs that were already rewritten to a wrong code show that code as unknown, which is the signal to fix them.

```bash
.venv/bin/python -m app.check --fix
```

```powershell
.venv\Scripts\python -m app.check --fix
```

## Optional connector for Claude Desktop

Off by default. Turn it on in Settings, then register `python -m mcp_server` in Claude Desktop's MCP configuration (Settings shows the exact command for this machine). It has one tool, `save_output(client_id, transcript_id, output, content)`, where `output` is `clio-note`, `jordan-calendar-overview` or `clio-form-note`. It cannot read, list or search anything, and its replies hold no stored data. It rejects bad or unknown IDs, an unknown output, mismatched client and transcript, and content over 200 KB. Every call adds a new version of that output. It works while the web app is closed, and an open call page picks up the new version within a few seconds. The reply box on the call page still works as the fallback, because Claude may skip the call.

## Security

- No outbound network calls anywhere in the app code. No CDN assets, fonts or telemetry. A test blocks sockets and runs the full flow.
- Host header check (127.0.0.1, localhost, [::1] only), a per-session CSRF token on every state-changing request, strict Content-Security-Policy with no inline script or style, no framing, no caching.
- Real values and transcripts are shown as text, never as HTML. Pages are rendered with autoescaping and the CSP blocks inline code.
- Logs hold IDs, counts and exception type names only. A test searches logs for real values.
- Real values are stored unencrypted in `client.json`. Anyone or anything running as your user can read them, and so can backups. Rely on disk encryption and keep this folder private.
- The data folder is owner-only (0700, file 0600) on macOS and Linux. The app refuses to use a synced or Git-tracked folder, and keeps the folder out of Spotlight through its `.noindex` name. On Windows it asks Windows Search to skip the folder, which has not been tested on a real machine. A folder set with `MATTER_WORKBENCH_HOME` needs its own name ending in `.noindex` on macOS.
- A save is crash-safe. Tests kill the process at each step and run two writers at once.
- The audit file records actions, IDs and byte counts, never content.
- Scrubbed transcripts, messages and outputs contain placeholders, not real values, unless the scrubber missed one.

## How well does it scrub

`scripts/eval_scrub.py` scores 10 synthetic conversations (609 tagged values). With the model on, 99.8% of tagged values are scrubbed automatically, and the one miss is flagged for review. Rules alone reach about 94.6%, so the app requires the model. This is measured on the same fixtures the rules were tuned on. Hand-label real transcripts, keep them outside this repository, and run the script on them before you rely on it. A miss is a leak, so the review gate is part of the safety design, not an extra.

Known gaps: hyphen-spelled emails and spoken-number addresses are not detected, bare first names rely on the model, and the nickname rule can join Joy and Joyce. Only names, emails and addresses are scrubbed. Phone numbers, account numbers and similar need a rule added to `app/scrub/regex_rules.py` once you decide the list.

## Deliberate differences from the build spec

- Outputs and transcripts render as plain text. There is no Markdown rendering, so there is nothing to sanitize and DOMPurify is not needed.
- Plain HTML and a small script instead of htmx. No assets are fetched from anywhere.
- A transcript is saved only after the review is complete, so the "draft" status is unused. The original is not stored, so the review cannot be resumed later.
- `client.json` holds one registry entry per person or value, in plain text, by the owner's decision.
- The design pass used the built-in browser for screenshots instead of Playwright, plus Impeccable's critique and detector.
- A spoken email is restored in written form, a spelled name is restored as the name, and a short address restores the full stored address.

## Tests

```bash
.venv/bin/python -m pytest
.venv/bin/python scripts/eval_scrub.py --model-dir models/gliner_pii
```

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python scripts\eval_scrub.py --model-dir models\gliner_pii
```

Tests use synthetic data only and temp folders. They never touch the real data folder. Real-model tests skip if the model is not installed.

## Test clients

`scripts/seed_test_cases.py` adds 14 invented clients, all with names that start with Test, so you can look at the client page in every state. They cover 3 text outputs with several versions and a hand edit (Testa also has a probate form), 1 output, 2 outputs waiting, a call with nothing asked for, a very long output, an unknown placeholder and a real value in a reply, 6 calls on different dates, a very long first name, an archived client and a client with no calls. Four newer cases have call titles. Testk has an output with 9 versions, Testl has 40 calls, Testm has a transcript and a note that still hold the name Hartley Quimby for trying Scrub this, and Testn has no calls, so you can paste `samples/review_may.txt` and try Choose each place. Every name, email and address in them is made up, and the registries hold those values so restored names show.

```bash
.venv/bin/python scripts/seed_test_cases.py
```

```powershell
.venv\Scripts\python scripts\seed_test_cases.py
```

It uses the normal data folder, or the folder in `MATTER_WORKBENCH_HOME` if that is set, and `--data-dir PATH` picks another. It is safe to run twice, because it skips any client whose first name already exists, and it never changes other clients. The script is not in the zip. To remove the test clients, archive them or delete them by hand from the data folder with the app closed.

## Layout

- `app/scrub/` parser, registry, regex and cue rules, pipeline, GLiNER stage, evaluation.
- `app/rehydrate.py` restores values and reports problems.
- `app/paths.py`, `app/store.py`, `app/check.py` location check, file storage, the safe damage report.
- `app/workflow.py` what the screens do, without web code.
- `app/web/` FastAPI app, templates, one stylesheet, one script.
- `mcp_server/` the optional connector.
- `scripts/` model export, parity check, evaluation, and the test client seed.
- `tests/fixtures/` ten synthetic intake conversations with tagged ground truth.

## Changes in UX round 4

Typed text about a transcript now respects the choices made for that transcript.

- A word hidden for one transcript only is replaced by its code in typed text only when every place of that word in the transcript was scrubbed. If some places were kept, such as May the month beside a sister called May, each typed occurrence is flagged with "Hide as <code>" and "Send as written". Nothing is sent as a code silently.
- A word decided Keep for this transcript is not flagged in typed boxes, unless it also matches a hidden person. On the review page this uses the choices on the same page before saving.
- Hide from a flag list (change box, directions boxes, Message) applies to this transcript only. It is stored as a transcript-only entry (`only`, plus `via` for the transcript whose message or directions added it) and is never matched in other transcripts, imports or placeholder copies. The option "Also hide in future transcripts for this client" makes it client-wide. The note says which scope applied. Stored files are never rewritten from here. The Message page with no transcript offers the client-wide Hide only.
- After the stale-version refusal the typed change text is kept in sessionStorage for that transcript and output, restored after the reload, and cleared after a successful copy or when the box is emptied. It is never stored in client files.
- The selection Hide popup snaps to whole words and trims lowercase words at both ends. It shows no button when nothing capitalised remains.
- The review directions Hide leaves a line such as "Quillfield will be hidden for this transcript".
- Hidden names: Unscrub puts the real words back in every saved transcript of the client and adds a new "Name restored" version to each output that held the name (older versions stay), then removes the entry. The name is not hidden again in later copies. Unscrub shows "Unscrubbed <value>" once. Rows added from a message or directions say "Added from a message on <title>". An archived client reads "Archived. Hidden from the client list. Restore". The connector Save button shows only without scripts. Import check says "as a new version" for one output.

Repair for entries created by an earlier flag-list Hide: not done. Those entries were saved client-wide with no record of their source, so `python -m app.check` cannot tell them apart from entries added on purpose. It only validates the new `only` and `via` fields. Review Hidden names and delete any that should not be client-wide.

## Changes in the UX review round

New transcripts take the output checklist and optional directions on the review page. Client matching ignores office staff. The Outputs view shows the paste box first while a reply is awaited, labels older versions, highlights changed words in Compare, and lets you hide a name from there. Settings save in place, one Save per section. The Hidden names page has one row per person.

## Changes in UX round 3

A name you hid for one transcript only (Choose each place) is hidden in anything you type about that transcript: the change box, the directions boxes and Message. It is replaced by its code and never flagged, while the box keeps your words. Hide beside a flagged word now changes only the text being sent and adds the word to Hidden names. It no longer rewrites the transcript or outputs, which the Scrub this form still does. The Review page checks directions as you type, using the choices made so far. A change request is refused if the output has a newer version than the page shows. Hidden names says where a transcript-only name applies, "Ask Claude for this" shows the old directions as "Last sent" with Use again, the import check names the transcript and drops the header line, and the connector checkbox saves when you change it.

## Changes in UX round 2, second pass

A placeholder code such as `[PERSON_1]` or `[PERSON_3.first]` is never a name. The registry refuses to add one, scrubbing leaves codes untouched and never flags them, and import masking never replaces text inside one. Directions are shown with real names and stored scrubbed, and they stay after a copy. The import check lists each replaced word with its code. Other fixes are in docs/history/UI-PLAN.md.

## Deleting

Delete client sits at the top right of a client page, and Delete transcript at the right of the transcript selector row. Each opens a page that says what will be removed and has one red button and a way back. Deleting a transcript removes its text, outputs, versions and the messages copied for it, and any name hidden for that call only (unless another call still uses it). Names hidden for the whole client stay. Deleting a client removes its folder with every transcript and the saved real values. There is no undo, and text already pasted into claude.ai is not touched. The audit log records the deletion with IDs only.

## Instructions to save in Claude

Settings has a section "Instructions to save in Claude" with a Copy button. Paste it once into the claude.ai Project's instructions. It holds the standing rules (keep placeholders unchanged, do only the listed outputs, how to save or reply, how to revise one output). It names the `save_output` tool only while the connector is on. The names of the outputs still come with every copy, and the writing rules are yours to add in the Project.
