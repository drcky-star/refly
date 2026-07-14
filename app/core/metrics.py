"""Dergi metrikleri — OpenAlex API (ücretsiz, anahtar gerekmez). ISSN ya da ad -> bibliyometri."""
from __future__ import annotations
import requests

_API = "https://api.openalex.org/sources"


def _tier(impact: float) -> str:
    """Impact (2 yıllık ortalama atıf) değerinden kaba tier etiketi. Gerçek Scimago çeyreği değildir."""
    if impact >= 10:
        return "Çok yüksek"
    if impact >= 5:
        return "Yüksek"
    if impact >= 2.5:
        return "Orta"
    if impact >= 1:
        return "Mütevazı"
    return "Düşük"


def _map(s: dict, fallback_issn: str = "") -> dict:
    """OpenAlex source objesini Refly metrik sözlüğüne çevirir."""
    stats = s.get("summary_stats") or {}
    impact = round(float(stats.get("2yr_mean_citedness") or 0.0), 1)
    return {
        "name": s.get("display_name", ""),
        "issn": s.get("issn_l") or fallback_issn,
        "publisher": s.get("host_organization_name") or "",
        "impact": impact,
        "h_index": stats.get("h_index"),
        "works_count": s.get("works_count"),
        "tier": _tier(impact),
        "openalex_id": (s.get("ids") or {}).get("openalex", ""),
        "source": "openalex",
    }


def journal_metrics(issn: str = "", name: str = "", email: str = "") -> dict | None:
    """ISSN ya da dergi adından OpenAlex bibliyometrik metriklerini döner. Bulunamazsa None."""
    mailto = email or "refly@example.com"
    try:
        if issn:
            r = requests.get(f"{_API}/issn:{issn.strip()}", params={"mailto": mailto}, timeout=20)
            if r.status_code != 200:
                return None
            return _map(r.json(), fallback_issn=issn.strip())
        if name:
            r = requests.get(_API, params={"search": name, "per_page": 1, "mailto": mailto}, timeout=20)
            if r.status_code != 200:
                return None
            results = r.json().get("results", [])
            if not results:
                return None
            return _map(results[0])
        return None
    except Exception:
        return None


def badge(m: dict) -> str:
    """Kısa rozet metni, ör. 'IF~74.7 · h=1201'. Eksik veride güvenli."""
    if not m:
        return ""
    parts = []
    impact = m.get("impact")
    if impact:
        parts.append(f"IF~{impact}")
    h = m.get("h_index")
    if h:
        parts.append(f"h={h}")
    return " · ".join(parts)
