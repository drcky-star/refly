"""Kaydı tamamla / temizle — eksik alanları CrossRef + PubMed'den doldurur.

Yalnızca BOŞ alanlar doldurulur; mevcut veriler asla ezilmez. DOI yoksa başlıkla
CrossRef'te güçlü eşleşme aranır (yanlış eşleşmeyi önlemek için yüksek benzerlik şartı).
"""
from __future__ import annotations
from difflib import SequenceMatcher

from . import crossref

# Bir kaydın "tamamlanmaya değer" sayılması için bakılan alanlar
_KEY_FIELDS = ("doi", "year", "journal", "volume", "pages")
# Doldurulabilecek tüm alanlar (boşsa)
_FILLABLE = ("doi", "pmid", "year", "journal", "iso", "volume", "issue", "pages",
             "authors", "abstract", "publisher", "url", "type")


def _norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum() or c == " ").strip()


def missing_fields(rec: dict) -> list[str]:
    miss = [f for f in _KEY_FIELDS if not rec.get(f)]
    if not rec.get("authors"):
        miss.append("authors")
    return miss


def needs_enrichment(rec: dict) -> bool:
    return bool(missing_fields(rec))


def _empty(rec: dict, field: str) -> bool:
    v = rec.get(field)
    return v in (None, "", [], 0)


def enrich(rec: dict, pm, email: str = "") -> dict:
    """Tek kayıt için doldurulacak alanları döner ({} = değişiklik yok)."""
    src = None
    # 1) Kaynak kaydı bul: DOI > PMID > başlık eşleşmesi
    if rec.get("doi"):
        src = crossref.fetch_doi(rec["doi"], email)
    elif rec.get("pmid"):
        recs = pm.fetch([rec["pmid"]])
        src = recs[0] if recs else None
    elif rec.get("title"):
        rt = _norm(rec["title"])
        best = None
        for cand in crossref.search_title(rec["title"], email, rows=3):
            ratio = SequenceMatcher(None, rt, _norm(cand.get("title", ""))).ratio()
            if best is None or ratio > best[0]:
                best = (ratio, cand)
        if best and best[0] >= 0.90:
            src = best[1]   # güçlü eşleşme

    if not src:
        return {}

    filled = {}
    for f in _FILLABLE:
        if _empty(rec, f) and not _empty(src, f):
            filled[f] = src[f]
    return filled
