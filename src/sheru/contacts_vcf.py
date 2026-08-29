"""Import contacts from a .vcf (vCard) file into Sheru's contact book — e.g. the contacts.vcf you send
yourself on WhatsApp. Run: uv run sheru import-vcf   (defaults to data/contacts.vcf, or --text <path>)."""
from __future__ import annotations

import quopri
import re
from pathlib import Path

from .actions import contacts_book


def _field(card: str, name: str) -> str | None:
    """Value of a vCard field, decoding ENCODING=QUOTED-PRINTABLE (+ its '='-terminated soft line-wraps) so a
    name like 'Crocodile 🐊' isn't stored as '=43=72=6F...'."""
    lines = card.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(rf"(?i)^{name}([^:]*):(.*)$", ln)
        if not m:
            continue
        params, val = m.group(1), m.group(2)
        if "quoted-printable" in params.lower():
            while val.endswith("=") and i + 1 < len(lines):     # join soft-wrapped continuation lines
                i += 1
                val = val[:-1] + lines[i]
            try:
                val = quopri.decodestring(val.encode()).decode("utf-8", "replace")
            except Exception:
                pass
        return val.strip()
    return None


def import_vcf(path: str | None = None) -> int:
    from . import config
    p = Path(path) if path else Path(config.DATA_DIR) / "contacts.vcf"
    if not p.exists():
        print(f"No vCard at {p}. Send yourself contacts.vcf on WhatsApp, then run again."); return 1
    text = p.read_text(errors="ignore")
    n = skipped = 0
    for card in text.split("END:VCARD"):
        fn = _field(card, "FN")
        tel = re.search(r"(?mi)^TEL[^:\n]*:\s*([+\d][\d\s\-()]{5,})", card)
        if fn and tel:
            contacts_book.add(fn, tel.group(1).strip())
            n += 1
        else:
            skipped += 1
    print(f"Imported {n} contacts into Sheru's book (skipped {skipped} without a name+number).")
    return 0
