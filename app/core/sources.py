"""Çoklu veritabanı arama — PubMed + CrossRef + Europe PMC + Semantic Scholar + arXiv.

Auto-cite (ve genel arama) için birden çok literatür kaynağını PARALEL tarar, sonuçları
tek kanonik listede birleştirir ve yinelenenleri (DOI → PMID → arXiv id → normalize
başlık) ayıklar. Böylece tıp dışı alanlar + preprint'ler de kapsanır, eşleşme oranı artar.

Her kaynak adaptörü `search(query, rows, email) -> list[dict]` arayüzünü sağlar ve
kanonik kayıt döner (bkz. crossref.py). Bir kaynak hata/limit verirse sessizce atlanır.
"""
from __future__ import annotations
import os
import re
from concurrent.futures import ThreadPoolExecutor

from . import crossref, europe_pmc, semantic_scholar, arxiv_src

_TAG = re.compile(r"<[^>]+>")

# Kayıt zenginliği önceliği (aynı makale birden çok kaynaktan gelirse hangisini tutalım)
_PRIORITY = ["pubmed", "crossref", "europepmc", "semantic_scholar", "arxiv"]
# Round-robin ağırlıkları: PubMed tıpta güçlü (2x); diğerleri tıp dışı kapsama için 1x
_WEIGHTS = {"pubmed": 2, "crossref": 1, "europepmc": 1, "semantic_scholar": 1, "arxiv": 1}
# Yinelenen birleştirmede eksikse tamamlanacak alanlar
_FILL = ("abstract", "doi", "pmid", "pmcid", "iso", "journal", "volume", "issue", "pages", "authors")


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())[:60]


def _key(rec: dict) -> str:
    doi = (rec.get("doi") or "").lower().strip()
    if doi:
        return "doi:" + doi
    pmid = (rec.get("pmid") or "").strip()
    if pmid:
        return "pmid:" + pmid
    aid = (rec.get("arxiv_id") or "").strip()
    if aid:
        return "arxiv:" + aid
    return "ti:" + _norm_title(rec.get("title", ""))


def _clean(rec: dict) -> dict:
    ab = rec.get("abstract")
    if ab and "<" in ab:
        rec["abstract"] = _TAG.sub(" ", ab).replace("  ", " ").strip()
    return rec


def default_sources() -> list[str]:
    """Etkin kaynaklar. REFLY_SOURCES ile ezilir; anahtarsız Semantic Scholar (429)
    varsayılan dışıdır — anahtar varsa otomatik eklenir."""
    env = os.getenv("REFLY_SOURCES", "").strip()
    if env:
        return [s.strip() for s in env.split(",") if s.strip()]
    src = ["pubmed", "crossref", "europepmc", "arxiv"]
    if os.getenv("SEMANTIC_SCHOLAR_API_KEY"):
        src.insert(3, "semantic_scholar")
    return src


class MultiSource:
    """Birden çok kaynağı tek `search(query, k)` arkasında birleştirir.
    `pm` = PubMed örneği (pubmed.py); diğer kaynaklar modül fonksiyonlarıdır."""

    def __init__(self, pm=None, email: str = "", enabled: list[str] | None = None):
        self.pm = pm
        self.email = email
        self.enabled = enabled or default_sources()

    def _pubmed(self, query: str, rows: int, email: str) -> list[dict]:
        if not self.pm:
            return []
        try:
            return self.pm.fetch(self.pm.search(query, retmax=rows))
        except Exception:
            return []

    def _adapters(self):
        m = {
            "pubmed": self._pubmed,
            "crossref": lambda q, rows, email: crossref.search_title(q, email=email, rows=rows),
            "europepmc": lambda q, rows, email: europe_pmc.search(q, rows=rows, email=email),
            "semantic_scholar": lambda q, rows, email: semantic_scholar.search(q, rows=rows, email=email),
            "arxiv": lambda q, rows, email: arxiv_src.search(q, rows=rows, email=email),
        }
        return [(name, m[name]) for name in self.enabled if name in m]

    def search(self, query: str, k: int = 8) -> list[dict]:
        """Tüm etkin kaynakları paralel tarar, birleştirir, dedup'lar. En çok ~12 aday döner."""
        adapters = self._adapters()
        if not adapters:
            return []
        per = max(4, k)  # her kaynaktan ~k aday; birleşince daha çok olur

        def run(item):
            name, fn = item
            try:
                recs = fn(query, per, self.email) or []
            except Exception:
                recs = []
            for r in recs:
                r.setdefault("source", name)
                _clean(r)
            return name, recs

        bucket: dict[str, list[dict]] = {}
        with ThreadPoolExecutor(max_workers=len(adapters)) as ex:
            for name, recs in ex.map(run, adapters):
                bucket[name] = recs

        # AĞIRLIKLI ROUND-ROBIN birleştirme: kaynakları serpiştirir ki tek bir kaynak (ör.
        # PubMed) cap'i doldurup diğerlerini aç bırakmasın. Böylece TIP DIŞI sorgularda da
        # arXiv/CrossRef/S2 yer bulur; PubMed 2x ağırlıkla tıpta güçlü kalır. Az sonuç
        # dönen kaynak çabuk tükenir, yerini ilgili kaynağa bırakır. Dupe → en zengin alan tutulur.
        cap = max(k, 12)
        names = [n for n in _PRIORITY if bucket.get(n)] + [n for n in bucket if n not in _PRIORITY and bucket.get(n)]
        pos = {n: 0 for n in names}
        seen: dict[str, dict] = {}
        order: list[str] = []
        progressed = True
        while len(order) < cap and progressed:
            progressed = False
            for name in names:
                for _ in range(_WEIGHTS.get(name, 1)):
                    lst = bucket.get(name, [])
                    if pos[name] >= len(lst):
                        break
                    r = lst[pos[name]]; pos[name] += 1; progressed = True
                    if not r.get("title"):
                        continue
                    key = _key(r)
                    if key not in seen:
                        seen[key] = r; order.append(key)
                    else:
                        cur = seen[key]
                        for f in _FILL:
                            if not cur.get(f) and r.get(f):
                                cur[f] = r[f]
                    if len(order) >= cap:
                        break
                if len(order) >= cap:
                    break
        return [seen[key] for key in order]
