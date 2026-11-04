# Matter Workbench Clio filler

A small Chrome extension that types the answers from Matter Workbench into the open Clio intake form. It fills the fields only. It never presses Submit, never clicks Next, and sends nothing anywhere. The paralegal reads the page and submits it herself.

## What it does

1. In Matter Workbench, open the Outputs tab and press Copy for Clio on a form. The answers go to the clipboard with the client's real names restored.
2. In Chrome, open the blank intake form in Clio.
3. Click the extension icon, check the form name and answer count, and press Fill this page.
4. The popup lists each question as filled, already filled, not found, or to check. Look over the page and submit it.

A question that Clio does not show yet, because it is a follow-up to an answer, is filled a moment after its parent. The extension waits up to 2.5 seconds for it. A box that already holds text is left alone. An answer longer than the box allows, or a date that is not MM/DD/YYYY, is left blank and listed under "To check".

## Install

The extension is the `clio_filler` folder in the Matter Workbench folder. Chrome loads it straight from there. It is not on the Chrome Web Store.

On macOS or Windows, the steps are the same.

1. Open Chrome and go to `chrome://extensions`.
2. Turn on Developer mode in the top right.
3. Press Load unpacked and choose the `clio_filler` folder.
4. Press the puzzle piece in the Chrome toolbar and pin Matter Workbench Clio filler.

If the folder is moved or the app is updated, press the refresh arrow on the extension's card in `chrome://extensions`. If a work Chrome policy blocks Developer mode, ask whoever manages that computer to allow it, or to install the folder for you.

## What it can see and do

The manifest asks for four permissions and no website access.

- activeTab and scripting let it run on the tab you are looking at, only after you press Fill this page. It cannot see any other tab.
- clipboardRead reads what Copy for Clio put there. clipboardWrite is used only by Copy page layout.

It has no background process, no content script on every page, and no code that makes network requests. `tests/test_clio_filler.py` in the project scans every script for fetch, WebSocket, submit, eval, cookie and navigation calls and fails if one appears.

## When a field is not found

The extension finds each question by its title text, because that is what Clio shows. If Clio words a title differently from the form in Matter Workbench, that field is reported as not found.

Open the form, click the extension, open "A field was not found" and press Copy page layout. It copies the form's labels and structure with nothing typed in. Scripts, styles, pictures and typed values are removed first. Paste it to whoever maintains Matter Workbench. This button reads the page only when you press it, and the result goes to the clipboard and nowhere else.

## Keeping it in step with the app

`forms-data.js` lists every entry of every intake form, and is generated from `forms.schema` in `app/forms.py`. After a form changes in Matter Workbench, regenerate it and reload the extension.

macOS or Linux, from the Matter Workbench folder:

```bash
.venv/bin/python scripts/build_clio_forms.py
```

Windows PowerShell:

```powershell
.venv\Scripts\python.exe scripts\build_clio_forms.py
```

A test fails if `forms-data.js` is out of date.

## Files

- `manifest.json` is the extension's declaration.
- `popup.html`, `popup.css` and `popup.js` are the window that opens from the icon.
- `parse.js` reads the Copy for Clio text.
- `fill.js` finds the fields on the page and fills them.
- `forms-data.js` is generated. Do not edit it.
- `tests/` holds the Node and headless Chrome checks. It is not shipped in the zip.

## Trying it on a stand-in page

`tests/sample.html` is a fake Clio form built from the app's form list, in two markup styles. Serve the `clio_filler` folder and open it. Chrome extensions do not run on `file://` pages unless you allow it, so use a local web server.

```bash
python3 -m http.server 8777 --bind 127.0.0.1 --directory clio_filler
```

```powershell
python -m http.server 8777 --bind 127.0.0.1 --directory clio_filler
```

Then open `http://127.0.0.1:8777/tests/sample.html`. Press Copy sample answers for this form, click the extension icon, and press Fill this page. The Submit counter next to the page's Submit button must stay at 0.

## Testing

From the Matter Workbench folder, run the project tests. The extension checks run inside them and need Node and Chrome. They skip themselves if either is missing.

```bash
.venv/bin/python -m pytest -q tests/test_clio_filler.py
```

```powershell
.venv\Scripts\python.exe -m pytest -q tests\test_clio_filler.py
```

The tests run the filler against two stand-in Clio pages built from the app's own form data, one with native inputs and one with custom buttons and a drop-down. They have not been run against the real Clio. Try a fake matter first.
