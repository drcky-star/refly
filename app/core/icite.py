"""iCite (NIH) — PMID başına atıf sayısı + etki ölçütü (RCR).

Önerilen makaleleri ne kadar etkili olduklarına göre sıralamak için kullanılır.
Erişilemezse boş sözlük döner (özellik opsiyoneldir).
"""
from __future__ import annotations
import requests

_API = "https://icite.od.nih.gov/api/pubs"


def metrics(pmids: list[str]) -> dict[str, dict]:
    """Döner: {pmid: {"citations": int, "rcr": float|None}}."""
    pmids = [p for p in pmids if p]
    if not pmids:
        return {}
    out: dict[str, dict] = {}
    try:
        for i in range(0, len(pmids), 100):
            batch = pmids[i:i + 100]
            r = requests.get(_API, params={"pmids": ",".join(batch)}, timeout=20)
            if r.status_code != 200:
                continue
            for d in r.json().get("data", []):
                pid = str(d.get("pmid", ""))
                if pid:
                    out[pid] = {"citations": d.get("citation_count") or 0,
                                "rcr": d.get("relative_citation_ratio")}
    except Exception:
        pass
    return out
