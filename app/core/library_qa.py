"""Kütüphaneye Sor (Ask Your Library) — bir soru + bir dizi belge (her biri önceden
çıkarılmış metin, örn. bir PDF'ten ya da özetten) alır; soruyla en ilgili pasajları
seçip Claude ile YALNIZCA verilen metne dayanan, ATIFLI bir yanıt üretir.

Getirme (retrieval) tamamen bağımsız / standart-kütüphane ile yapılır (gömü yok):
soru sözcüklere ayrılır, her belgenin metni ~1200 karakterlik parçalara bölünür, her
parça soru sözcükleriyle örtüşmesine göre puanlanır (belge başlığı da örtüşürse ek puan),
en iyi parçalar karakter bütçesine kadar seçilir. Küçük belgelerde tüm metin kullanılır.

Ardından her seçilen parça '[<id>] <başlık>:\n<parça>' olarak bir bağlam bloğuna dizilir.
Claude'a YALNIZCA bu kaynaklardan yanıt vermesi, her iddiadan sonra [id] atıf işareti
koyması, bağlam yanıtı desteklemiyorsa "kütüphanede bulamadım" demesi söylenir. Çıktı
zorunlu araç çağrısıyla {answer, used} olarak alınır.

Sentez/denetim hatlarının (synthesis / autocite / audit) tamamlayıcısıdır: orada
'kaynaklardan derleme yaz' / 'atıf gerçek mi', burada 'kütüphaneye soru sor'. Claude
yalnızca yapılandırılmış çıktı için kullanılır; getirme kısmı yereldir.
"""
from __future__ import annotations

import re

import anthropic

# Çok kısa / bilgi taşımayan sözcükler (İngilizce + Türkçe karışık) — puanlamada atlanır.
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are",
    "was", "were", "be", "been", "by", "at", "as", "it", "its", "this", "that", "these",
    "those", "from", "into", "than", "then", "there", "their", "them", "which", "who",
    "what", "when", "where", "how", "why", "does", "do", "did", "can", "could", "should",
    "would", "will", "may", "might", "has", "have", "had", "not", "no", "vs", "using",
    "ve", "ya", "veya", "ile", "bir", "bu", "şu", "mi", "mı", "mu", "mü", "için", "en",
    "çok", "daha", "gibi", "olan", "midir", "mıdır", "nedir", "nasıl",
}

_WORD_RE = re.compile(r"[a-zçğıöşü0-9]+", re.IGNORECASE)


def _tokens(text: str) -> set[str]:
    """Metni küçük harfli, anlamlı sözcük kümesine çevirir (kısa/stopword sözcükleri atar)."""
    out: set[str] = set()
    for w in _WORD_RE.findall((text or "").lower()):
        if len(w) < 3 or w in _STOP:
            continue
        out.add(w)
    return out


def _chunk(text: str, size: int = 1200) -> list[str]:
    """Metni ~size karakterlik parçalara böler; kolaysa paragraf/cümle sınırında keser."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    # Önce paragraflara ayır, paragrafları biriktirerek ~size'lık parçalar oluştur;
    # tek bir paragraf çok uzunsa cümle sınırında (kolaysa) daha ince böl.
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) <= 1:
        paras = [text]

    chunks: list[str] = []
    buf = ""
    for p in paras:
        for piece in _split_long(p, size):
            if not buf:
                buf = piece
            elif len(buf) + 1 + len(piece) <= size:
                buf += " " + piece
            else:
                chunks.append(buf)
                buf = piece
    if buf:
        chunks.append(buf)
    return chunks


def _split_long(para: str, size: int) -> list[str]:
    """Bir paragraf size'dan uzunsa cümle sınırında böler; olmazsa sert keser."""
    if len(para) <= size:
        return [para]
    sents = re.split(r"(?<=[.!?])\s+", para)
    out: list[str] = []
    buf = ""
    for s in sents:
        if len(s) > size:                    # tek cümle bile çok uzun → sert kesim
            if buf:
                out.append(buf)
                buf = ""
            for i in range(0, len(s), size):
                out.append(s[i:i + size].strip())
            continue
        if not buf:
            buf = s
        elif len(buf) + 1 + len(s) <= size:
            buf += " " + s
        else:
            out.append(buf)
            buf = s
    if buf:
        out.append(buf)
    return [c for c in out if c]


class LibraryQA:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def _tool_call(self, system: str, user: str, schema: dict, tool_name: str,
                   max_tokens: int = 2000) -> dict:
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

    # ------------------------------------------------- getirme (yerel, bağımsız)
    def _retrieve(self, question: str, docs: list[dict], k: int, char_budget: int) -> list[dict]:
        """Soruyla en ilgili parçaları seçer. Dönen: [{'id','title','chunk'}] (bağlam sırası)."""
        q = _tokens(question)

        # Tüm belgelerin metnini parçala + puanla.
        scored: list[dict] = []
        for doc in docs:
            did = doc.get("id")
            title = (doc.get("title") or "").strip()
            title_tok = _tokens(title)
            title_bonus = 2 if (q & title_tok) else 0
            for ch in _chunk(doc.get("text", "")):
                overlap = len(q & _tokens(ch))
                scored.append({
                    "id": did, "title": title, "chunk": ch,
                    "score": overlap + title_bonus, "doc_id": did,
                })

        if not scored:
            return []

        total_chars = sum(len(s["chunk"]) for s in scored)
        # Metin zaten küçükse (bütçeye sığıyorsa) hepsini olduğu gibi kullan.
        if total_chars <= char_budget:
            return [{"id": s["id"], "title": s["title"], "chunk": s["chunk"]} for s in scored]

        # Puana göre sırala (eşitlikte uzun parça biraz önde — daha çok bağlam).
        scored.sort(key=lambda s: (s["score"], len(s["chunk"])), reverse=True)

        selected: list[dict] = []
        used_chars = 0
        seen_docs: set = set()

        # 1) Mümkünse k ayrı belgeden en iyi parçayı garanti et (kapsama için).
        best_per_doc: dict = {}
        for s in scored:
            d = s["doc_id"]
            if d not in best_per_doc:
                best_per_doc[d] = s
        for s in list(best_per_doc.values())[:k]:
            if s["score"] <= 0:
                continue
            if used_chars + len(s["chunk"]) > char_budget and selected:
                continue
            selected.append(s)
            used_chars += len(s["chunk"])
            seen_docs.add(s["doc_id"])

        # 2) Kalan bütçeyi genel en iyi parçalarla doldur (tekrarı atla).
        for s in scored:
            if s in selected or s["score"] <= 0:
                continue
            if used_chars + len(s["chunk"]) > char_budget:
                continue
            selected.append(s)
            used_chars += len(s["chunk"])

        # Hiçbir parça soruyla örtüşmüyorsa (hepsi 0 puan) yine de bağlam ver:
        # ilk k belgenin ilk parçalarını bütçeye kadar al.
        if not selected:
            for s in list(best_per_doc.values())[:k]:
                if used_chars + len(s["chunk"]) > char_budget and selected:
                    break
                selected.append(s)
                used_chars += len(s["chunk"])

        return [{"id": s["id"], "title": s["title"], "chunk": s["chunk"]} for s in selected]

    # ------------------------------------------------- ana giriş
    def ask(self, question: str, docs: list[dict], k: int = 6,
            char_budget: int = 12000) -> dict:
        """docs: [{"id": <int|str>, "title": str, "text": str}]. Soruyla en ilgili
        pasajları seçip Claude ile ATIFLI (yalnız verilen metinden) yanıt üretir."""
        question = (question or "").strip()
        docs = docs or []

        # Guard: belge yoksa ya da soru boşsa Claude'u çağırmadan boş dön.
        if not docs or not question:
            return {"answer": "", "used": [], "n_docs": 0, "n_context_chunks": 0}

        chunks = self._retrieve(question, docs, k, char_budget)
        if not chunks:
            return {"answer": "", "used": [], "n_docs": len(docs), "n_context_chunks": 0}

        # Bağlam bloğu: her parça '[<id>] <başlık>:\n<parça>' olarak.
        blocks = []
        for c in chunks:
            title = c["title"] or "(başlıksız)"
            blocks.append(f"[{c['id']}] {title}:\n{c['chunk']}")
        context = "\n\n".join(blocks)

        system = (
            "You are a careful research assistant answering a question using ONLY the "
            "provided sources. Each source is prefixed with a bracketed id like [3]. "
            "Base every statement strictly on the source texts — do NOT use outside "
            "knowledge and do NOT invent facts or citations. After each claim, insert a "
            "citation marker with the id of the source(s) that support it, e.g. [3] or "
            "[1][2]. Only cite ids that actually appear in the sources. If the sources do "
            "not contain enough information to answer, say clearly that you cannot find the "
            "answer in the library, and do not guess. Be concise and factual."
        )
        user = (
            f"QUESTION:\n{question}\n\n"
            f"SOURCES:\n{context}\n\n"
            "Answer the question using only these sources, with inline [id] citations."
        )
        schema = {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "The answer, grounded only in the sources, with inline "
                                   "[id] citation markers after each claim.",
                },
                "used": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The source ids actually cited in the answer.",
                },
            },
            "required": ["answer", "used"],
        }
        out = self._tool_call(system, user, schema, "report_answer", max_tokens=2000)

        answer = (out.get("answer") or "").strip()
        # 'used' değerlerini olabildiğince orijinal id türüne (int/str) geri eşle.
        id_by_str = {str(c["id"]): c["id"] for c in chunks}
        used: list = []
        seen: set = set()
        for u in (out.get("used") or []):
            key = str(u).strip()
            val = id_by_str.get(key, u)
            if key not in seen:
                seen.add(key)
                used.append(val)

        return {
            "answer": answer,
            "used": used,
            "n_docs": len(docs),
            "n_context_chunks": len(chunks),
        }
