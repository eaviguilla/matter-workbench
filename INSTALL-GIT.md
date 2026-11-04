# Matter Workbench, install with git

This guide is for installing from GitHub on a fresh macOS or Windows computer, and for updating that copy later.
If you were sent a zip file instead, use `INSTALL-ZIP.md`.

Matter Workbench runs only on this computer. Installing takes about 15 minutes. The first run downloads the
libraries and the name model, about 600 MB in total.

## Before you start

1. A computer with macOS or Windows, about 2 GB of free disk space and an internet connection.
2. Python 3.13. Python 3.12 also works. Python 3.11 is the oldest that runs the app.
3. Git. The Download ZIP option below works without it, but updating is easier with git.
4. A short folder that is not synced. Do not use OneDrive, iCloud Drive, Dropbox, Desktop or Documents.

### Python

macOS. Open Terminal (press Cmd+Space, type Terminal, press Return) and run this.

```bash
python3 --version
```

Windows. Open PowerShell (press the Windows key, type PowerShell, press Return) and run this.

```powershell
py --version
```

If the number is 3.11 or higher, go on. Otherwise install Python.

1. Go to https://www.python.org/downloads/ and download Python 3.13 for your system.
2. Run the installer. On Windows, tick "Add python.exe to PATH" on the first screen, then choose Install Now.
3. Close the window, open a new one, and run the version command again.

On Windows, typing `python` may open the Microsoft Store. Always type `py` instead.

### Git

macOS. Run `git --version` in Terminal. If git is missing, macOS offers to install the command line tools. Accept,
wait for it to finish, and run the command again.

Windows. Download Git for Windows from https://git-scm.com/download/win and install it with the default choices.
Open a new PowerShell window afterwards.

## Install

### macOS

```bash
git clone https://github.com/eaviguilla/matter-workbench.git ~/matter-workbench
cd ~/matter-workbench
python3 run.py
```

### Windows

```powershell
git clone https://github.com/eaviguilla/matter-workbench.git C:\matter-workbench
cd C:\matter-workbench
py run.py
```

### Without git

1. Open https://github.com/eaviguilla/matter-workbench, choose Code, then Download ZIP.
2. Unzip it. GitHub names the folder `matter-workbench-main`. Move the folder that holds `run.py` to `~/matter-workbench`
   on a Mac or `C:\matter-workbench` on Windows. Windows may make a folder inside a folder, so open them until you
   find `run.py`.
3. Run `python3 run.py` on a Mac or `py run.py` on Windows from that folder.

Updating then means downloading and unzipping a fresh copy into a new folder, as for the zip install.

## What happens on the first run

1. The window prints "Installing Matter Workbench". It builds a private environment in the folder and installs
   the libraries from the internet. This takes a few minutes.
2. The name model is not stored in git. `run.py` downloads it once, about 570 MB, from the GitHub release named in
   `models/MODEL-SHA256.txt`, and shows its progress. It checks every file against its checksum before using it.
   A download that stops continues where it stopped the next time you run it.
3. Your web browser opens on http://127.0.0.1:8765 and shows Matter Workbench. Leave the window open while you use
   the app.

## Every day after that

Run the last line again, `python3 run.py` on a Mac or `py run.py` on Windows, from the app folder. It checks what is
installed first. If everything is in place, it installs and downloads nothing and the app starts in seconds. If the
app is already running, it only opens the page again.

To stop the app, click its window and press Ctrl+C.

## Updating

1. Open Terminal or PowerShell in the app folder.
2. Run `git pull`.
3. Run `run.py` again. It installs only what changed. New libraries are installed into the existing environment,
   and the name model is downloaded again only when a new model has been released.

If `git pull` says it cannot continue because files were changed on this computer, ask the owner of the project.
Do not edit files in the app folder.

Your saved clients are stored outside this folder, so updating never touches them.

## Where your data is stored

1. macOS, `~/Library/Application Support/MatterWorkbench.noindex`.
2. Windows, `%LOCALAPPDATA%\MatterWorkbench`.

Real names, emails and addresses are stored there as plain text. Keep disk encryption on, which is FileVault on a
Mac and BitLocker on Windows. A new computer starts with no clients.

## If something goes wrong

1. "Python 3.11 or newer is needed". Install Python as above and run again. On a Mac with several versions, use
   `python3.13 run.py`. On Windows, use `py -3.13 run.py`.
2. pip says no matching distribution exists. Install Python 3.13 and run again.
3. The page shows "The name model is not installed". The download did not finish. Connect to the internet and run
   `run.py` again. It continues where it stopped. The app still opens, but scrubbing stays blocked until then.
4. "The name model release is not on GitHub". Tell the owner of the project. The model has not been uploaded yet.
5. A proxy or firewall blocks the download. Ask IT to allow downloads from github.com, or ask for the zip install.
6. A certificate error on a Mac. In Finder open `/Applications/Python 3.13` and double-click
   `Install Certificates.command`, then run again.
7. "address already in use", or the page does not open. Another copy is running. Close its window, or add
   `--port 9000` to the run command.
8. A very long folder path on Windows makes the install fail. Use `C:\matter-workbench`.

## Options

```text
run.py --port 9000      use another port, the default is 8765
run.py --no-browser     do not open the page automatically
run.py --reinstall      delete the private environment and install again
run.py --install-only   install everything, then stop
```
