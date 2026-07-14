"""Europe PMC ile referans arama — REST search API. Sorgu -> yapılandırılmış kayıt listesi."""
from __future__ import annotations
import re
import requests

_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def _clean_doi(s: str) -> str:
    """URL / 'doi:' önekini temizleyip ham (küçük harf) DOI döner."""
    m = _DOI_RE.search((s or "").strip())
    return m.group(0).rstrip(".").lower() if m else ""


def search(query: str, rows: int = 8, email: str = "") -> list[dict]:
    """Europe PMC'de arar; kanonik kayıt listesi döner. Hata → []."""
    try:
        r = requests.get(_API, params={
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": rows,
            "email": email or "refly@example.com",
        }, headers={"User-Agent": "Refly/1.0 (mailto:refly@example.com)"}, timeout=20)
        if r.status_code != 200:
            return []
        results = r.json().get("resultList", {}).get("result", [])
        return [_map(it) for it in results]
    except Exception:
        return []


def fetch_doi(doi: str, email: str = "") -> dict | None:
    """DOI ile tek kayıt getirir (query=DOI:"..."). Bulunamazsa → None."""
    doi = _clean_doi(doi)
    if not doi:
        return None
    try:
        r = requests.get(_API, params={
            "query": f'DOI:"{doi}"',
            "format": "json",
            "resultType": "core",
            "pageSize": 1,
            "email": email or "refly@example.com",
        }, headers={"User-Agent": "Refly/1.0 (mailto:refly@example.com)"}, timeout=20)
        if r.status_code != 200:
            return None
        results = r.json().get("resultList", {}).get("result", [])
        return _map(results[0]) if results else None
    except Exception:
        return None


def _authors(m: dict) -> list[str]:
    """authorList.author[] (lastName + initials) tercih edilir; yoksa authorString ayrıştırılır."""
    out = []
    author_list = (m.get("authorList") or {}).get("author") or []
    for a in author_list:
        last = (a.get("lastName") or "").strip()
        init = (a.get("initials") or "").strip().replace(".", "")
        if last and init:
            out.append(f"{last} {init}")
        elif last:
            out.append(last)
        elif a.get("fullName"):
            out.append(a["fullName"].strip())
    if out:
        return out
    # Fallback: "Smith JA, Jones B" biçimindeki authorString
    s = (m.get("authorString") or "").strip().rstrip(".")
    if s:
        out = [p.strip() for p in s.split(",") if p.strip()]
    return out


def _map(m: dict) -> dict:
    ji = m.get("journalInfo") or {}
    journal = ji.get("journal") or {}
    iso = journal.get("isoabbreviation") or journal.get("medlineAbbreviation") or ""
    year = str(m.get("pubYear") or ji.get("yearOfPublication") or "").strip()
    return {
        "type": "article-journal",
        "title": (m.get("title") or "").strip().rstrip("."),
        "abstract": (m.get("abstractText") or "").strip(),
        "authors": _authors(m),
        "journal": (journal.get("title") or "").strip(),
        "iso": iso.strip(),
        "year": year,
        "volume": str(ji.get("volume") or "").strip(),
        "issue": str(ji.get("issue") or "").strip(),
        "pages": str(m.get("pageInfo") or "").strip(),
        "doi": _clean_doi(m.get("doi") or ""),
        "pmid": str(m.get("pmid") or "").strip(),
        "pmcid": str(m.get("pmcid") or "").strip(),
        "source": "europepmc",
    }
