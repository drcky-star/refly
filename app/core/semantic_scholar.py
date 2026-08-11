"""Semantic Scholar Graph API ile referans arama — sorgu -> kanonik kayıt listesi."""
from __future__ import annotations
import os
import re
import time
import requests

_API = "https://api.semanticscholar.org/graph/v1/paper/search"
_GRAPH = "https://api.semanticscholar.org/graph/v1/paper"
_FIELDS = "title,abstract,year,authors,venue,journal,externalIds"


def snowball(doi: str = "", pmid: str = "", limit: int = 25) -> dict:
    """Atıf-ağı ile ilgili makale keşfi (snowball):
      references = bu makalenin ATIF YAPTIĞI (kaynakça) makaleler,
      citations  = bu makaleye ATIF VEREN (sonraki) makaleler.
    DOI ya da PMID gerektirir; hata/429 → boş listeler."""
    pid = f"DOI:{doi}" if doi else (f"PMID:{pmid}" if pmid else "")
    out = {"references": [], "citations": []}
    if not pid:
        return out
    for kind, sub, inner in (("references", "references", "citedPaper"),
                             ("citations", "citations", "citingPaper")):
        try:
            r = requests.get(f"{_GRAPH}/{pid}/{sub}", headers=_headers(),
                             params={"fields": _FIELDS, "limit": limit}, timeout=20)
            if r.status_code != 200:
                continue
            recs = []
            for it in (r.json().get("data") or []):
                p = (it or {}).get(inner) or {}
                if p.get("title"):
                    recs.append(_map(p))
            out[kind] = recs
        except Exception:
            continue
    return out


def _headers() -> dict:
    """SEMANTIC_SCHOLAR_API_KEY tanımlıysa x-api-key başlığı döner; yoksa boş."""
    key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    return {"x-api-key": key} if key else {}


def search(query: str, rows: int = 8, email: str = "") -> list[dict]:
    """Semantic Scholar'da arar; kanonik kayıt listesi döner. Hata/429 → []."""
    if not (query or "").strip():
        return []
    params = {"query": query, "limit": rows, "fields": _FIELDS}
    try:
        for attempt in range(3):
            r = requests.get(_API, params=params, headers=_headers(), timeout=20)
            if r.status_code == 429:
                if attempt < 2:
                    time.sleep(1)
                    continue
                return []
            if r.status_code != 200:
                return []
            data = r.json().get("data", []) or []
            return [_map(it) for it in data]
        return []
    except Exception:
        return []


def _name_to_initials(name: str) -> str:
    """'Jane A Smith' -> 'Smith JA'. Bölünemezse tam adı korur."""
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    if len(parts) < 2:
        return (name or "").strip()
    family = parts[-1]
    init = "".join(p[0] for p in parts[:-1] if p and p[0].isalpha())
    if not init:
        return (name or "").strip()
    return f"{family} {init.upper()}"


def _map(m: dict) -> dict:
    authors = []
    for a in m.get("authors", []) or []:
        nm = (a or {}).get("name", "")
        if nm:
            authors.append(_name_to_initials(nm))
    journal = m.get("journal") or {}
    ext = m.get("externalIds") or {}
    doi = ext.get("DOI") or ""
    pmid = ext.get("PubMed") or ""
    year = m.get("year")
    return {
        "type": "article-journal",
        "title": (m.get("title") or "").strip().rstrip("."),
        "abstract": (m.get("abstract") or "").strip(),
        "authors": authors,
        "journal": m.get("venue") or (journal.get("name") or ""),
        "iso": "",
        "year": str(year) if year else "",
        "volume": journal.get("volume") or "",
        "issue": "",
        "pages": (journal.get("pages") or "").strip(),
        "doi": str(doi).lower() if doi else "",
        "pmid": str(pmid) if pmid else "",
        "source": "semantic_scholar",
    }
