"""AI kullanım beyanı (AI-use disclosure) üretici.

Dergilerin/kurumların giderek zorunlu tuttuğu "AI'yı nerede kullandım" beyanını,
kullanıcının Refly'da GERÇEKTEN kullandığı AI yardımlarına göre DÜRÜST biçimde üretir.
Şeffaflığa yaslanır — humanizer/gizleme araçlarının tam tersi; Refly'ın bütünlük ilkesiyle uyumlu.

Claude varsa dergiye/yerleşime göre metni cilalar; yoksa sağlam şablon döner (her zaman çalışır).
Beyan; AI'nın yazar OLMADIĞINI ve veri/sonuç/referans UYDURMADIĞINI, tüm çıktıların yazar
tarafından gözden geçirilip doğrulandığını ve sorumluluğun yazarda olduğunu açıkça belirtir.
"""
from __future__ import annotations

# Seçilebilir AI-yardım türleri → resmi akademik beyan cümlesi parçası (İngilizce).
USE_PHRASES = {
    "autocite":   "identify relevant published sources and insert in-text citations, which the "
                  "author(s) verified against the original publications",
    "rephrase":   "improve the clarity and academic tone of author-written text without altering "
                  "its meaning or its citations",
    "synthesis":  "help synthesize findings across author-selected published sources",
    "asklibrary": "answer questions grounded in the author(s)' own reference library",
    "audit":      "check that cited references exist and had not been retracted",
    "autotag":    "organize and categorize references",
}

_TOOL = "an AI assistant (Anthropic's Claude, via Refly)"


def build_statement(uses: list[str], tool: str = _TOOL) -> str:
    """Şablon tabanlı, her zaman geçerli DÜRÜST beyan (Claude gerektirmez)."""
    phrases = [USE_PHRASES[u] for u in uses if u in USE_PHRASES]
    if not phrases:
        phrases = ["assist with reference management"]
    body = phrases[0] if len(phrases) == 1 else "; ".join(phrases[:-1]) + "; and " + phrases[-1]
    return (
        f"During the preparation of this work, the author(s) used {tool} to {body}. "
        "After using this tool, the author(s) reviewed and edited the content as needed and "
        "take(s) full responsibility for the accuracy and integrity of the publication. "
        "No AI tool was listed as an author, and AI was not used to generate or fabricate data, "
        "results, or references."
    )


class Disclosure:
    """Claude ile dergi politikasına göre cilalanmış beyan (opsiyonel; hata olursa şablona düşer)."""

    def __init__(self, api_key: str, model: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def run(self, uses: list[str], journal: str = "", placement: str = "", tool: str = _TOOL) -> str:
        base = build_statement(uses, tool)
        system = (
            "You are an academic editor. Rewrite the provided AI-use disclosure statement so it is "
            "concise, formal and ready to paste, in English. Keep it HONEST and faithful to the "
            "listed uses — do NOT add any use that is not listed, and do NOT overstate or "
            "understate. ALWAYS keep an explicit author-responsibility clause and the statement "
            "that AI was not listed as an author and did not generate or fabricate data, results "
            "or references. Return ONLY the statement text."
        )
        ctx = f"Statement to refine:\n{base}"
        if journal:
            ctx += f"\n\nTailor the wording to the AI-disclosure policy of: {journal}."
        if placement:
            ctx += f"\n\nIt will appear in the '{placement}' section of the manuscript."
        schema = {"type": "object",
                  "properties": {"statement": {"type": "string"}},
                  "required": ["statement"]}
        try:
            msg = self.client.messages.create(
                model=self.model, max_tokens=600, system=system,
                messages=[{"role": "user", "content": ctx}],
                tools=[{"name": "return_statement", "description": "Return the disclosure statement.",
                        "input_schema": schema}],
                tool_choice={"type": "tool", "name": "return_statement"},
            )
            for b in msg.content:
                if b.type == "tool_use":
                    return (b.input.get("statement") or "").strip() or base
        except Exception as e:
            print(f"[disclosure] Claude atlandı, şablon kullanıldı: {e}", flush=True)
        return base
