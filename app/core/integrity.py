"""Yayın bütünlüğü — geri çekilme / endişe ifadesi / erratum tespiti.

PubMed kaydındaki PublicationType ve CommentsCorrections alanlarından okunur.
Ekstra ağ çağrısı gerekmez (kayıt zaten efetch ile gelmiştir).
"""
from __future__ import annotations

_RETRACTED_TYPES = {"Retracted Publication"}
_CONCERN_TYPES = {"Expression of Concern"}


def classify(rec: dict) -> dict | None:
    """Tek kayıt için bütünlük etiketi döner ya da None."""
    pts = set(rec.get("pub_types") or [])
    ccs = rec.get("corrections") or []
    if pts & _RETRACTED_TYPES or "RetractionIn" in ccs:
        return {"kind": "retracted", "severity": "high",
                "note": "PubMed bu makaleyi geri çekilmiş olarak işaretliyor."}
    if "ExpressionOfConcernIn" in ccs or pts & _CONCERN_TYPES:
        return {"kind": "concern", "severity": "high",
                "note": "Bu makaleye bir 'endişe ifadesi' bağlı."}
    if "ErratumIn" in ccs:
        return {"kind": "erratum", "severity": "low",
                "note": "Bu makaleye bir düzeltme (erratum) bağlı."}
    return None


def check_pmids(pmids: list[str], pm) -> dict[str, dict]:
    """PMID listesini PubMed'den taze çekip her biri için integrity etiketi döner.
    pm: pubmed.PubMed örneği. Döner: {pmid: {kind, severity, note}}."""
    out: dict[str, dict] = {}
    recs = pm.fetch([p for p in pmids if p])
    for r in recs:
        info = classify(r)
        if info:
            out[r["pmid"]] = info
    return out
