# Client record and call page plan

> History only. `docs/ARCHITECTURE.md` is the current guide, and it wins where this file disagrees.

Written after looking at the running app at 1440px. It extends the existing "Ledger" look in `style.css`: ink chrome,
blue for placeholders, orange for what needs a decision. It keeps that look and changes the layout.

## Problems found

1. The call page shows the whole transcript first, so the outputs start about two screens down.
2. Outputs stack vertically, so they cannot be compared and only one is on screen.
3. Asking Claude to change an output means leaving for the "Message to Claude" tab and choosing the transcript again.
4. The call date appears twice. Each output shows its slug, a long "Not used" placeholder list and a sentence about storage.
5. Import is a separate tab, though a reply always belongs to the call on screen.
6. Every section on the client page has equal weight. Rarely used options sit above the summary, and calls do not lead.

## Call page (`/transcripts/{id}`), top to bottom

1. Title row: "Call of 2 Nov 2026", the transcript ID, the status, a link back to the client. The date appears once.
2. Request bar in one row: the 3 output checkboxes and the "Copy for Claude" button.
3. Output board: exactly 3 columns, always all 3 outputs, in a fixed order. An output not requested or not received shows
   an empty state, so the layout never shifts. Columns from about 1200px of page width. Below that they stack.
4. Paste Claude's reply: an inline box under the board, saving to this call through the existing import check.
5. Transcript, collapsed by default in a `details`, showing the word count and the legend when opened.

The review decision count and the storage sentences are removed. Unused placeholders move into a closed `details`
because they are rarely useful, and no list shows by default.

## One output column, top to bottom

1. Name, in plain words, with no slug on screen.
2. Version row: chips v1, v2, v3, with the latest marked. Choosing a version changes only this column. "Compare" is a
   small control that appears when there are 2 or more versions.
3. Warnings: unknown placeholders, real values found.
4. The text with real names, in a box with its own scroll, so 3 columns line up even when one is long.
5. Actions: "Copy" as the main button (real names). "Copy with placeholders" and "Edit" are quieter.
6. Saved time and source, one small line.
7. "Ask Claude to change this": a text box, then a "Copy for Claude" button, disabled until there is text.

## The change request

`POST /transcripts/{id}/outputs/{slug}/request-change` takes the typed text and the version on screen. The app scrubs the
typed text with the client's registry, then returns text to copy, in this order:

1. What to do: revise only this output, keep placeholders unchanged, return the full revised text, using the save_output
   tool with this output ID if available, otherwise under an `[OUTPUT: slug]` line.
2. The output's standing instructions from Settings.
3. The header line.
4. The scrubbed change request.
5. The current text of the chosen version, with placeholders.
6. The scrubbed transcript.

It is stored as a message of kind `correction`. Words the scrubber flags in the typed text are not sent silently: the
response lists them and copying stops until the person edits the text or confirms each one. The real value of a known
name must never reach the clipboard.

## Keeping typed text safe

The polling reload must never run while a change box has text or the paste box has text. It shows "New version
available" with a reload link instead. Version links on a column with typed text ask before leaving.

## Client page (`/clients/{id}`)

- Calls lead: a list with date, status and, per call, which of the 3 outputs exist. Each row opens the call page.
- Tabs reduce to Calls, Add transcript, Hidden names. The separate Import tab is dropped from the tabs. Its route stays
  for summaries, linked from the summary section. "Message to Claude" stays as a route, linked from a "More" section for
  comments that are not about one output.
- Scrubbing options, running summary and manage move into closed `details` under the calls.
- The "Transcript saved" box sends the person to the call page rather than repeating the copy controls.

## Test cases to keep

`scripts/seed_test_cases.py` adds synthetic clients to the data folder. They are kept for the owner to examine. It is safe
to run twice and never touches other clients. Names start with `Test`.

| Client | What it shows |
|---|---|
| Testa Allthree | 3 outputs, several versions, one with an edit |
| Testb Onlyone | 1 output requested and received |
| Testc Waiting | 2 outputs requested, none received |
| Testd Noneyet | saved call, nothing requested |
| Teste Longtext | a very long output beside short ones |
| Testf Warnings | an unknown placeholder and a real value in a reply |
| Testg Manycalls | 6 calls on different dates |
| Testhlongfirstnamethatkeepsongoingandgoing Wide | a long name, for layout |
| Testi Archived | archived client with a call |
| Testj Empty | client with no calls |

## Checks

Automated tests for the new route, scrubbing of typed text, copy order, flagged words, the board always showing 3
columns, and the fixed client page. Then a browser check at 1440, 1100, 800 and 390px in light and dark on every test
case, including a typed change request and no horizontal overflow, followed by the Impeccable detector.

## Update: one client page

The call page above was merged into the client page. `/clients/{id}` is now the working page and `/transcripts/{id}`
redirects to it.

- Top: client name, then the call selector. It has an older arrow, a native select, a newer arrow and a label such as
  "3 of 14". Options read date, optional title, ID and output state. Arrows are disabled at the ends. A plain GET form is
  the no-script fallback. Typed text in a change, directions or paste box triggers a confirm before navigating.
- Below it, an Outputs and Transcript switch, linkable with `?view=`. It opens on Transcript when nothing is requested
  or received, otherwise on Outputs. After a successful copy the page shows Outputs with waiting states.
- Transcript view: scrubbed text with legend, Scrub this, the output checklist, optional directions, Copy for Claude.
- Outputs view: the 3 column board, the paste box, a closed Request more outputs section.
- Version controls per column: older arrow, select ("v9 latest, 3 Nov, Claude"), newer arrow, Compare with select, and
  Back to latest. Each column is independent.
- The calls list is removed. An empty client shows an invitation with Add transcript. Scrubbing options, summary and
  manage stay under More.
- Review page: Choose each place lists every occurrence with its own Scrub or Keep, and an optional title field.
- Review round (titles, wording, layout): the word is "Transcripts" everywhere. Titles are stored as typed with no
  flagged-word step. The selector row under the picker shows only status and Edit title. Outputs lose the "saved from"
  line and the Unused placeholders list. Copy is the only button per output, with Copy with placeholders and Edit as quiet
  text actions. Sidebar rows are name over a muted one-line ID. The text box height is a clamp on viewport height from
  1200px so the change box shows at 1440x900. The key (Person, Email, Address) is a muted, non-link row beside the
  Transcript heading. In the Transcript view, the checklist and Copy for Claude come before Scrub this, because both
  cannot fit under the text at 900px high. Output text sent as placeholders is masked again for any version.
- Seed cases Testk to Testn cover 9 versions, 40 calls with titles, a name to hide and a client for the May sample.

## Update: UX review round 2 (19 findings)

- Review page: has the 3-output checklist and the directions box above Save. Both are stored (`planned_outputs`, `directions`, `directions_ok`), and the client page opens on Transcript with them filled. A new client starts from the last choice made anywhere.
- Matching: office staff, names stored in more than one client and marked office speakers are ignored. Rows say "Matched <name>", nothing is preselected and the new-client name is never prefilled from another client.
- Outputs view: the paste box comes first while an output is waiting. Older versions read "Copy vN (older)". Compare marks changed words. Scrub this works here too (source "hide", shown as "Name hidden"). The not-requested column has "Ask Claude for this".
- Flag lists in change and directions boxes refresh after a pause, have a Hide button, and skip plain words from `REQUEST_WORDS`.
- Selector: title first, a filter box above it, counter in list order. Archived clients show a one-line Restore bar.
- Settings: one Save per section, saved in place with a note beside the button, starter text with Reset. Hidden names: one row per person, one Save, office staff marked.
- Wording: "hidden name", "Ready to copy", "Copied, waiting for Claude", "N of M outputs received". Disabled Copy buttons say why.

## Update: UX review round 3

- Names hidden for one transcript only are recognised in the change box, directions boxes (Outputs, Transcript, Review) and Message. They are replaced by the transcript's code and not flagged. The box keeps real words.
- Hide beside a flagged word changes only the message and the hidden names. The transcript, outputs and versions are never rewritten by it. The Scrub this form is the only rewrite.
- A change request refuses a stale version with a clear message. The Review directions box flags words live (debounced, server side) with Hide and a message spot beside it.
- Hidden names: "Only in <title or date>" and codes in Merge options. Request more outputs from "Ask Claude for this" starts empty with "Last sent" and Use again.
- Import check names the transcript by title and date, or "Summary for <client>", with no header line in the preview. Review says "Read N speaker lines (Name: text)." plainly. The transcript filter never shows a non-match as chosen. The connector checkbox saves on change.

## Update: UX review round 2, second pass

- Codes are never names. `PLACEHOLDER_RE` and `has_token` live in `app/scrub/registry.py`. Every registry write refuses a value that is or holds a code (`PlaceholderValue`), `iter_forms` skips any such value already stored, `_scrub` drops detected spans and known-value matches that overlap a code and treats codes as covered for flags, and `mask_known_values` skips text inside a code.
- Directions: stored scrubbed only. The box shows `wf.directions_for_display`, which restores a code to its real name only when that name would hide to the same code again (never for hidden-here words). A copy saves the scrubbed directions and their confirmed words again, so they stay until the box is cleared and copied.
- `python -m app.check` reports an entry that holds a code (type and number only). `--fix` removes those entries, or only the code form of a mixed one, and prints counts. The Hidden names page marks such a row and can delete it.
- The reason beside a disabled button has `data-reason`, so the script clears it. "Ask Claude for this" ticks only that output. Import with `kind=summary` is its own short page with no selects. A small Scrub 'text' button follows a selection (`.hidepop`, built in `app.js`, submits the Scrub this form). "Name: text" lines are read as speakers (see the parser rule in README). The save_output sentence is in Copy for Claude and change requests only when the connector is on. The import check lists each replaced word and its code (not stored). The transcript filter shows a match count. An archived client shows only the Restore bar. Compare lists "Previous, vN" instead of repeating vN, and ignores punctuation-only differences.

## Update: UX review round 4

Typed text follows the per-transcript choices. A transcript-only word is replaced by its code only when every place was scrubbed, otherwise each typed place is flagged with two choices. Words kept at review are not flagged. Flag-list Hide is transcript-only with an off-by-default option for the whole client, and the note names the scope. The stale-version refusal keeps the typed change text across the reload. The selection popup snaps to whole words and trims lowercase ends. Hidden names confirms a delete once and explains where a row came from. The archived bar reads "Archived. Hidden from the client list. Restore". The connector Save button shows only without scripts.

## Update: round 5

The Transcript view shows real values with hidden ones highlighted. Scrubbing options are one horizontal row under the transcript card (and under Add transcript), saved on change, no longer under More. Delete client is a quiet red link at the far right of the client header, Delete transcript the same on the selector row, both through a confirm page with counts. Settings has the Claude Project instructions with a Copy button.

The options row is Names, First names, Last names, Email addresses, Street addresses. Names is ticked while First names and Last names both are, and sets both. Both unticked is the same as names off.
