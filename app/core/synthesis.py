"""Literatür Sentezi (Literature Synthesis) — seçili kaynak kayıtlarını (başlık + özet vb.) alır,
Claude bunlardan atıflı, bütünlüklü bir literatür-derleme paragrafı yazar.

Kaynaklar verilen sırayla [1]..[N] olarak numaralandırılır; Claude yalnızca bu numaralı
kaynaklara atıf yapar ([n] işaretleri), sağlanan kaynakların dışında bilgi/atıf uydurmaz.
Bir kaynağın özeti yoksa başlığına dayanır. `question` verilirse sentez o soruya odaklanır;
yoksa kümenin genel bir sentezi üretilir.

Doğrulama/denetim hatlarının (autocite / audit) tamamlayıcısıdır: orada 'atıf gerçek mi',
burada 'kaynaklardan atıflı derleme yaz'. Claude yalnızca yapılandırılmış çıktı için kullanılır.
"""
from __future__ import annotations

import anthropic


def _fmt_record(i: int, rec: dict) -> str:
    """Tek kaydı '[i] Başlık (Yıl). Dergi. Abstract: ...' satırına çevirir."""
    title = (rec.get("title") or "").strip() or "(başlıksız)"
    year = str(rec.get("year") or "").strip()
    journal = (rec.get("journal") or rec.get("iso") or "").strip()
    abstract = (rec.get("abstract") or "").strip()
    if len(abstract) > 1000:
        abstract = abstract[:1000].rstrip() + "…"

    head = f"[{i}] {title}"
    if year:
        head += f" ({year})"
    head += "."
    if journal:
        head += f" {journal}."
    if abstract:
        head += f" Abstract: {abstract}"
    else:
        head += " Abstract: (yok — başlığa dayan)"
    return head


class Synthesizer:
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

    def run(self, records: list[dict], question: str = "", max_words: int = 220) -> dict:
        """Seçili kaynaklardan atıflı bir literatür sentezi/derleme paragrafı üretir."""
        # Guard: kaynak yoksa Claude'u çağırmadan boş dön.
        if not records:
            return {"synthesis": "", "used": [], "n_sources": 0}

        n = len(records)
        block = "\n\n".join(_fmt_record(i, rec) for i, rec in enumerate(records, start=1))

        system = (
            "You are an expert medical/academic writer producing a literature review. "
            "Write a COHESIVE synthesis (NOT a list or bullet points) of approximately "
            f"{max_words} words that INTEGRATES the findings across the provided sources into "
            "a flowing narrative. Insert citation markers like [1], [2] immediately after the "
            "statements they support; a single statement supported by multiple sources may use "
            "[1][3] or [2,4]. "
            "CRITICAL RULES: cite ONLY the provided sources by their bracketed [n] number "
            "(1.."
            f"{n}); NEVER invent facts, findings, or citations beyond what the sources state; "
            "do NOT cite any [n] that is not in the provided list. If a source lacks an "
            "abstract, rely on its title. Do not fabricate statistics or conclusions."
        )
        if question:
            system += (
                " Focus the synthesis on answering this specific question, drawing only on the "
                f"provided sources: {question!r}."
            )
        else:
            system += " Provide a general, balanced synthesis of the set as a whole."

        user = (
            "Synthesize the literature from the following numbered sources into a single "
            f"cohesive review paragraph (~{max_words} words) with [n] citation markers.\n\n"
            f"SOURCES:\n{block}"
        )

        schema = {
            "type": "object",
            "properties": {
                "synthesis": {
                    "type": "string",
                    "description": "The cohesive synthesis paragraph with [n] citation markers.",
                },
                "used": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "The [n] source numbers actually cited in the synthesis.",
                },
            },
            "required": ["synthesis", "used"],
        }

        # max_words'e bağlı token bütçesi (kelime başına ~2 token + pay).
        max_tokens = min(4000, max(600, max_words * 6))
        out = self._tool_call(system, user, schema, "report_synthesis", max_tokens=max_tokens)

        synthesis = (out.get("synthesis") or "").strip()
        # 'used'ı temizle: yalnızca geçerli aralıktaki [1..n], tekilleştir, sırala.
        used_raw = out.get("used") or []
        seen: set[int] = set()
        used: list[int] = []
        for x in used_raw:
            try:
                k = int(x)
            except (TypeError, ValueError):
                continue
            if 1 <= k <= n and k not in seen:
                seen.add(k)
                used.append(k)
        used.sort()

        return {"synthesis": synthesis, "used": used, "n_sources": n}
