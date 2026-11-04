# Clio form filler, plan

Status: approved as the next step. Waiting on the saved Clio form pages before any code is written. The owner asked for a plan approval before work that touches more than three files, so confirm the phase 1 start with them.

## Goal

The paralegal clicks Copy for Clio on an intake form, opens the matching blank form in Clio in her own Chrome, clicks the extension, and every answer lands in its field at once. She reviews the page and submits it herself. Nothing is saved or submitted by the tool.

## Decisions made

1. The tool is an unpacked Chrome extension, installed once through Developer mode. The owner chose this on 2026-11-04.
2. It fills values only. It never clicks Submit or any other button, never navigates, and never reads or sends anything off the page. Reloading the page loses the values, which is fine.
3. A blank answer and a "Not discussed" answer both leave the Clio field empty. A field Clio already filled is skipped.
4. Playwright was considered and set aside. It needs a second Chrome profile with its own Clio login and a new Python dependency, and the extension needs neither.
5. Reading the session cookie out of her everyday Chrome was rejected. Chrome encrypts cookies on purpose, the workarounds look like credential-stealing malware, and a copied login for the firm's Clio account is a breach risk.
6. A bookmarklet built from the same fill code is the fallback if Developer mode is blocked on her machine.
7. Whether the account is Clio Grow or Clio Manage does not matter and is not asked. The extension uses the activeTab permission, so it works only on the tab where she clicks it and needs no stored Clio address. This differs from the first plan, which limited it to one host. The fill refuses to run unless enough field titles on the page match the chosen form, so a wrong page is never filled.

## What the owner provides

1. The blank form HTML for all four forms, at `samples/clio-probate.html`, `samples/clio-estate-plan.html`, `samples/clio-general.html` and `samples/clio-trust-admin.html`. Each is the outerHTML of the element that holds all the questions, copied from a test matter with a fake client.
2. A screenshot of each dropdown or date picker while open, only for fields that use one.

Do not send client names, session tokens or URLs with IDs. The build step strips values, scripts and styles from the files before use.

## Conditional entries

A follow-up that Clio shows only after an earlier answer is absent from the Clio page until that answer is chosen. The app already decides this in `forms.visibility(slug, answers)`, which says open, closed, unset or always for each entry, and `forms.schema(slug)` returns every entry (number, text, Clio title, kind, options, condition, limit) as plain data. The extension build uses `schema` to make the mapping files, so a drift test can compare them. The Copy for Clio text carries only entries that are always shown or open and that hold a real answer (not Not discussed). The extension fills a parent entry, waits for the follow-up field to appear, fills it, and skips any field that is absent from the page, because Clio is the final judge.

## Phases

1. Copy for Clio button. A new button on each form panel copies plain text that the extension can parse. First line `Matter Workbench answers for Clio, format 1`. Then the form slug, the client display name, the call date, the version, and the copied time. Then one block per answered question, `--- 3. <question text>` followed by the answer. Last line `--- End of answers`. Empty and "Not discussed" answers are left out. Copy all stays as it is.
2. Extension core. Files under a new top-level `clio_filler/`. A parser for the copied text, a locator that finds a field by label or by the field name from the saved HTML, and a setter that sets the value and fires the input and change events so Clio's page notices. Setters for text boxes, text areas, native dropdowns, radios, checkboxes and dates, plus whatever the screenshots show for custom dropdowns. A popup that reads the clipboard, shows the client name, the form name and how old the copy is, warns if it is over 30 minutes old, and fills after one confirm click. A status line per question, filled, skipped because already filled, or not found.
3. Mapping. A file per form slug, keyed by question number, with the field locators taken from the saved HTML. "Yes, two" style answers fill the choice and flag the rest. Live trial by the owner on a test matter, fixing what Clio does differently from the saved HTML.
4. Packaging and docs. Add `clio_filler` to the package script and update the zip contents test. A short README inside `clio_filler/` and install steps for macOS and Windows. Chrome steps are the same on both. Open `chrome://extensions`, switch on Developer mode, click Load unpacked, choose the `clio_filler` folder. Add the bookmarklet build only if Developer mode turns out to be blocked.

## Tests

1. Node tests with `node --test` for the parser, locator and setters.
2. A mock Clio page built from the saved HTML, filled in headless Chrome and read back with `--dump-dom`. Test folders named `tests` are dropped by the package script's skip list.
3. A drift test that fails if the question numbers or titles in `app/forms.py` no longer match the mapping files.
4. The scan in `tests/test_security.py` extends to the extension code and bans fetch, XMLHttpRequest, WebSocket, sendBeacon, console output, submit calls and location changes.
5. A Python test for the Copy for Clio text, including empty answers, "Not discussed" and codes never appearing, since the text carries real values and goes only to the clipboard.

## Likely failures

1. Custom dropdowns and date pickers that are not native elements. The screenshots show what each one needs.
2. Clio saving or validating on change. The owner said there is no save step, only submit, so this is low risk.
3. A saved HTML page that lacks the options or behavior Clio adds with script. The live trial catches it.
4. Clio rewording a field title. The locator tries the field name first, then the title, and the popup reports any question not found.
5. A managed Chrome that blocks unpacked extensions. Use the bookmarklet.

## Done

1. Both forms fill every mapped field on the owner's test matter, with blanks left blank.
2. All tests pass, including the new ones, and `python -m app.check` reports 0 problems.
3. The package script builds a zip that holds the extension folder and its README.
4. The owner has installed it on a Mac and a Windows machine, or the bookmarklet is built.
