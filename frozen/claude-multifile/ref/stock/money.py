"""金額（セント単位の整数）と文字列の相互変換。"""

import re

_AMOUNT_RE = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")


def parse_cents(text):
    """"12.50" のような金額の文字列をセントの整数にする。書式が違えば ValueError。"""
    if not isinstance(text, str) or _AMOUNT_RE.fullmatch(text) is None:
        raise ValueError(f"bad amount: {text!r}")
    whole, _, frac = text.partition(".")
    return int(whole) * 100 + int(frac.ljust(2, "0"))


def format_cents(cents):
    """セントの整数を "1234.56" の形の文字列にする。"""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}{whole}.{frac:02d}"
