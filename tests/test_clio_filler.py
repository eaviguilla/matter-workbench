"""The Copy for Clio text, the generated form data of the Chrome extension, and the extension itself in headless Chrome."""
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app import workflow as wf
from scripts import build_clio_forms

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "clio_filler"
PROGRAM_DIRS = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
CHROME = next((p for p in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", shutil.which("google-chrome"),
                           shutil.which("chromium"), shutil.which("chrome"), shutil.which("chrome.exe"),
                           *[str(Path(d) / "Google/Chrome/Application/chrome.exe") for d in PROGRAM_DIRS if d]]
               if p and Path(p).exists()), None)


def row(n, q, text, state="answered", fold=False):
    return dict(n=n, question=q, text=text, state=state, fold=fold)


def test_clio_text_has_the_header_one_block_per_answer_and_an_end_line():
    rows = [row(1, "Name?", "Maria Lopez"), row(2, "Date?", "09/14/2026")]
    lines = wf.clio_text("probate-intake-form", rows, "Nadia", "2026-09-14", 3).split("\n")
    assert lines[:6] == [wf.CLIO_FORMAT, "Form: probate-intake-form", "Client: Nadia", "Call: 2026-09-14", "Version: 3",
                         f"Copied: {wf.COPIED_STAMP}"]
    assert lines[6:] == ["--- 1. Name?", "Maria Lopez", "--- 2. Date?", "09/14/2026", "--- End of answers"]


def test_clio_text_leaves_out_empty_not_discussed_and_folded_entries():
    rows = [row(1, "A?", "yes"), row(2, "B?", "", state="empty"), row(3, "C?", "Not discussed", state="not_discussed"),
            row(4, "D?", "x", fold=True)]
    text = wf.clio_text("f", rows, "N", "d", 1)
    assert "--- 1. A?" in text
    assert not any(f"--- {n}." in text for n in (2, 3, 4))


def test_clio_text_keeps_an_answer_from_looking_like_a_block_start():
    text = wf.clio_text("f", [row(1, "List?", "--- 9. fake\nsecond line")], "N", "d", 1)
    assert [l for l in text.split("\n") if l.startswith("---")] == ["--- 1. List?", "--- End of answers"]


def test_clio_text_flattens_line_breaks_in_the_header_and_question():
    text = wf.clio_text("f", [row(1, "Two\nlines?", "a")], "Na\ndia", "d", 1)
    assert "Client: Na dia" in text and "--- 1. Two lines?" in text


def test_generated_form_data_matches_the_forms_schema():
    assert (EXT / "forms-data.js").read_text(encoding="utf-8") == build_clio_forms.render(), \
        "run: .venv/bin/python scripts/build_clio_forms.py"


def test_manifest_asks_for_no_more_than_the_filler_needs():
    m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert m["manifest_version"] == 3
    assert set(m["permissions"]) <= {"activeTab", "scripting", "clipboardRead", "clipboardWrite"}
    assert not m.get("host_permissions") and not m.get("content_scripts") and not m.get("background")


FORBIDDEN = [r"\bfetch\s*\(", r"XMLHttpRequest", r"WebSocket", r"sendBeacon", r"\bconsole\.", r"\.submit\s*\(",
             r"requestSubmit", r"\beval\s*\(", r"new Function", r"location\s*(\.|=)", r"importScripts", r"document\.cookie",
             r"localStorage", r"chrome\.tabs\.(update|create)", r"window\.open"]


@pytest.mark.parametrize("name", ["fill.js", "parse.js", "popup.js"])
def test_extension_scripts_do_not_reach_the_network_or_submit_anything(name):
    src = (EXT / name).read_text(encoding="utf-8")
    src = re.sub(r"//[^\n]*", "", src)
    for pattern in FORBIDDEN:
        assert not re.search(pattern, src), f"{name} matches {pattern}"


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_parse_and_matching_unit_tests_pass():
    tests = sorted((EXT / "tests").glob("*.test.js"))
    assert tests
    r = subprocess.run(["node", "--test", *map(str, tests)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_the_extension_reads_what_the_app_copies():
    rows = [row(1, "Name?", "Maria Lopez"), row(2, "Notes?", "one\n--- 9. two\n----\nthree"), row(3, "Gone?", "", state="empty")]
    text = wf.clio_text("probate-intake-form", rows, "Nadia", "2026-09-14", 3).replace(wf.COPIED_STAMP, "2026-11-05T14:02:11.000Z")
    code = "const {parse}=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>console.log(JSON.stringify(parse(s))))"
    r = subprocess.run(["node", "-e", code, str(EXT / "parse.js")], input=text, capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout)
    assert got["ok"] and got["form"] == "probate-intake-form" and got["version"] == "3"
    assert [(a["n"], a["text"]) for a in got["answers"]] == [(1, "Maria Lopez"), (2, "one\n--- 9. two\n----\nthree")]


def run_harness(tmp_path):
    out = tmp_path / "dom.html"
    with out.open("w", encoding="utf-8") as fh:
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
                        "--virtual-time-budget=600000", "--dump-dom", (EXT / "tests" / "harness.html").as_uri()],
                       stdout=fh, stderr=subprocess.DEVNULL, timeout=240)
    dom = out.read_text(encoding="utf-8")
    assert "<title>done</title>" in dom, "the harness did not finish"
    return json.loads(html.unescape(re.search(r'<pre id="out">(.*?)</pre>', dom, re.S).group(1)))


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    if not CHROME:
        pytest.skip("Chrome is not installed")
    return run_harness(tmp_path_factory.mktemp("harness"))


def mismatches(r):
    return [n for n, v in r["want"].items() if r["back"].get(n, "") != v]


def test_every_form_fills_completely_in_both_mock_layouts(report):
    basics = [r for r in report if r["name"] == "basic"]
    assert len(basics) == 8
    for r in basics:
        assert mismatches(r) == [], (r["slug"], r["layout"])
        assert {x["status"] for x in r["run"]["results"]} == {"filled"}, (r["slug"], r["layout"])
        assert r["submitted"] == 0


def test_an_answer_already_in_clio_is_left_alone(report):
    r = next(r for r in report if r["name"] == "already")
    status = {x["n"]: x["status"] for x in r["run"]["results"]}
    assert status[1] == "already" and status[7] == "already"
    assert r["back"]["1"] == "keep me"


def test_a_too_long_answer_or_a_non_date_is_flagged_and_left_blank(report):
    r = next(r for r in report if r["name"] == "limits")
    status = {x["n"]: x["status"] for x in r["run"]["results"]}
    assert status[1] == "flag" and status[5] == "flag"
    assert r["back"]["1"] == "" and r["back"]["5"] == ""


def test_a_follow_up_whose_parent_has_no_answer_is_reported_missing(report):
    r = next(r for r in report if r["name"] == "orphan")
    assert r["run"]["results"] == [{"n": 8, "status": "missing", "note": "Clio did not show this follow-up."}]


def test_a_page_that_is_not_the_form_is_refused(report):
    r = next(r for r in report if r["name"] == "wrongpage")
    assert r["run"]["ok"] is False and r["run"]["results"] == []


def test_the_layout_copy_holds_titles_and_no_typed_values(report):
    s = next(r for r in report if r["name"] == "structure-html")["html"]
    assert "What was the name of your loved one?" in s and "<script" not in s and "<style" not in s
    assert "TYPED-VALUE" not in s and "Sample answer" not in s and " checked" not in s and "aria-checked" not in s and 'id="note"' in s

