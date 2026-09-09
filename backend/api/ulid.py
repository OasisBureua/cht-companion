"""Minimal ULID generation — SCRUM-195 §7.1 (time-sortable request IDs).

No external dependency: a ULID is a 48-bit millisecond timestamp followed by
80 bits of randomness, Crockford base32-encoded to 26 characters. Lexicographic
sort order on the string matches chronological order, which is the property
SCRUM-195 §7.1 needs for log correlation — a plain UUID4 doesn't have this.
"""

from __future__ import annotations

import os
import time

_CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    timestamp_ms = int(time.time() * 1000)
    randomness = os.urandom(10)  # 80 bits

    # 48-bit timestamp -> 6 bytes, then 10 bytes of randomness = 128 bits total.
    ts_bytes = timestamp_ms.to_bytes(6, byteorder="big")
    value = int.from_bytes(ts_bytes + randomness, byteorder="big")

    chars = []
    for _ in range(26):
        value, remainder = divmod(value, 32)
        chars.append(_CROCKFORD_ALPHABET[remainder])
    return "".join(reversed(chars))
