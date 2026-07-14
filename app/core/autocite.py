"""Otomatik referanslama — referanssız (veya sahte referanslı) bir metni alır,
her iddia için PubMed'de GERÇEK kaynak bulur, Claude ile doğrular ve atıfları
yerleştirip kaynakça üretir.

Boru hattı:
  1) İddia tespiti  — Claude metni okur, kaynak isteyen cümleleri + PubMed sorgusu üretir.
  2) PubMed arama   — her iddia için canlı aday makaleler (başlık + özet) çekilir.
  3) Doğrulama      — Claude aday özetlerini okur, cümleyi GERÇEKTEN destekleyeni seçer
                       (desteklemiyorsa atıf atılmaz — uydurma/yanlış atıf önlenir).
  4) Yerleştirme    — [1],[2]… atıfları cümle sonlarına eklenir, tekrarlar birleştirilir,
                       seçilen stilde kaynakça üretilir.
"""
from __future__ import annotations
import io
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import anthropic

from . import csl


# Metni cümlelere böler; her parça sondaki noktalamayı korur (yeniden birleştirme için).
# Kısaltmalara (et al., e.g., Fig.) dayanıklı: yalnızca noktalama + boşluk + BÜYÜK harf
# (ya da metin sonu) sınır sayılır — "et al., 2019" gibi yapılarda yanlış bölmez.
def split_sentences(text: str) -> list[str]:
    bounds = [m.end() for m in re.finditer(r"[.!?]+(?=\s+[A-ZÇĞİÖŞÜ\"(]|\s*$)", text)]
    parts, start = [], 0
    for b in bounds:
        parts.append(text[start:b])
        start = b
    if start < len(text):
        parts.append(text[start:])
    return [p for p in parts if p.strip()]


def read_manuscript(filename: str, data: bytes) -> str:
    """Yüklenen Word (.docx) / PDF / düz metin dosyasından metni çıkarır."""
    name = (filename or "").lower()
    if name.endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages)
    return data.decode("utf-8", errors="ignore")


# Mevcut (genelde ChatGPT'nin uydurduğu) atıfları ve kaynakça bölümünü temizler.
_REF_HEADING = re.compile(r"^\s*(references|bibliography|kaynak(la|ça)r?|works cited)\s*:?\s*$",
                          re.I | re.M)
_INLINE_NUM = re.compile(r"\s*[\[(]\s*\d+(?:\s*[-–,;]\s*\d+)*\s*[\])]")
# Büyük harfle başlayıp içinde 4 haneli yıl olan parantez: (Smith, 2019), (Smith et al., 2019),
# (Smith & Jones, 2019). Atıf olmayan parantezleri (ör. "(2 cm)") yıl şartı korur.
_AUTHOR_YEAR = re.compile(r"\s*\(\s*[A-ZÇĞİÖŞÜ][^)]{0,60}?(?:19|20)\d{2}[a-z]?\s*\)")


def strip_existing_citations(text: str) -> tuple[str, int]:
    """Var olan atıfları ([1], (Smith, 2020) vb.) ve sondaki kaynakça bölümünü siler.
    Döner: (temiz metin, silinen atıf sayısı)."""
    removed = 0
    m = _REF_HEADING.search(text)
    if m:
        text = text[:m.start()]
    text, n1 = _INLINE_NUM.subn("", text)
    text, n2 = _AUTHOR_YEAR.subn("", text)
    removed = n1 + n2
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text, removed


def _insert_marker(sentence: str, marker: str) -> str:
    """Atıfı cümlenin sonundaki noktalamadan ÖNCE yerleştirir: '...iddia [1].'"""
    m = re.search(r"[.!?]+\s*$", sentence)
    if m:
        return sentence[:m.start()].rstrip() + f" {marker}" + sentence[m.start():]
    return sentence.rstrip() + f" {marker}"


class AutoCite:
    def __init__(self, api_key: str, model: str, helper_model: str, pm, email: str = "",
                 searcher=None):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.helper = helper_model
        self.pm = pm
        self.email = email
        # Çoklu-kaynak arayıcı (sources.MultiSource). Verilmezse yalnız PubMed kullanılır.
        self.searcher = searcher

    # -------------------------------------------------- yardımcı: araçlı JSON çağrısı
    def _tool_call(self, model: str, system: str, user: str, schema: dict,
                   tool_name: str, max_tokens: int = 4000) -> dict:
        msg = self.client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{"name": tool_name, "description": "Yapılandırılmış sonucu döndür.",
                    "input_schema": schema}],
            tool_choice={"type": "tool", "name": tool_name},
        )
        for block in msg.content:
            if block.type == "tool_use":
                return block.input
        return {}

    # -------------------------------------------------- 1) iddia tespiti
    def detect_claims(self, sentences: list[str], max_claims: int = 30) -> list[dict]:
        numbered = "\n".join(f"[{i}] {s.strip()}" for i, s in enumerate(sentences))
        system = (
            "You are an expert academic research librarian who works across ALL disciplines "
            "(medicine, life sciences, physics, engineering, computer science, social sciences, "
            "economics, law, humanities). You receive a manuscript split into numbered sentences. "
            "Identify the sentences that state a factual, citable claim (empirical findings, "
            "statistics, mechanisms, established results, methods, datasets or theories attributable "
            "to prior work) that would normally require a citation. Skip headings, common-knowledge "
            "definitions, the authors' own opinions, and transition sentences. For each citable "
            "sentence, write a HIGH-RECALL literature search query using only the 2-3 most central "
            "concepts of that field (no field tags, avoid long AND chains that return nothing; prefer "
            "the core terms). The query must be broad enough to return results. Return at most "
            f"{max_claims} of the most important claims."
        )
        schema = {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer", "description": "Sentence number"},
                            "query": {"type": "string", "description": "PubMed search query"},
                        },
                        "required": ["index", "query"],
                    },
                }
            },
            "required": ["claims"],
        }
        out = self._tool_call(self.helper, system, numbered, schema, "report_claims", max_tokens=4000)
        claims = out.get("claims", [])
        # geçerli indeksler + sınır
        seen = set()
        result = []
        for c in claims:
            i = c.get("index")
            if isinstance(i, int) and 0 <= i < len(sentences) and i not in seen and c.get("query"):
                seen.add(i)
                result.append({"index": i, "query": c["query"].strip()})
            if len(result) >= max_claims:
                break
        return result

    # -------------------------------------------------- 2) aday çekme
    def candidates(self, query: str, k: int = 8) -> list[dict]:
        # Çoklu-kaynak açıksa PubMed + CrossRef + Europe PMC + arXiv (+ S2) birlikte taranır.
        if self.searcher is not None:
            try:
                return self.searcher.search(query, k=k)
            except Exception:
                return []
        try:
            pmids = self.pm.search(query, retmax=k)
            return self.pm.fetch(pmids)
        except Exception:
            return []

    # -------------------------------------------------- 3) doğrulama
    def verify(self, sentence: str, cands: list[dict]) -> dict:
        """En iyi destekleyen adayı seçer. Döner: {match: idx|-1, confidence, reason}."""
        if not cands:
            return {"match": -1, "confidence": 0, "reason": "Aday bulunamadı."}
        blocks = []
        for i, c in enumerate(cands):
            ab = (c.get("abstract") or "")[:1200]
            blocks.append(f"[{i}] {c.get('title','')}\nYear: {c.get('year','')}\nAbstract: {ab or '(özet yok)'}")
        system = (
            "You match citations for an academic manuscript in ANY discipline (like a literature "
            "review). Given a CLAIM and candidate articles (title + abstract), choose the SINGLE best "
            "article that is a SUITABLE citation for the claim — i.e. it is on the same topic and its "
            "content is consistent with and could reasonably support the statement. For general or "
            "background statements, a review, survey, guideline or authoritative overview on that topic "
            "IS an acceptable and good citation; you do NOT need an article that proves the exact "
            "wording. Only return match=-1 if NONE of the candidates is even topically relevant to "
            "the claim. Prefer reviews/surveys for broad statements and specific studies for "
            "specific findings. Give confidence 0-100 (how good a citation it is) and a one-line reason."
        )
        user = f"CLAIM:\n{sentence.strip()}\n\nCANDIDATES:\n" + "\n\n".join(blocks)
        schema = {
            "type": "object",
            "properties": {
                "match": {"type": "integer", "description": "Index of best candidate, or -1"},
                "confidence": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["match", "confidence", "reason"],
        }
        out = self._tool_call(self.model, system, user, schema, "verdict", max_tokens=600)
        m = out.get("match", -1)
        if not isinstance(m, int) or m < 0 or m >= len(cands):
            return {"match": -1, "confidence": out.get("confidence", 0),
                    "reason": out.get("reason", "Destekleyen kaynak yok.")}
        return {"match": m, "confidence": out.get("confidence", 0), "reason": out.get("reason", "")}

    def _process_claim(self, sentence: str, query: str) -> dict:
        """Tek iddia için: aday çek + doğrula. İlk sorgu eşleşmezse cümlenin kendisiyle
        ikinci (geniş) bir arama denenir. Döner: {rec|None, confidence, reason, alternatives}."""
        cands = self.candidates(query)
        verdict = self.verify(sentence, cands)
        used = cands

        # İkinci deneme: ilk sorgu bir kaynak veremezse cümlenin doğal halini ara
        if verdict["match"] < 0:
            seen = {c.get("pmid") for c in cands if c.get("pmid")}
            broad = [c for c in self.candidates(sentence.strip()[:220], k=6)
                     if c.get("pmid") not in seen]
            if broad:
                v2 = self.verify(sentence, broad)
                if v2["match"] >= 0:
                    used, verdict = broad, v2

        alts = [{"title": c.get("title", ""), "year": c.get("year", ""),
                 "journal": c.get("iso") or c.get("journal", ""), "pmid": c.get("pmid", "")}
                for j, c in enumerate(used) if j != verdict["match"]][:3]
        rec = used[verdict["match"]] if verdict["match"] >= 0 else None
        return {"rec": rec, "confidence": verdict.get("confidence", 0),
                "reason": verdict.get("reason", ""), "alternatives": alts}

    # -------------------------------------------------- boru hattını çalıştır
    def run(self, text: str, style: str = "vancouver", max_claims: int = 30,
            min_confidence: int = 45, clean_existing: bool = True,
            workers: int = 4, progress=None) -> dict:
        def report(stage, done, total):
            if progress:
                progress(stage, done, total)

        removed = 0
        if clean_existing:
            text, removed = strip_existing_citations(text)

        sentences = split_sentences(text)
        report("İddialar tespit ediliyor", 0, 1)
        claims = self.detect_claims(sentences, max_claims=max_claims)
        total = len(claims)
        report("Kaynaklar taranıyor ve doğrulanıyor", 0, total)

        # iddiaları PARALEL işle (büyük tezlerde 3-4x hız)
        done_lock = threading.Lock()
        counter = {"n": 0}
        results: dict[int, dict] = {}

        def work(claim):
            res = self._process_claim(sentences[claim["index"]], claim["query"])
            with done_lock:
                counter["n"] += 1
                report("Kaynaklar doğrulanıyor", counter["n"], total)
            return claim["index"], res

        n_workers = max(1, min(workers, total)) if total else 1
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            for idx, res in ex.map(work, claims):
                results[idx] = res

        # eşleşenleri/eşleşmeyenleri ayır
        chosen: dict[int, dict] = {}
        unmatched: list[dict] = []
        for i, res in results.items():
            if res["rec"] and res["confidence"] >= min_confidence:
                rec = res["rec"]
                rec["_confidence"] = res["confidence"]
                rec["_alternatives"] = res["alternatives"]
                chosen[i] = rec
            else:
                unmatched.append({"sentence": sentences[i].strip()[:160],
                                  "reason": res["reason"], "alternatives": res["alternatives"]})

        # atıfları ilk-görülme sırasına göre numarala (aynı kaynak tekrarında aynı no)
        from .references import dedupe_key
        order: list[str] = []
        key_to_num: dict[str, int] = {}
        key_to_rec: dict[str, dict] = {}
        idx_to_num: dict[int, int] = {}
        for i in sorted(chosen.keys()):
            rec = chosen[i]
            k = dedupe_key(rec)
            if k not in key_to_num:
                key_to_num[k] = len(order) + 1
                key_to_rec[k] = rec
                order.append(k)
            idx_to_num[i] = key_to_num[k]

        # metni yeniden kur, atıfları yerleştir
        out_sentences = []
        for i, s in enumerate(sentences):
            out_sentences.append(_insert_marker(s, f"[{idx_to_num[i]}]") if i in idx_to_num else s)
        annotated = "".join(out_sentences)

        ordered_recs = [key_to_rec[k] for k in order]
        entries = csl.build_reference_list(ordered_recs, style=style)

        # atıf başına özet (güven % + seçilen kaynak + alternatifler)
        citations = []
        for num, k in enumerate(order, 1):
            rec = key_to_rec[k]
            citations.append({
                "num": num,
                "title": rec.get("title", ""), "year": rec.get("year", ""),
                "author": (rec.get("authors") or [""])[0],   # yazar-yıl stili için ilk yazar
                "journal": rec.get("iso") or rec.get("journal", ""),
                "doi": rec.get("doi", ""), "pmid": rec.get("pmid", ""),
                "confidence": rec.get("_confidence", 0),
                "alternatives": rec.get("_alternatives", []),
            })

        report("Tamamlandı", total, total)
        return {
            "annotated_text": annotated,
            "references": ordered_recs,
            "entries": entries,
            "citations": citations,
            "n_claims": total,
            "n_cited": len(order),
            "n_inserted": len(idx_to_num),
            "removed_existing": removed,
            "unmatched": unmatched,
        }
