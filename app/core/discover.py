"""Keşif yardımcıları — anlamsal (AI) kütüphane araması + dergi önerisi.

semantic_rank: doğal-dil sorguya göre kullanıcının KENDİ kayıtlarını (başlık+özet) Claude ile
  anlamca sıralar — kelime birebir geçmese de ilgili olanı bulur (gömme/vektör altyapısı
  gerektirmez; kişisel kütüphane küçük-orta olduğundan doğrudan sıralama yeterli).
suggest_journals: başlık+özetten uygun hedef dergileri önerir (kapsam + uygunluk gerekçesiyle).

Her ikisi de yalnızca sağlanan/bilinen bilgiye dayanır; uydurma atıf/veri üretmez.
"""
from __future__ import annotations

import anthropic


class Discover:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def _tool(self, system, user, schema, name, max_tokens=1500):
        msg = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{"name": name, "description": "Return structured result.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": name},
        )
        for b in msg.content:
            if b.type == "tool_use":
                return b.input
        return {}

    def semantic_rank(self, query: str, records: list[dict], top: int = 12) -> list[dict]:
        """records: [{id,title,abstract}]. Sorguya en ilgili kayıt id'lerini sıralı döner."""
        if not records or not query.strip():
            return []
        lines = []
        for r in records:
            ab = (r.get("abstract") or "").strip()
            if len(ab) > 400:
                ab = ab[:400] + "…"
            lines.append(f"id={r['id']} | {(r.get('title') or '').strip()}" + (f" — {ab}" if ab else ""))
        block = "\n".join(lines)
        system = (
            "You are a research librarian. Given a natural-language query and a list of the user's "
            "saved papers (id, title, abstract), return the papers MOST semantically relevant to the "
            "query — by meaning, not just keyword overlap. Only include genuinely relevant papers "
            f"(up to {top}); if few are relevant, return few. For each, give a relevance score 0-1 and "
            "a one-line reason. Use ONLY the provided papers; never invent ids or papers."
        )
        user = f"QUERY: {query}\n\nPAPERS:\n{block}"
        schema = {"type": "object", "properties": {"ranked": {"type": "array", "items": {"type": "object",
                  "properties": {"id": {"type": "integer"}, "score": {"type": "number"}, "reason": {"type": "string"}},
                  "required": ["id"]}}}, "required": ["ranked"]}
        out = self._tool(system, user, schema, "rank_papers", max_tokens=min(2500, 300 + len(records) * 18))
        valid = {r["id"] for r in records}
        seen, ranked = set(), []
        for item in (out.get("ranked") or []):
            try:
                i = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if i in valid and i not in seen:
                seen.add(i)
                ranked.append({"id": i, "score": item.get("score"), "reason": (item.get("reason") or "").strip()})
        return ranked[:top]

    def tldr(self, title: str, abstract: str) -> dict:
        """Bir makalenin özetinden 1 cümlelik TL;DR + 3-4 anahtar nokta (sadık, uydurmasız)."""
        if not (abstract or title).strip():
            return {"tldr": "", "points": []}
        system = (
            "You are a biomedical research assistant. From the paper's title and abstract, produce a "
            "faithful TL;DR: one plain-language sentence capturing the main point, plus 3-4 short key "
            "takeaways (method/population, main finding, and any limitation if stated). Use ONLY what "
            "the abstract states; do NOT add facts, numbers or claims that are not there. If the "
            "abstract is missing, base it on the title and say so briefly."
        )
        user = f"TITLE: {title}\n\nABSTRACT: {abstract[:3000] or '(no abstract — use title)'}"
        schema = {"type": "object", "properties": {"tldr": {"type": "string"},
                  "points": {"type": "array", "items": {"type": "string"}}}, "required": ["tldr", "points"]}
        out = self._tool(system, user, schema, "summarize", max_tokens=600)
        return {"tldr": (out.get("tldr") or "").strip(),
                "points": [p.strip() for p in (out.get("points") or []) if p and p.strip()][:5]}

    def suggest_journals(self, title: str, abstract: str) -> list[dict]:
        """Başlık+özetten uygun hedef dergileri önerir (kapsam + uygunluk)."""
        system = (
            "You are a scholarly publishing advisor. Given a manuscript's title and abstract, suggest "
            "6-8 REAL, well-known peer-reviewed journals that are a plausible fit for submission. For "
            "each: 'name' (the journal), 'fit' (one line on why it fits this manuscript's topic and "
            "type), and 'scope' (a few words on the journal's scope/audience). Favor journals that "
            "genuinely publish this subject area. Do NOT invent fake journals; if unsure, prefer "
            "broader reputable journals in the field. Remind nothing — just the list."
        )
        user = f"TITLE: {title}\n\nABSTRACT: {abstract[:2500]}"
        schema = {"type": "object", "properties": {"journals": {"type": "array", "items": {"type": "object",
                  "properties": {"name": {"type": "string"}, "fit": {"type": "string"}, "scope": {"type": "string"}},
                  "required": ["name", "fit"]}}}, "required": ["journals"]}
        out = self._tool(system, user, schema, "suggest_journals", max_tokens=1500)
        res = []
        for j in (out.get("journals") or [])[:10]:
            nm = (j.get("name") or "").strip()
            if nm:
                res.append({"name": nm, "fit": (j.get("fit") or "").strip(), "scope": (j.get("scope") or "").strip()})
        return res
