import pytest
from app.scrub.parse import TranscriptFormatError, parse_transcript
from app.scrub.pipeline import scrub_transcript
from app.scrub.registry import Registry

GOOD = "• Maria Lopez 0:05\nHello there.\n• Sam Whitaker 0:12\nHi Maria.\n"


def test_same_line_timestamp():
    p = parse_transcript(GOOD)
    assert not p.issues
    assert [t.speaker for t in p.turns] == ["Maria Lopez", "Sam Whitaker"]
    assert p.turns[0].timestamp == "0:05"
    s, e = p.turns[0].speaker_span
    assert GOOD[s:e] == "Maria Lopez"
    b0, b1 = p.turns[0].body_span
    assert GOOD[b0:b1] == "Hello there.\n"


def test_timestamp_on_next_line_and_blank_lines():
    p = parse_transcript("• Maria Lopez\n0:05\n\nHello.\n\n• Sam\n0:09\nHi.\n")
    assert not p.issues
    assert [t.timestamp for t in p.turns] == ["0:05", "0:09"]


def test_crlf_offsets_stay_valid():
    text = GOOD.replace("\n", "\r\n")
    p = parse_transcript(text)
    s, e = p.turns[1].speaker_span
    assert text[s:e] == "Sam Whitaker"


def test_missing_timestamp_is_flagged_not_guessed():
    p = parse_transcript("• Maria Lopez\nHello there.\n")
    assert [i.message for i in p.issues] == ["missing timestamp"]


def test_text_before_first_bullet_is_flagged():
    p = parse_transcript("Intro line\n• Maria Lopez 0:05\nHello.\n")
    assert any("before the first speaker" in i.message for i in p.issues)


def test_bad_speaker_name_and_empty_input():
    assert parse_transcript("• 12345 0:05\nHi.\n").issues
    assert parse_transcript("").issues


def test_scrub_reads_any_layout_as_plain_text_and_says_so():
    res = scrub_transcript("just a paragraph about Tomas Beltran, who lives at 418 Alder Street, Tacoma, WA 98402. "
                           "Reach him at tomas@example.com.", Registry())
    assert "tomas@example.com" not in res.text and "98402" not in res.text
    assert any("No speaker lines" in n for n in res.notes)


def test_scrub_refuses_only_an_empty_paste():
    with pytest.raises(TranscriptFormatError):
        scrub_transcript("   \n", Registry())


def test_a_long_run_of_dashes_or_dots_after_a_capital_letter_does_not_stall_the_speaker_regexes():
    import time
    from app.scrub import parse
    for line in ("A" + "-" * 200_000 + "!", "A" + "." * 200_000 + "!", "Name " + "-" * 200_000 + " x"):
        start = time.perf_counter()
        for rx in (parse._TS_FIRST, parse._NAME_TS, parse._COLON):
            rx.match(line)
        assert time.perf_counter() - start < 3
