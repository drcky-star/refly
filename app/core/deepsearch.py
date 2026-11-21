"""Yinelemeli ('deep') literatür araması + dürüst kapsama tahmini.

Tek-geçiş arama yerine ÇOK TURLU: her tur sonuçlarının başlıkları Claude'a verilir, kaçırılmış
olabilecek YENİ arama açıları (eşanlamlı, alt-konu, yöntem, popülasyon) üretilir ve tekrar aranır.
Sonunda bulunanlar birleştirilir (dedup) + 'tahmini kapsama (recall) / kaçırmış olabileceklerim'.

İlke: yalnız GERÇEK makaleler (MultiSource: PubMed/CrossRef/Europe PMC/arXiv/S2); kapsama tahmini
bir AI ÖNGÖRÜSÜDÜR ve bilerek TEMKİNLİDİR — kara-kutu 'her şeyi buldum' iddiasının tersi.
"""
from __future__ import annotations

import anthropic

from .sources import _key


class DeepSearch:
    def __init__(self, multisource, api_key: str, model: str):
        self.ms = multisource
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def _tool(self, system, user, schema, name, max_tokens=400):
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

    def _followups(self, question, titles, prior, n=3):
        system = (
            "You expand a literature search. Given the research question, queries already tried, and "
            "titles found so far, propose up to N NEW short search queries (different synonyms, "
            "subtopics, methods, populations, adjacent concepts) likely to surface papers NOT yet "
            "found. Keep them concise and specific; do NOT repeat prior queries."
        )
        user = (f"QUESTION: {question}\nPRIOR QUERIES: {prior}\nTITLES SO FAR:\n"
                + "\n".join("- " + t for t in titles[:30]))
        schema = {"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
                  "required": ["queries"]}
        out = self._tool(system, user, schema, "followups")
        return [q.strip() for q in (out.get("queries") or []) if q and q.strip()][:n]

    def _coverage(self, question, titles):
        system = (
            "Estimate how well a set of found papers covers a research question. Return an honest "
            "coverage estimate 0-100 (recall-like) — be CONSERVATIVE, never overconfident — and a short "
            "note on which aspects/subtopics might still be missed. Base it only on the titles shown."
        )
        user = f"QUESTION: {question}\nFOUND ({len(titles)}):\n" + "\n".join("- " + t for t in titles[:60])
        schema = {"type": "object", "properties": {"coverage": {"type": "integer"}, "note": {"type": "string"}},
                  "required": ["coverage", "note"]}
        out = self._tool(system, user, schema, "coverage")
        cov = out.get("coverage")
        try:
            cov = max(0, min(100, int(cov)))
        except (TypeError, ValueError):
            cov = None
        return {"coverage": cov, "note": (out.get("note") or "").strip()}

    def run(self, question: str, rounds: int = 3, per_round: int = 8, cap: int = 60) -> dict:
        pool: dict[str, dict] = {}
        used: list[str] = []
        pending = [question]
        for rnd in range(rounds):
            if not pending or len(pool) >= cap:
                break
            q = pending.pop(0)
            used.append(q)
            for rec in self.ms.search(q, k=per_round):
                k = _key(rec)
                if k not in pool:
                    pool[k] = rec
            if rnd < rounds - 1 and len(pool) < cap:
                titles = [r.get("title", "") for r in pool.values()]
                for f in self._followups(question, titles, used):
                    if f not in used and f not in pending:
                        pending.append(f)
        recs = list(pool.values())[:cap]
        cov = self._coverage(question, [r.get("title", "") for r in recs]) if recs else {"coverage": 0, "note": ""}
        return {"query": question, "results": recs, "rounds": len(used), "queries": used,
                "coverage": cov["coverage"], "note": cov["note"]}
