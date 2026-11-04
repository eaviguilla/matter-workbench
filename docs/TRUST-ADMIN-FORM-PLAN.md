# Trust Admin Intake Form, plan

Status: built 2026-11-05 with the defaults below (the exact name, Not available only for "I do not have it", Clio's wording kept). Written 2026-11-04 as a plan so the work could be picked up on another machine.

## Goal

Add the fourth Clio intake form as a form output, the same way the other three were added: Claude answers it from the transcript, each answer has its own copy box, and the later Clio extension (see `CLIO-EXTENSION-PLAN.md`) can fill the real Clio form from the saved answers.

The three forms already built are `probate-intake-form`, `estate-plan-intake-form` and `general-intake-form`. All four forms are now known, so after this one the form list is complete.

## The Clio page

Copied from Clio with the matter, submitter and form ID numbers left out. The official name is **Trust Admin Intake Form**. It has 6 questions and 3 follow-ups.

| Clio question | Type on the page | Follow-up |
|---|---|---|
| What was the name of your loved one? | single-line text, 255 | none |
| Do you have a copy of the estate plan you can email, mail, or drop off to us (trust, will, etc.)? | pick one: Mail, Drop Off, Email, Not available | Not available opens "When will it be available?" (single-line text, 255) |
| Do you have a copy of the death certificate you can email, mail, or drop off to us (trust, will, etc.)? | pick one: Mail, Drop Off, Email, Not available | Not available opens "When will it be available?" (single-line text, 255) |
| Are there any disagreements or unresolved matters among family members regarding your loved one's belongings or affairs? | Yes or No | Yes opens "Please explain." (single-line text, 255) |
| How did you hear about us? | single-line text, 255 | none |
| Is there anything else you would like us to know? | long text area (65535) | none |

Notes on the page:
- The death certificate question carries the words "(trust, will, etc.)" at the end. That looks like a copy of the estate plan question. Keep it exactly as Clio has it, because the later extension finds fields by their title.
- The disagreements question uses a curly apostrophe (loved one’s), as in the probate form.
- Both "When will it be available?" boxes have the same title, so the app needs its own way to tell them apart.

## Proposed form: 9 entries

Same approach as the other forms: each follow-up is its own entry that names the answer that opens it, and each entry has a kind.

| # | Entry | Kind | Opened by |
|---|---|---|---|
| 1 | What was the name of your loved one? | text, 255 | |
| 2 | Do you have a copy of the estate plan ...? | radio: Mail, Drop Off, Email, Not available | |
| 3 | When will it be available? (estate plan) | text, 255 | 2 is Not available |
| 4 | Do you have a copy of the death certificate ...? | radio: Mail, Drop Off, Email, Not available | |
| 5 | When will it be available? (death certificate) | text, 255 | 4 is Not available |
| 6 | Are there any disagreements or unresolved matters ...? | yesno | |
| 7 | Please explain. (disagreements) | text, 255 | 6 is Yes |
| 8 | How did you hear about us? | text, 255 | |
| 9 | Is there anything else you would like us to know? | textarea | |

Entries 3, 5 and 7 take the exact Clio title in `Question.clio` ("When will it be available?" and "Please explain.") and a distinct `text` in the app, as entries 14 and 19 of the Estate Plan form do.

## What is new compared with the forms already built

1. **A follow-up opened by a radio option, not a Yes or No.** `Question.when` already holds any (number, answer) pair, so the model needs no change. The hint reads "Only if answer 2 is Not available." The existing structure tests assume the parent is always a `yesno` entry, so that assertion must accept a `radio` parent whose option list holds the answer.
2. **Two radios with four options.** The `radio` kind and its hint ("One of: ...") exist already from the General Intake Form.
3. Nothing else. No new kind, no change to the `[ANSWER: n]` format, the parser, the connector or the pages.

## Work, in order

Small, about the size of the General Intake Form.

0. Optional first: remove the hard-coded output counts from the tests. Several tests say `== 5` or `== 6` for how many outputs a page lists, and every new form means editing them. Derive those numbers from `len(OUTPUTS)` and `len(FORM_SLUGS)` instead. Do this with careful single-purpose edits and run the tests after each file, because an earlier bulk replace corrupted two test files.
1. `app/forms.py`: add `TRUST_ADMIN_FORM` (9 entries above), `TRUST_ADMIN = tuple(q.text ...)`, and register both in `QUESTIONS` and `DETAILS` under `trust-admin-intake-form`. Add the delivery options as a constant.
2. `app/outputs.py`: add `("trust-admin-intake-form", "Trust Admin Intake Form")` to `FORM_OUTPUTS` and `"trust-admin-intake-form": "Trust admin"` to `SHORT_NAMES`.
3. Tests:
   - `tests/test_forms.py`: unpack four slugs, add `forms.count(TRUST) == 9`, add a structure test for the entries, kinds, options and `when` pairs, and loosen the parent-kind assertion in the two existing structure tests to "yesno, or radio with that answer among its options".
   - `tests/test_outputs.py`, `tests/test_ux_round.py`: add the fourth slug to the lists of slugs, and raise the page counts from 6 to 7 (unless step 0 already derived them).
   - `tests/test_workspace.py`, `tests/test_ui_cases.py`: the "Not requested" and `name="output"` counts, 6 to 7.
4. Docs: `README.md`, `CLAUDE.md`, `docs/ARCHITECTURE.md` (six outputs becomes seven, three forms becomes four).
5. `docs/claude-project/JLC-CASE-NOTES-V2.md`: add the form to the output list, the question list and the answering rules below. Re-paste the instructions block into the Claude Project afterwards.
6. Check: run the tests, then in demo mode (`python -m app --demo`, about 30 seconds to start) import a sample `[OUTPUT: trust-admin-intake-form]` reply and look at the panel.
7. Commit and push.

## Answering rules for Claude (draft)

These go into the Project instructions. They follow the rule that applies to every output: use only what the transcript says, write Not discussed when it was not said, never invent.

- Entry 1: the decedent's name as a placeholder, exactly as written.
- Entries 2 and 4 (copy of the estate plan, copy of the death certificate): write exactly one option. Mail, Drop Off or Email only if the caller said how they will get it to the firm. Not available only if the caller said they do not have it or cannot get it yet. If the caller said they have it but never said how it will arrive, write Not discussed.
- Entries 3 and 5: answer only if entry 2 or 4 is Not available, with what the caller said about when it will be available, in 250 characters or fewer. Otherwise Not discussed.
- Entry 6: exactly Yes or No, and No only if the caller said no. Entry 7 only if 6 is Yes, neutral, no legal label, 250 characters or fewer.
- Entry 8: how they heard, as said, 250 characters or fewer.
- Entry 9: the notes box with no limit: the full overview for Jordan, written like `jordan-calendar-overview`, plus anything the call held that no other box could take.

## Questions to settle before building

1. Is the name **Trust Admin Intake Form** exact? The app would show it that way.
2. Entry 2 and 4 wording: is "Not available" only for "I don't have it", or also "I have it but can't send it yet"? The draft rule uses the first, and asks "when will it be available" only then.
3. Should the death certificate entry keep Clio's odd "(trust, will, etc.)" ending in the app, or show a cleaned title while keeping the exact one for Clio? The plan keeps the exact title so the extension can match it.

## Picking this up on another machine

1. `git clone https://github.com/eaviguilla/matter-workbench` and open the folder.
2. Python 3.11 or newer. Run `py run.py --install-only` (Windows) or `python3 run.py --install-only` (macOS). It builds `.venv`, installs the libraries and downloads the name model from the GitHub release. The first run takes a few minutes and needs the internet. The model is about 580 MB.
3. Run the tests: `.venv\Scripts\python -m pytest -q` (Windows) or `.venv/bin/python -m pytest -q` (macOS). On Windows two tests in `tests/test_security.py` fail because of Python 3.14 and the way the test reads files, not because of the app. Python 3.12 or 3.13 avoids the first one.
4. Run the app: `py run.py` or `.venv\Scripts\python -m app`. Its data folder is separate on each machine, so clients on one machine do not appear on the other.
5. The Claude Desktop connector (`save_output`) is set up per machine. Turn it on in Settings and add `.venv\Scripts\python.exe -m mcp_server` (with the full path on that machine) to Claude Desktop's MCP config. See `docs/claude-project/JLC-CASE-NOTES-V2.md`.
6. `git pull` before starting, and push when done. Git needs a GitHub sign-in on each machine with write access to the repository.
