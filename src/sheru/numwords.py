"""Spoken number words -> digits, so voice input like 'five plus five', 'convert hundred dollars', and
'set volume to twenty' works. Whisper emits number WORDS constantly for spoken numbers, so calc / FX / volume
all preprocess through replace_number_words(). Handles 0-999,999 incl. compounds ('twenty five'=25,
'one hundred fifty'=150, 'two thousand'=2000). Leaves everything else untouched.
"""
from __future__ import annotations

import re

_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
         "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000}
_ALL = set(_UNITS) | set(_TENS) | set(_SCALES) | {"and"}
_TOKEN = re.compile(r"[a-z]+|\d+")


def _run_value(words: list[str]) -> int | None:
    """Fold a run of number words into an integer using the standard hundreds/thousands accumulator."""
    total = current = 0
    seen = False
    for w in words:
        if w == "and":
            continue
        if w in _UNITS:
            current += _UNITS[w]; seen = True
        elif w in _TENS:
            current += _TENS[w]; seen = True
        elif w == "hundred":
            current = (current or 1) * 100; seen = True
        elif w == "thousand":
            total += (current or 1) * 1000; current = 0; seen = True
        else:
            return None
    return total + current if seen else None


def replace_number_words(text: str) -> str:
    """Replace maximal runs of spoken number words with their digit value. 'five plus five' -> '5 plus 5'."""
    toks = _TOKEN.findall(text.lower())
    if not any(t in _ALL and t != "and" for t in toks):
        return text
    out, i = [], 0
    while i < len(toks):
        if toks[i] in _ALL and toks[i] != "and":
            j = i
            while j < len(toks) and toks[j] in _ALL:
                j += 1
            while j - 1 > i and toks[j - 1] == "and":       # don't swallow a trailing 'and'
                j -= 1
            val = _run_value(toks[i:j])
            if val is not None:
                out.append(str(val)); i = j; continue
        out.append(toks[i]); i += 1
    return " ".join(out)
