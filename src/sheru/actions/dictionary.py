"""Local word definitions via macOS's built-in Dictionary (the same one behind trackpad force-press 'Look Up').
Fully offline, instant, no LLM guessing. Returns a clean SPOKEN definition (IPA phonetics stripped so the TTS
doesn't choke), or None so the caller can fall back to search/Claude for words the dictionary doesn't have.
"""
from __future__ import annotations

import re

_DCS = None      # cached DCSCopyTextDefinition function


def _dcs():
    global _DCS
    if _DCS is None:
        try:
            import objc
            from Foundation import NSBundle
            b = NSBundle.bundleWithPath_(
                "/System/Library/Frameworks/CoreServices.framework/Frameworks/DictionaryServices.framework")
            g = {}
            objc.loadBundleFunctions(b, g, [("DCSCopyTextDefinition", b"@@@{_CFRange=qq}")])
            _DCS = g.get("DCSCopyTextDefinition") or False
        except Exception:
            _DCS = False
    return _DCS or None


_POS = r"noun|verb|adjective|adverb|pronoun|preposition|conjunction|exclamation|abbreviation"


def _clean(entry: str, word: str) -> str | None:
    """Flattened entry ('word | IPA | pos [labels] sense1: example | sense2 … ORIGIN …') -> a clean spoken
    first definition ('noun. the meaning'). Anchors on the part-of-speech to skip the headword + IPA."""
    m = re.search(r"\b(" + _POS + r")\b", entry, re.I)         # definition starts at the first part-of-speech
    body = entry[m.start():] if m else entry
    body = re.split(r"\bORIGIN\b", body)[0]                    # drop etymology
    body = re.sub(r"\([^)]*\)", " ", body)                     # drop inflections/parentheticals ('(runs)', '(past; ran)')
    body = re.sub(r"\[[^\]]*\]", " ", body)                    # drop grammar labels ('[mass noun]')
    pos_m = re.match(r"\s*(" + _POS + r")\b", body, re.I)
    pos = pos_m.group(1).lower() if pos_m else ""
    rest = body[pos_m.end():] if pos_m else body
    rest = re.sub(r"^\s*\d+\s*", "", rest)                     # drop a leading sense number ('1 …')
    rest = rest.split(":")[0]                                  # drop the usage example after the first ':'
    rest = re.sub(r"\s+", " ", rest).strip(" .;,|•")
    if len(rest) > 220:                                        # keep it spoken-length; cut at a word boundary
        rest = rest[:220].rsplit(" ", 1)[0] + "…"
    if not rest:
        return None
    return f"{pos}. {rest}" if pos else rest


def define(word: str) -> str | None:
    """A short spoken definition of `word`, or None if the dictionary has no entry."""
    word = (word or "").strip().strip("?.!,'\"").strip()
    if not word or len(word) > 40:
        return None
    fn = _dcs()
    if fn is None:
        return None
    try:
        d = fn(None, word, (0, len(word)))
    except Exception:
        return None
    if not d:
        return None
    out = _clean(str(d), word)
    return out or None
