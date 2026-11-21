"""Açık-erişim tam-metin PDF bulma (Unpaywall) — DOI → ücretsiz/legal PDF.

Unpaywall, yayıncıların ve depoların açık-erişim kopyalarının dizinidir (legal). DOI ile en iyi
OA konumunun PDF URL'ini bulur; sonra PDF'i indirir (yalnız gerçek PDF, boyut sınırlı). Bulduğu
dosya mevcut ek (attachment) mekanizmasına kaydedilir — Ask-library, karşılaştırma matrisi ve
tıkla-doğrula için tam metin sağlar. Hata → boş/None (sessiz).
"""
from __future__ import annotations

import requests

_UNPAYWALL = "https://api.unpaywall.org/v2/"


def find_pdf_url(doi: str, email: str) -> str:
    """DOI için en iyi açık-erişim PDF URL'ini döner; yoksa ''."""
    doi = (doi or "").strip().lower()
    if not doi or not email:
        return ""
    try:
        r = requests.get(_UNPAYWALL + doi, params={"email": email}, timeout=20)
        if r.status_code != 200:
            return ""
        d = r.json()
        best = d.get("best_oa_location") or {}
        if best.get("url_for_pdf"):
            return best["url_for_pdf"]
        for loc in (d.get("oa_locations") or []):
            if loc.get("url_for_pdf"):
                return loc["url_for_pdf"]
    except Exception:
        return ""
    return ""


_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def download(url: str, max_mb: int = 40) -> bytes | None:
    """URL'den PDF indirmeyi DENER. Yalnız gerçek PDF (%PDF- imzası) ve boyut sınırı içinde; aksi
    None (çoğu yayıncı bot indirmeyi engeller — o zaman çağıran taraf URL'i link olarak sunar)."""
    try:
        r = requests.get(url, timeout=40, headers={"User-Agent": _UA}, allow_redirects=True)
        if r.status_code != 200:
            return None
        data = r.content
        if not data or len(data) > max_mb * 1024 * 1024:
            return None
        ct = (r.headers.get("Content-Type") or "").lower()
        if data[:5] != b"%PDF-" and "pdf" not in ct:
            return None
        return data
    except Exception:
        return None
