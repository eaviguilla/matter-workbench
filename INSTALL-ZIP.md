# Matter Workbench, install from the zip

This guide is for a computer that received the Matter Workbench zip file. It works on macOS and Windows.
Matter Workbench runs only on this computer. It hides names, emails and addresses in call transcripts before you
paste them into claude.ai, and puts the real values back in Claude's replies.

The zip holds the app and the name model. It holds no client records or transcripts. Installing takes about
10 minutes, and most of that is the first run downloading the libraries.

## Before you start

1. A computer with macOS or Windows, about 2 GB of free disk space and an internet connection for the first run.
2. Python 3.13. Python 3.12 also works. Python 3.11 is the oldest that runs the app.
3. A short folder that is not synced. Do not use OneDrive, iCloud Drive, Dropbox, Desktop or Documents.

### Check for Python

macOS. Open Terminal (press Cmd+Space, type Terminal, press Return) and run this.

```bash
python3 --version
```

Windows. Open PowerShell (press the Windows key, type PowerShell, press Return) and run this.

```powershell
py --version
```

If the number is 3.11 or higher, go on. If you see an older number, or a message that the command is not found,
install Python.

1. Go to https://www.python.org/downloads/ and download Python 3.13 for your system.
2. Run the installer. On Windows, tick "Add python.exe to PATH" on the first screen, then choose Install Now.
3. Close the Terminal or PowerShell window and open a new one, then run the version command again.

On Windows, typing `python` may open the Microsoft Store. Always type `py` instead.

## Install

### macOS

1. Double-click the zip to unzip it. Move the folder that holds `run.py`, named `matter-workbench`, into your
   home folder, so its path is `~/matter-workbench`.
2. Open Terminal and run these two lines.

```bash
cd ~/matter-workbench
python3 run.py
```

### Windows

1. Right-click the zip and choose Extract All, then Extract. Windows may make a folder inside a folder. Open them
   until you find the folder that holds `run.py`, named `matter-workbench`. Move that folder to `C:\`, so its path is
   `C:\matter-workbench`.
2. Open PowerShell and run these two lines.

```powershell
cd C:\matter-workbench
py run.py
```

If Windows Defender or SmartScreen asks about the file, choose "More info" and then "Run anyway".

## What happens on the first run

1. The window prints "Installing Matter Workbench". It builds a private environment inside the folder and installs
   the libraries from the internet. This takes a few minutes. Wait for it.
2. It checks the name model that came in the zip. Nothing is downloaded for the model.
3. Your web browser opens on http://127.0.0.1:8765 and shows Matter Workbench. Leave the Terminal or PowerShell
   window open while you use the app.

## Every day after that

Run the same two lines. The app starts in seconds because everything is already installed. `run.py` checks what
is installed first, and installs nothing if all of it is in place. If the app is already running, running the
lines again only opens the page again.

To stop the app, click the Terminal or PowerShell window and press Ctrl+C.

## Updating

1. Unzip the new zip into a new folder next to the old one. Do not unzip over the old folder.
2. Run `run.py` from the new folder as above. It sets itself up again.
3. When the new one works, delete the old folder.

Your saved clients are not in this folder, so updating never touches them. They stay on this computer.

## Where your data is stored

Saved clients and transcripts are stored outside the app folder.

1. macOS, `~/Library/Application Support/MatterWorkbench.noindex`.
2. Windows, `%LOCALAPPDATA%\MatterWorkbench`.

Real names, emails and addresses are stored there as plain text. Keep disk encryption on, which is FileVault on a
Mac and BitLocker on Windows. A new computer starts with no clients, and copying the app folder never copies them.

## Removing

Delete the app folder. To remove the saved data too, delete the data folder above. Do that only after you have
exported anything you still need, because it cannot be recovered afterwards.

## If something goes wrong

1. "Python 3.11 or newer is needed". Install Python as described above, then run the command again. On a Mac with
   several versions, use `python3.13 run.py`. On Windows, use `py -3.13 run.py`.
2. pip says no matching distribution exists. Your Python is too new or too old for one of the libraries. Install
   Python 3.13 and run again.
3. The first run stops with a message about the internet. Connect, then run the same command. It continues.
4. The page shows "The name model is not installed". The zip's model files are missing or damaged. Run the same
   command again while online. It downloads the model once and checks it.
5. "Name model" with a certificate error on a Mac. Open the folder `/Applications/Python 3.13` in Finder and
   double-click `Install Certificates.command`, then run again.
6. "address already in use", or the page does not open. Another copy is running. Close its window, or use
   `python3 run.py --port 9000` on a Mac or `py run.py --port 9000` on Windows.
7. Windows, the folder path is very long and the install fails. Move the app folder to `C:\matter-workbench`.

To report a problem, run this from the app folder. The report holds no stored values.

```bash
.venv/bin/python -m app.check
```

```powershell
.venv\Scripts\python -m app.check
```

## Options

```text
run.py --port 9000      use another port, the default is 8765
run.py --no-browser     do not open the page automatically
run.py --reinstall      delete the private environment and install again
run.py --install-only   install everything, then stop
```
