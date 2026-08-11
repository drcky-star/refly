"""Kanıt-yönü toplama ('Consensus Meter').

Bir EVET/HAYIR klinik soru için GERÇEK makaleleri (dışarıdan retrieval ile) alır ve her birini
Claude ile şu şekilde sınıflar: destekliyor (yes) / desteklemiyor (no) / karışık (mixed) /
belirsiz (unclear) — YALNIZCA o makalenin özet/başlığına dayanarak. Her makale için kısa bir
'bulgu' cümlesi + güven (0-1) döner. Böylece kanıtın nerede durduğu (dağılım) görünür.

İlke: Claude yalnızca SINIFLANDIRMA için; bulgu uydurmaz, sonucu kesin gerçek gibi sunmaz —
her sınıf makalenin kendi ifadesine dayanır (Refly'ın 'gerçek kaynak' bütünlük ilkesi).
"""
from __future__ import annotations

import anthropic

from .synthesis import _fmt_record

_STANCES = ("yes", "no", "mixed", "unclear")


class Evidence:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def run(self, question: str, records: list[dict]) -> dict:
        counts = {s: 0 for s in _STANCES}
        if not records:
            return {"question": question, "verdicts": [], "counts": counts, "n": 0}
        n = len(records)
        block = "\n\n".join(_fmt_record(i, r) for i, r in enumerate(records, start=1))
        system = (
            "You are a clinical evidence analyst. The user asks a YES/NO research question. "
            "Classify EACH numbered source by whether ITS OWN findings, as stated in its "
            "abstract/title, SUPPORT a 'yes' answer to the question ('yes'), SUPPORT a 'no' answer "
            "('no'), are MIXED/partial ('mixed'), or are off-topic / not determinable ('unclear'). "
            "For each source give a short 'finding' (a faithful paraphrase of the key relevant "
            "result, NOT invented) and a confidence 0-1. Base classification ONLY on the provided "
            "text; if a source lacks an abstract, rely on its title and prefer 'unclear' when unsure. "
            "You are classifying existing evidence, NOT declaring ground truth."
        )
        user = (f"QUESTION: {question}\n\nClassify each of the {n} numbered sources below.\n\n"
                f"SOURCES:\n{block}")
        schema = {
            "type": "object",
            "properties": {
                "verdicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "n": {"type": "integer", "description": "Source number 1..N"},
                            "stance": {"type": "string", "enum": list(_STANCES)},
                            "finding": {"type": "string", "description": "Faithful short key finding"},
                            "confidence": {"type": "number"},
                        },
                        "required": ["n", "stance", "finding"],
                    },
                },
            },
            "required": ["verdicts"],
        }
        msg = self.client.messages.create(
            model=self.model, max_tokens=min(4000, 400 + n * 120), system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{"name": "classify_evidence", "description": "Return per-source stance.",
                    "input_schema": schema}],
            tool_choice={"type": "tool", "name": "classify_evidence"},
        )
        raw = {}
        for b in msg.content:
            if b.type == "tool_use":
                raw = b.input
                break
        verdicts = []
        seen = set()
        for v in (raw.get("verdicts") or []):
            try:
                k = int(v.get("n"))
            except (TypeError, ValueError):
                continue
            if not (1 <= k <= n) or k in seen:
                continue
            seen.add(k)
            stance = v.get("stance") if v.get("stance") in _STANCES else "unclear"
            rec = records[k - 1]
            counts[stance] += 1
            verdicts.append({
                "stance": stance,
                "finding": (v.get("finding") or "").strip(),
                "confidence": v.get("confidence"),
                "title": rec.get("title", ""),
                "authors": rec.get("authors", []),
                "year": rec.get("year", ""),
                "journal": rec.get("journal") or rec.get("iso", ""),
                "doi": rec.get("doi", ""),
                "pmid": rec.get("pmid", ""),
            })
        # 'yes' önce, sonra 'no', 'mixed', 'unclear' — okunur sıralama
        order = {"yes": 0, "no": 1, "mixed": 2, "unclear": 3}
        verdicts.sort(key=lambda v: order.get(v["stance"], 9))
        return {"question": question, "verdicts": verdicts, "counts": counts, "n": len(verdicts)}
