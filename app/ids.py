"""Client IDs, transcript IDs and the header line that ties a message to both."""
import re
import unicodedata
from collections.abc import Iterable
from datetime import date

CLIENT_ID_RE = re.compile(r"^[^\W\d_]+-\d{8}-\d+\Z")
TX_ID_RE = re.compile(r"^TX-\d{8}-\d+\Z")
MAX_NAME_IN_ID = 40      # IDs are folder names, and paths have a length limit
HEADER_RE = re.compile(r"\[CLIENT:[ ]*(?P<client>[^\s|\]]+)[ ]*\|[ ]*TX:[ ]*(?P<tx>[^\s|\]]+)[ ]*\]")


def _next_n(prefix: str, existing: Iterable[str]) -> int:
    # Compared without case, because macOS and Windows disks treat Tomas and TOMAS as the same folder.
    prefix = prefix.casefold()
    taken = [int(e[len(prefix):]) for e in map(str.casefold, existing) if e.startswith(prefix) and e[len(prefix):].isdigit()]
    return max(taken, default=0) + 1


def make_client_id(first_name: str, added: date, existing: Iterable[str] = ()) -> str:
    letters = "".join(ch for ch in unicodedata.normalize("NFC", first_name) if ch.isalpha())[:MAX_NAME_IN_ID]
    if not letters:
        raise ValueError("first name has no letters")
    prefix = f"{letters[:1].upper()}{letters[1:]}-{added:%Y%m%d}-"
    return f"{prefix}{_next_n(prefix, existing)}"


def make_transcript_id(call_date: date, existing: Iterable[str] = ()) -> str:
    prefix = f"TX-{call_date:%Y%m%d}-"
    return f"{prefix}{_next_n(prefix, existing)}"


def header_line(client_id: str, tx_id: str) -> str:
    if not CLIENT_ID_RE.match(client_id) or not TX_ID_RE.match(tx_id):
        raise ValueError("malformed client or transcript ID")
    return f"[CLIENT: {client_id} | TX: {tx_id}]"


def find_header(text: str):
    """Return the first valid header match in text, or None. Never guesses."""
    for m in HEADER_RE.finditer(text):
        if CLIENT_ID_RE.match(m["client"]) and TX_ID_RE.match(m["tx"]):
            return m
    return None
