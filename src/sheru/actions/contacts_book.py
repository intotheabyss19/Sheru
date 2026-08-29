"""Sheru's own contact book: name -> WhatsApp number, independent of macOS Contacts.

Seeded on demand — when a name is unknown, Sheru asks for the number once and stores it here, so future
sends never touch macOS Contacts. Stored in gitignored data/contacts.json (personal).
"""
from __future__ import annotations

import json
import re

from .. import config


def _path():
    return config.DATA_DIR / "contacts.json"


def _load() -> dict:
    try:
        return json.loads(_path().read_text())
    except Exception:
        return {}


def _save(d: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(d, indent=2, ensure_ascii=False))


def add(name: str, number: str) -> dict:
    """Store name -> number. Returns a contact dict ({name, kind, handle})."""
    digits = re.sub(r"[^\d+]", "", number)
    d = _load()
    d[name.strip().lower()] = {"name": name.strip(), "handle": digits}
    _save(d)
    return {"name": name.strip(), "kind": "phone", "handle": digits}


def get(name: str) -> dict | None:
    """Look up a stored contact: exact key first, then fuzzy over stored names (STT-tolerant)."""
    d = _load()
    if not d:
        return None
    key = name.strip().lower()
    if key in d:
        e = d[key]
        return {"name": e["name"], "kind": "phone", "handle": e.get("handle"), "address": e.get("address")}
    from rapidfuzz import fuzz
    best, score = None, 0.0
    for k, e in d.items():
        s = max([fuzz.ratio(key, k)] + [fuzz.ratio(key, tok) for tok in k.split()])
        if s > score:
            best, score = e, s
    if best and score >= 82:
        return {"name": best["name"], "kind": "phone", "handle": best.get("handle"), "address": best.get("address")}
    return None


def set_address(name: str, address: str) -> str:
    """Remember how to ADDRESS a contact in messages — e.g. saved as 'Crocodile' but addressed as 'Madam' — so a
    private nickname is never sent as their real name. Attaches to the matched contact, or an address-only stub."""
    d = _load()
    key = name.strip().lower()
    e = d.get(key)
    if e is None:
        hit = get(name)                       # attach to the best fuzzy match if there is one
        if hit and hit.get("name"):
            key = hit["name"].strip().lower()
            e = d.get(key) or {"name": hit["name"], "handle": hit.get("handle")}
        else:
            e = {"name": name.strip()}
    e["address"] = address.strip()
    d[key] = e
    _save(d)
    return e["address"]


def address_for(name: str) -> str:
    """The greeting term for a contact: the stored address override if set, else what the user called them
    (unchanged behaviour when no override exists — so only deliberately-set addresses alter a greeting)."""
    c = get(name)
    if c and c.get("address"):
        return c["address"]
    return name.strip()
