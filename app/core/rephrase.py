"""Akademik yeniden ifade (paraphrase / netleştir).

Verilen pasajı DAHA NET, özlü ve akademik bir tonla — ANLAMI ve tüm ATIF işaretlerini
KORUYARAK — aynı dilde yeniden yazar. Amaç: kaynağı kendi cümlenle doğru ifade etmek
(intihalden kaçınmanın doğru yolu) ve özellikle ana dili İngilizce olmayan yazarlar için
dil netliği. AI-tespit ATLATMA değildir; Refly'ın bütünlük ilkesiyle uyumludur.

Claude yalnızca yapılandırılmış çıktı için kullanılır. Yeni bilgi/atıf UYDURMAZ.
"""
from __future__ import annotations

import anthropic

_SYSTEM = (
    "You are an expert academic copy-editor. Rewrite the passage the user provides so that it is "
    "clearer, more concise and more academic in tone, IN THE SAME LANGUAGE as the input. "
    "STRICT RULES — follow every one: "
    "(1) Preserve the meaning EXACTLY — do not add, remove or alter any fact, claim, number, "
    "measurement or nuance. "
    "(2) Preserve EVERY citation marker exactly as written and attached to the same statement — "
    "this includes Refly markers like [#123], numeric markers like [1] or [2,3], and "
    "author-date markers like (Smith, 2020). Never move a citation to a different claim. "
    "(3) NEVER invent citations, sources, facts, statistics or references. "
    "(4) Do not translate, do not add commentary or headings. "
    "Return ONLY the rewritten passage via the tool."
)


class Rephraser:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def run(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        text = text[:4000]          # maliyet/uzunluk sınırı
        schema = {
            "type": "object",
            "properties": {
                "rephrased": {
                    "type": "string",
                    "description": "The rewritten passage — same language, meaning and all "
                                   "citation markers preserved exactly.",
                }
            },
            "required": ["rephrased"],
        }
        msg = self.client.messages.create(
            model=self.model, max_tokens=1600, system=_SYSTEM,
            messages=[{"role": "user", "content": "Rewrite this passage:\n\n" + text}],
            tools=[{"name": "return_rewrite", "description": "Return the rewritten passage.",
                    "input_schema": schema}],
            tool_choice={"type": "tool", "name": "return_rewrite"},
        )
        for block in msg.content:
            if block.type == "tool_use":
                return (block.input.get("rephrased") or "").strip()
        return ""
