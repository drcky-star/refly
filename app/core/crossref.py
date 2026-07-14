"""DOI ile referans import — CrossRef API. DOI -> yapılandırılmış kayıt."""
from __future__ import annotations
import re
import requests

_API = "https://api.crossref.org/works"
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def clean_doi(s: str) -> str:
    """URL / 'doi:' önekini temizleyip ham DOI döner."""
    m = _DOI_RE.search((s or "").strip())
    return m.group(0).rstrip(".") if m else ""


def fetch_doi(doi: str, email: str = "") -> dict | None:
    doi = clean_doi(doi)
    if not doi:
        return None
    try:
        r = requests.get(f"{_API}/{doi}", params={"mailto": email or "refly@example.com"}, timeout=20)
        if r.status_code != 200:
            return None
        return _map(r.json().get("message", {}))
    except Exception:
        return None


def search_title(title: str, email: str = "", rows: int = 5) -> list[dict]:
    try:
        r = requests.get(_API, params={"query.bibliographic": title, "rows": rows,
                                       "mailto": email or "refly@example.com"}, timeout=20)
        items = r.json().get("message", {}).get("items", [])
        return [_map(it) for it in items]
    except Exception:
        return []


_TYPE_MAP = {
    "journal-article": "article-journal", "book": "book", "book-chapter": "chapter",
    "proceedings-article": "paper-conference", "posted-content": "article",
    "dissertation": "thesis", "report": "report",
}


def _map(m: dict) -> dict:
    authors = []
    for a in m.get("author", []):
        fam = a.get("family", "")
        given = a.get("given", "")
        if fam and given:
            init = "".join(p[0] for p in re.split(r"[\s.-]+", given) if p)
            authors.append(f"{fam} {init}")
        elif fam:
            authors.append(fam)
        elif a.get("name"):
            authors.append(a["name"])
    issued = m.get("issued", {}).get("date-parts", [[None]])
    year = str(issued[0][0]) if issued and issued[0] and issued[0][0] else ""
    container = m.get("container-title", [""])
    short = m.get("short-container-title", [""])
    return {
        "type": _TYPE_MAP.get(m.get("type", ""), "article-journal"),
        "title": (m.get("title") or [""])[0].strip().rstrip("."),
        "authors": authors,
        "journal": container[0] if container else "",
        "iso": short[0] if short else "",
        "year": year,
        "volume": m.get("volume", ""),
        "issue": m.get("issue", ""),
        "pages": m.get("page", ""),
        "doi": m.get("DOI", ""),
        "publisher": m.get("publisher", ""),
        "url": m.get("URL", ""),
        "abstract": re.sub(r"<[^>]+>", "", m.get("abstract", "")).strip(),
    }
