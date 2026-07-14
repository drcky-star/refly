"""PubMed import — NCBI E-utilities (esearch + efetch). PMID veya arama ile.

Paralel kullanımda NCBI hız limitini (anahtarsız 3/sn, anahtarlı 10/sn) aşmamak için
tüm istekler global bir kilitle hız-sınırlanır; geçici hatalarda (429/zaman aşımı) tekrar
denenir. Böylece eşzamanlı çağrılarda istekler sessizce boş dönmez (eşleşme kaybı önlenir).
"""
from __future__ import annotations
import time
import threading
import xml.etree.ElementTree as ET
import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMed:
    def __init__(self, email: str = "", api_key: str = ""):
        self.email = email
        self.api_key = api_key
        self.delay = 0.11 if api_key else 0.35   # min istekler-arası aralık
        self._lock = threading.Lock()
        self._last = 0.0

    def _params(self, extra: dict) -> dict:
        p = {"tool": "refly", "email": self.email}
        if self.api_key:
            p["api_key"] = self.api_key
        p.update(extra)
        return p

    def _get(self, path: str, params: dict, timeout: int):
        """Hız-sınırlı + 3 denemeli GET (eşzamanlı çağrılarda 429'u önler)."""
        last_err = None
        for attempt in range(3):
            with self._lock:                       # global throttle
                wait = self.delay - (time.monotonic() - self._last)
                if wait > 0:
                    time.sleep(wait)
                self._last = time.monotonic()
            try:
                r = requests.get(f"{EUTILS}/{path}", params=params, timeout=timeout)
                if r.status_code == 429:           # hız aşımı — bekle, tekrar dene
                    time.sleep(0.6 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                last_err = e
                time.sleep(0.5 * (attempt + 1))
        if last_err:
            raise last_err
        raise requests.RequestException("PubMed 429")

    def search(self, query: str, retmax: int = 30) -> list[str]:
        params = self._params({"db": "pubmed", "term": query, "retmax": retmax,
                               "retmode": "json", "sort": "relevance"})
        r = self._get("esearch.fcgi", params, timeout=30)
        return r.json().get("esearchresult", {}).get("idlist", [])

    def related(self, pmid: str, retmax: int = 20) -> list[str]:
        """Bir makaleye PubMed'in benzer/ilgili makalelerini (komşular) döner."""
        if not pmid:
            return []
        params = self._params({"dbfrom": "pubmed", "db": "pubmed", "id": pmid,
                               "cmd": "neighbor_score", "retmode": "json"})
        r = self._get("elink.fcgi", params, timeout=30)
        out = []
        for ls in r.json().get("linksets", []):
            for db in ls.get("linksetdbs", []):
                if db.get("linkname") == "pubmed_pubmed":
                    for link in db.get("links", []):
                        lid = link.get("id") if isinstance(link, dict) else str(link)
                        if lid and lid != pmid:
                            out.append(lid)
        return out[:retmax]

    def fetch(self, pmids: list[str]) -> list[dict]:
        if not pmids:
            return []
        out: list[dict] = []
        for i in range(0, len(pmids), 100):
            batch = pmids[i:i + 100]
            params = self._params({"db": "pubmed", "id": ",".join(batch), "retmode": "xml"})
            r = self._get("efetch.fcgi", params, timeout=60)
            out.extend(self._parse(r.text))
        return out

    @staticmethod
    def _parse(xml_text: str) -> list[dict]:
        records = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return records
        for art in root.findall(".//PubmedArticle"):
            pmid = art.findtext(".//PMID", "")
            t_el = art.find(".//ArticleTitle")
            title = "".join(t_el.itertext()) if t_el is not None else ""
            abstract_parts = []
            for ab in art.findall(".//Abstract/AbstractText"):
                label = ab.get("Label")
                txt = "".join(ab.itertext())
                abstract_parts.append(f"{label}: {txt}" if label else txt)
            abstract = " ".join(abstract_parts)
            authors = []
            for a in art.findall(".//Author"):
                ln = a.findtext("LastName")
                init = a.findtext("Initials")
                if ln:
                    authors.append(f"{ln} {init}" if init else ln)
            journal = art.findtext(".//Journal/Title", "")
            iso = art.findtext(".//Journal/ISOAbbreviation", "")
            year = art.findtext(".//JournalIssue/PubDate/Year") or art.findtext(".//PubDate/Year") or ""
            volume = art.findtext(".//JournalIssue/Volume", "")
            issue = art.findtext(".//JournalIssue/Issue", "")
            pages = art.findtext(".//Pagination/MedlinePgn", "")
            # Asıl DOI ELocationID'dedir; ArticleId listesinde erratum/yorum DOI'leri
            # de bulunabildiğinden önce onu deneriz, yoksa ilk ArticleId DOI'sine düşeriz.
            doi = art.findtext(".//Article/ELocationID[@EIdType='doi']", "") or ""
            pmcid = ""
            for el in art.findall(".//PubmedData/ArticleIdList/ArticleId"):
                idt = el.get("IdType")
                if idt == "doi" and not doi:
                    doi = el.text or ""
                elif idt == "pmc":
                    pmcid = el.text or ""
            pub_types = [pt.text for pt in art.findall(".//PublicationType") if pt.text]
            corrections = [c.get("RefType") for c in art.findall(".//CommentsCorrections") if c.get("RefType")]
            records.append({
                "type": "article-journal",
                "pmid": pmid, "title": title.strip().rstrip("."), "abstract": abstract.strip(),
                "authors": authors, "journal": journal, "iso": iso, "year": year,
                "volume": volume, "issue": issue, "pages": pages, "doi": doi, "pmcid": pmcid,
                "pub_types": pub_types, "corrections": corrections,
            })
        return records
