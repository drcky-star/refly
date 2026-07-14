"""Otomatik konu etiketleme — Claude referansları konuya göre etiketler.

Başlık + özetten 2-3 kısa konu etiketi üretir (anatomi bölgesi, hastalık, işlem,
çalışma tipi). Tutarlılık için kütüphanedeki mevcut etiket sözlüğünü öncelikle
yeniden kullanır (eş anlamlı çoğaltmayı önler). Verimlilik için toplu çağırır.
"""
from __future__ import annotations
import anthropic


class Tagger:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def tag_batch(self, records: list[dict], existing_tags: list[str],
                  max_tags: int = 3) -> dict[int, list[str]]:
        """records: [{title, abstract}] — döner {index: [etiketler]}."""
        if not records:
            return {}
        lines = []
        for i, r in enumerate(records):
            ab = (r.get("abstract") or "")[:600]
            lines.append(f"[{i}] {r.get('title','')}\n{ab}")
        vocab = ", ".join(existing_tags[:60]) or "(henüz etiket yok)"
        system = (
            "You are a medical librarian tagging references for a clinician's library. "
            f"For each article assign {max_tags} or fewer SHORT topic tags (1-2 words, lowercase) "
            "covering: anatomical region, disease/condition, procedure, and study type when clear. "
            "STRONGLY prefer reusing tags from the existing vocabulary when they fit, to avoid "
            "near-duplicate synonyms. Match the language of the existing vocabulary. "
            f"Existing vocabulary: {vocab}."
        )
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["index", "tags"],
                    },
                }
            },
            "required": ["items"],
        }
        msg = self.client.messages.create(
            model=self.model, max_tokens=2000, system=system,
            messages=[{"role": "user", "content": "\n\n".join(lines)}],
            tools=[{"name": "report_tags", "description": "Her makale için etiketler.",
                    "input_schema": schema}],
            tool_choice={"type": "tool", "name": "report_tags"},
        )
        out: dict[int, list[str]] = {}
        for block in msg.content:
            if block.type == "tool_use":
                for it in block.input.get("items", []):
                    i = it.get("index")
                    if isinstance(i, int) and 0 <= i < len(records):
                        tags = [t.strip().lower() for t in it.get("tags", []) if t.strip()][:max_tags]
                        out[i] = tags
        return out
