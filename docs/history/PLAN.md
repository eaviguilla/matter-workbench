# Storage and outputs plan

> History only. `docs/ARCHITECTURE.md` is the current guide, and it wins where this file disagrees.

Final plan, agreed on 2026-11-03.

## Decisions

- Plain files only. There is no import step.
- Real values are stored as plain text in `client.json`. There is no encryption, key or keychain.
- Claude never opens the client folder. `client.json` holds the real names. Outputs reach the app through the
  write-only connector or the Import page.
- Each output has its own JSON file, and new versions are only added. Files store placeholders. The app fills in
  the real values on screen and when copying.

## Layout

```text
MatterWorkbench/
  settings.json
  audit.jsonl
  .lock
  clients/Tomas-20261102-1/
    client.json
    transcripts/TX-20261102-1/
      transcript.txt
      clio-note.json
      jordan-calendar-overview.json
      clio-form-note.json
```

`client.json` holds the client's name, status, options, real values, messages to Claude, and each transcript's date,
review status and ticked outputs. An output file exists once Claude has sent that output.

## Save rules

1. A global lock covers every write, because transcript IDs are shared across clients.
2. A new transcript's folder is written first. It counts as saved only when `client.json` lists it.
3. `client.json` is replaced by one atomic rename. Existing text and output files are replaced the same way, after it.
4. Unlisted folders and temporary files left by a crash are ignored and cleaned up at the next start.
5. IDs are checked against a strict pattern before they touch a path, and compared without regard to case.

## Steps

- [x] 1. Fix the save failure, with tests that use the real name model.
- [x] 2. Build the folder storage, the search indexing exclusion and the local check command.
- [x] 3. Remove encryption, the key pages and their dependencies from code, tests and docs.
- [x] 4. Test real process kills at each save step, and saves from two processes at once.
- [x] 5. Recreate the 2 existing empty clients and rebuild the zip.
- [ ] 6. Run the zip on a real Windows machine. This needs the user, because it cannot run here.
- [x] 7. Build the 3 outputs: output files, connector and Import changes, checklist, instructions, outputs page.

## Defaults chosen for step 7

1. Both routes are supported. The connector saves each output as Claude writes it, and the Import page splits a pasted
   reply that has `[OUTPUT: slug]` lines. A reply without markers goes to the output chosen in a picker.
2. The instructions for each output start as plain defaults and are editable in Settings. Copy for Claude sends only the
   ticked outputs' instructions.
3. Hand edits are allowed. They work on the placeholder text and are saved as new versions with the source `edit`.
4. Jordan is staff, so the name in the output title is not scrubbed.

## Update: client workspace

The client page is the single working page (see UI-PLAN.md in this folder). New routes are `POST /transcripts/{id}/hide` and
`POST /transcripts/{id}/title`, and `/transcripts/{id}` redirects to `/clients/{cid}?tx=`. Scrub this runs in one
transaction in the existing save order. Per-place review decisions are saved by span. Hidden-here words are local
registry entities that rehydrate but never match new text. Titles are optional strings in `client.json`, stored as typed with no
scrubbing, shown on screen only and never sent to Claude. Directions are scrubbed and stored as a comment message. No new runtime files, so
`scripts/package.py` is unchanged.
