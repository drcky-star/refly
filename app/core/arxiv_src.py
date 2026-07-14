"""arXiv import — arXiv Atom API. Arama ile yapılandırılmış kayıt listesi.

arXiv, Atom XML döner; kayıtlar xml.etree.ElementTree ile ayrıştırılır (PubMed gibi).
Kanonik Refly kayıt şekline eşlenir. Hata durumunda boş liste döner.
"""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET
import requests

_API = "http://export.arxiv.org/api/query"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_HEADERS = {"User-Agent": "Refly/1.0"}


def _collapse(s: str) -> str:
    """Baş/son boşlukları kırpar, iç boşluk/satır sonlarını tek boşluğa indirir."""
    return re.sub(r"\s+", " ", (s or "").strip())


def _fmt_author(name: str) -> str:
    """'Jane A Smith' -> 'Smith JA'. Bölünemezse tam adı korur."""
    name = _collapse(name)
    if not name:
        return ""
    parts = name.split(" ")
    if len(parts) < 2:
        return name
    family = parts[-1]
    init = "".join(p[0] for p in parts[:-1] if p).upper()
    return f"{family} {init}" if init else family


def _arxiv_id(url: str) -> str:
    """http://arxiv.org/abs/2401.12345v2 -> 2401.12345 (önek + sürüm eki temizlenir)."""
    aid = (url or "").strip().rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", aid)


def _map(entry: ET.Element) -> dict:
    title = _collapse(entry.findtext("atom:title", "", _NS))
    if title.endswith("."):
        title = title[:-1]
    abstract = _collapse(entry.findtext("atom:summary", "", _NS))
    authors = []
    for a in entry.findall("atom:author", _NS):
        nm = _fmt_author(a.findtext("atom:name", "", _NS))
        if nm:
            authors.append(nm)
    published = entry.findtext("atom:published", "", _NS)
    year = published[:4] if len(published) >= 4 else ""
    journal_ref = _collapse(entry.findtext("arxiv:journal_ref", "", _NS))
    doi = (entry.findtext("arxiv:doi", "", _NS) or "").strip().lower()
    return {
        "type": "article",
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "journal": journal_ref or "arXiv",
        "iso": "arXiv",
        "year": year,
        "volume": "",
        "issue": "",
        "pages": "",
        "doi": doi,
        "arxiv_id": _arxiv_id(entry.findtext("atom:id", "", _NS)),
        "source": "arxiv",
    }


def search(query: str, rows: int = 8, email: str = "") -> list[dict]:
    """arXiv'de arar; kanonik kayıt listesi döner. Hata → []."""
    try:
        r = requests.get(_API, params={"search_query": f"all:{query}", "start": 0,
                                       "max_results": rows, "sortBy": "relevance"},
                         headers=_HEADERS, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        return [_map(e) for e in root.findall("atom:entry", _NS)]
    except Exception:
        return []
