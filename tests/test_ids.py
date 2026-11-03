from datetime import date

import pytest

from app.ids import find_header, header_line, make_client_id, make_transcript_id


def test_client_id_counter_breaks_same_name_same_day():
    d = date(2026, 11, 2)
    first = make_client_id("maria", d)
    assert first == "Maria-20261102-1"
    assert make_client_id("Maria", d, [first]) == "Maria-20261102-2"
    assert make_client_id("Maria", date(2026, 11, 3), [first]) == "Maria-20261103-1"


def test_transcript_id_counts_per_day():
    d = date(2026, 11, 2)
    assert make_transcript_id(d) == "TX-20261102-1"
    assert make_transcript_id(d, ["TX-20261102-1", "TX-20261102-2"]) == "TX-20261102-3"


def test_header_roundtrip_and_rejects_bad_ids():
    h = header_line("Maria-20261102-1", "TX-20261102-1")
    assert h == "[CLIENT: Maria-20261102-1 | TX: TX-20261102-1]"
    m = find_header("noise\n" + h + "\nbody")
    assert (m["client"], m["tx"]) == ("Maria-20261102-1", "TX-20261102-1")
    assert find_header("[CLIENT: nope | TX: TX-1]") is None
    with pytest.raises(ValueError):
        header_line("bad", "TX-20261102-1")
