"""Makale karşılaştırma matrisi.

Seçili kayıtlardan Claude ile YAPILANDIRILMIŞ alanlar çıkarır (çalışma tasarımı, örneklem/N,
ana sonuç, sınırlılıklar/rigor) ve yan yana tablo üretir (CSV'ye aktarılabilir). Derleme yazımı
ve kanıt-triyajı için. Grounded: yalnızca sağlanan özet/başlığa dayanır, uydurmaz; alan yoksa '—'.
"""
from __future__ import annotations

import anthropic

from .synthesis import _fmt_record

COLUMNS = [
    {"key": "design", "label": "Study design"},
    {"key": "sample", "label": "Sample (N / population)"},
    {"key": "outcome", "label": "Key outcome / finding"},
    {"key": "limitations", "label": "Limitations / rigor"},
]


class Comparator:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def run(self, records: list[dict]) -> dict:
        if not records:
            return {"columns": COLUMNS, "rows": []}
        n = len(records)
        block = "\n\n".join(_fmt_record(i, r) for i, r in enumerate(records, start=1))
        system = (
            "You are a systematic-review assistant building a comparison table. Each source is "
            "prefixed with its list number in brackets, e.g. [1], [2]. For EACH source, extract a "
            "structured summary based ONLY on its abstract/title: 'design' (study design, e.g. RCT, "
            "cohort, meta-analysis, review), 'sample' (the study sample size N and population), "
            "'outcome' (the key outcome / main finding), and 'limitations' (limitations or "
            "risk-of-bias / rigor signals). Set 'source' to the bracket list number (1.."
            f"{n}) — NOT the sample size. Be concise (a few words or one short phrase per field). "
            "Do NOT invent anything not present; if a field is not stated, return exactly '—' "
            "(an em dash), never 'unknown' or 'N/A'. Stay faithful to the source text."
        )
        user = f"Extract a comparison row for each of the {n} numbered sources ([1]..[{n}]).\n\nSOURCES:\n{block}"
        schema = {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "integer",
                                       "description": f"The source's bracket list number (1..{n}), NOT the sample size"},
                            "design": {"type": "string"},
                            "sample": {"type": "string"},
                            "outcome": {"type": "string"},
                            "limitations": {"type": "string"},
                        },
                        "required": ["source", "design", "sample", "outcome", "limitations"],
                    },
                },
            },
            "required": ["rows"],
        }
        msg = self.client.messages.create(
            model=self.model, max_tokens=min(4000, 400 + n * 160), system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{"name": "build_matrix", "description": "Return one row per source.",
                    "input_schema": schema}],
            tool_choice={"type": "tool", "name": "build_matrix"},
        )
        raw = {}
        for b in msg.content:
            if b.type == "tool_use":
                raw = b.input
                break
        # Sıra eşleştir: önce 'source' alanına göre; sağlıklı değilse gelen sırayla düş.
        raw_rows = raw.get("rows") or []
        by_n = {}
        for pos, row in enumerate(raw_rows, start=1):
            try:
                k = int(row.get("source"))
            except (TypeError, ValueError):
                k = pos
            if not (1 <= k <= n) or k in by_n:
                k = pos                      # 'source' bozuksa (ör. N yazmış) gelen sıraya düş
            if 1 <= k <= n and k not in by_n:
                by_n[k] = row

        def _cell(v: str) -> str:
            v = (v or "").strip()
            if not v or v.lower() in ("unknown", "n/a", "na", "not stated", "not reported",
                                      "<unknown>", "none", "-"):
                return "—"
            return v

        rows = []
        for i, rec in enumerate(records, start=1):
            r = by_n.get(i, {})
            rows.append({
                "n": i,
                "title": rec.get("title", ""),
                "authors": rec.get("authors", []),
                "year": rec.get("year", ""),
                "doi": rec.get("doi", ""),
                "pmid": rec.get("pmid", ""),
                "design": _cell(r.get("design")),
                "sample": _cell(r.get("sample")),
                "outcome": _cell(r.get("outcome")),
                "limitations": _cell(r.get("limitations")),
            })
        return {"columns": COLUMNS, "rows": rows}
