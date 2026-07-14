"""Atıf Denetleyici (Citation Audit) — yapıştırılan bir kaynakça / atıf listesini alır,
her referansın GERÇEKTEN var olup olmadığını CrossRef + PubMed'de doğrular.

ChatGPT'nin en büyük sorunu var olmayan (uydurma) referanslar üretmesidir; bu araç bunları
yakalar: her referans için
  • DOI verilmişse CrossRef'te çözülüyor mu,
  • başlık CrossRef/PubMed'de gerçek bir makaleyle eşleşiyor mu
bakar ve gerçek / şüpheli / bulunamadı olarak işaretler; gerçek eşleşmenin bağlantısını verir.

Doğrulama hattını (autocite) tersine kullanır: orada 'cümleye kaynak bul', burada
'referans gerçek mi'. Claude yalnızca serbest-metin kaynakçayı yapılandırmak için kullanılır.
"""
from __future__ import annotations
import difflib
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import anthropic

from . import crossref


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower())).strip()


def _ratio(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


class CitationAudit:
    def __init__(self, api_key: str, model: str, pm=None, email: str = ""):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.pm = pm
        self.email = email

    def _tool_call(self, system: str, user: str, schema: dict, tool_name: str,
                   max_tokens: int = 4000) -> dict:
        msg = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{"name": tool_name, "description": "Yapılandırılmış sonucu döndür.",
                    "input_schema": schema}],
            tool_choice={"type": "tool", "name": tool_name},
        )
        for block in msg.content:
            if block.type == "tool_use":
                return block.input
        return {}

    # ----------------------------------------------------- 1) serbest metni ayrıştır
    def parse_references(self, text: str) -> list[dict]:
        """Yapıştırılan kaynakçayı tek tek referanslara böler + alanları çıkarır."""
        system = (
            "You are a bibliography parser. The user pastes a reference list or the citations "
            "from a manuscript (any style: Vancouver, APA, numbered, etc.). Split it into "
            "INDIVIDUAL references. For each, extract: the full raw text, the article title, "
            "the first author's family name, the 4-digit year, the DOI if present, and the "
            "journal/venue if present. Do not invent data — leave a field empty if absent. "
            "Ignore non-reference lines (headings like 'References')."
        )
        schema = {
            "type": "object",
            "properties": {
                "references": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "raw": {"type": "string"},
                            "title": {"type": "string"},
                            "author": {"type": "string"},
                            "year": {"type": "string"},
                            "doi": {"type": "string"},
                            "journal": {"type": "string"},
                        },
                        "required": ["raw"],
                    },
                }
            },
            "required": ["references"],
        }
        out = self._tool_call(system, text, schema, "report_references", max_tokens=8000)
        refs = []
        for r in out.get("references", []):
            if (r.get("raw") or "").strip():
                refs.append({k: (r.get(k) or "").strip() for k in
                             ("raw", "title", "author", "year", "doi", "journal")})
        return refs

    # ----------------------------------------------------- 2) tek referansı doğrula
    def check_one(self, ref: dict) -> dict:
        raw, title = ref.get("raw", ""), ref.get("title", "")
        doi = crossref.clean_doi(ref.get("doi", "")) or crossref.clean_doi(raw)

        # a) DOI verilmişse doğrudan çöz
        if doi:
            rec = crossref.fetch_doi(doi, self.email)
            if rec and rec.get("title"):
                sim = _ratio(title, rec["title"]) if title else 1.0
                if sim >= 0.55 or not title:
                    return self._verdict("real", ref, rec, 0.99,
                                         "DOI CrossRef'te çözüldü.")
                return self._verdict("uncertain", ref, rec, sim,
                                     "DOI çözüldü ama başlık farklı — yanlış DOI olabilir.")
            return self._verdict("fabricated", ref, None, 0.0,
                                 "Verilen DOI CrossRef'te bulunamadı (uydurma olabilir).")

        # b) DOI yok → başlık + YAZAR + YIL ile ara (kısa/jenerik başlıkları ayırt eder),
        #    eşleşmeyi yazar/yıl ile doğrula (sahte başlığın alakasız bir makaleye rastgele
        #    benzemesini "gerçek" saymamak için).
        if not title:
            return self._verdict("uncertain", ref, None, 0.0,
                                 "Başlık/DOI ayrıştırılamadı — elle kontrol et.")
        author, year = ref.get("author", ""), ref.get("year", "")
        cands = crossref.search_title(raw or title, self.email, rows=3)  # ham atıf en iyi eşleşir
        if self.pm:
            try:
                pm_q = " ".join(x for x in (title, author, year) if x)
                cands += self.pm.fetch(self.pm.search(pm_q, retmax=3))
            except Exception:
                pass
        best, score = None, 0.0
        for c in cands:
            s = _ratio(title, c.get("title", ""))
            if s > score:
                best, score = c, s

        au_ok, yr_ok = self._corroborate(author, year, best)
        if score >= 0.9 or (score >= 0.7 and (au_ok or yr_ok)):
            corr = " (yazar/yıl doğrulandı)" if (au_ok or yr_ok) else ""
            return self._verdict("real", ref, best, score, "Gerçek bir makaleyle eşleşti" + corr + ".")
        if score >= 0.7:
            return self._verdict("uncertain", ref, best, score,
                                 "Başlık benziyor ama yazar/yıl tutmuyor — yanlış/eksik atıf olabilir.")
        if score >= 0.55:
            return self._verdict("uncertain", ref, best, score,
                                 "Zayıf kısmi eşleşme — elle doğrula.")
        return self._verdict("fabricated", ref, None, score,
                             "CrossRef/PubMed'de eşleşen makale yok (uydurma olabilir).")

    @staticmethod
    def _corroborate(author: str, year: str, rec: dict | None):
        """Eşleşen kaydın yazar soyadı ve yılı, verilen referansla tutuyor mu?"""
        if not rec:
            return False, False
        au_ok = False
        if author:
            fam = _norm(author).split()
            fam = fam[0] if fam else ""
            au_ok = bool(fam) and any(fam in _norm(a) for a in rec.get("authors", []))
        yr_ok = bool(year) and str(year).strip() == str(rec.get("year", "")).strip()
        return au_ok, yr_ok

    @staticmethod
    def _verdict(status: str, ref: dict, rec: dict | None, score: float, reason: str) -> dict:
        match = None
        if rec:
            doi = (rec.get("doi") or "").lower()
            pmid = rec.get("pmid") or ""
            link = (f"https://doi.org/{doi}" if doi else
                    (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""))
            match = {
                "title": rec.get("title", ""),
                "authors": ", ".join(rec.get("authors", [])[:3]),
                "journal": rec.get("iso") or rec.get("journal", ""),
                "year": rec.get("year", ""), "doi": doi, "pmid": pmid, "link": link,
            }
        return {"status": status, "score": round(score, 2), "reason": reason,
                "given": ref, "match": match}

    # ----------------------------------------------------- boru hattı
    def run(self, text: str, workers: int = 6, progress=None) -> dict:
        refs = self.parse_references(text)
        total = len(refs)
        if progress:
            progress("Referanslar doğrulanıyor", 0, total)

        results: dict[int, dict] = {}
        lock = threading.Lock()
        counter = {"n": 0}

        def work(item):
            i, ref = item
            res = self.check_one(ref)
            with lock:
                counter["n"] += 1
                if progress:
                    progress("Referanslar doğrulanıyor", counter["n"], total)
            return i, res

        n_workers = max(1, min(workers, total)) if total else 1
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            for i, res in ex.map(work, list(enumerate(refs))):
                results[i] = res

        ordered = [results[i] for i in range(total)]
        n_real = sum(1 for r in ordered if r["status"] == "real")
        n_fab = sum(1 for r in ordered if r["status"] == "fabricated")
        n_unc = sum(1 for r in ordered if r["status"] == "uncertain")
        if progress:
            progress("Tamamlandı", total, total)
        return {"references": ordered, "n": total, "n_real": n_real,
                "n_fabricated": n_fab, "n_uncertain": n_unc}
