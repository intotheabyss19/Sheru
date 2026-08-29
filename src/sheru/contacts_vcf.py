"""Import contacts from a .vcf (vCard) file into Sheru's contact book — e.g. the contacts.vcf you send
yourself on WhatsApp. Run: uv run sheru import-vcf   (defaults to data/contacts.vcf, or --text <path>)."""
from __future__ import annotations

import re
from pathlib import Path

from .actions import contacts_book


def import_vcf(path: str | None = None) -> int:
    from . import config
    p = Path(path) if path else Path(config.DATA_DIR) / "contacts.vcf"
    if not p.exists():
        print(f"No vCard at {p}. Send yourself contacts.vcf on WhatsApp, then run again."); return 1
    text = p.read_text(errors="ignore")
    n = skipped = 0
    for card in text.split("END:VCARD"):
        fn = re.search(r"(?mi)^FN[^:\n]*:(.+)$", card)
        tel = re.search(r"(?mi)^TEL[^:\n]*:\s*([+\d][\d\s\-()]{5,})", card)
        if fn and tel and fn.group(1).strip():
            contacts_book.add(fn.group(1).strip(), tel.group(1).strip())
            n += 1
        else:
            skipped += 1
    print(f"Imported {n} contacts into Sheru's book (skipped {skipped} without a name+number).")
    return 0
