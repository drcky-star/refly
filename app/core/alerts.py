"""Konu alarmları — kayıtlı aramalarda yeni makale tespiti + e-posta özeti (digest).

Her kayıtlı arama PubMed'de çalıştırılır; daha önce görülmeyen (last_ids'de olmayan)
makaleler 'yeni' sayılır. İlk çalıştırma bir temel (baseline) kurar (alarm üretmez);
sonraki çalıştırmalarda yeni çıkanlar bulunur ve e-posta ayarlıysa özet gönderilir.
"""
from __future__ import annotations
import datetime as dt
import json

from . import db, mailer


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")


def _digest_html(query: str, recs: list[dict]) -> str:
    rows = []
    for r in recs:
        au = ", ".join((r.get("authors") or [])[:3])
        link = (f"https://pubmed.ncbi.nlm.nih.gov/{r.get('pmid')}/" if r.get("pmid")
                else (f"https://doi.org/{r.get('doi')}" if r.get("doi") else "#"))
        rows.append(
            f'<li style="margin:0 0 12px">'
            f'<a href="{link}" style="color:#4f46e5;font-weight:600;text-decoration:none">{r.get("title", "")}</a>'
            f'<div style="color:#64748b;font-size:13px">{au} · {r.get("iso") or r.get("journal", "")} · {r.get("year", "")}</div></li>')
    return (f'<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:560px">'
            f'<h2 style="color:#0f1b33">📚 Refly — yeni makaleler</h2>'
            f'<p style="color:#475569">"<b>{query}</b>" aramasında <b>{len(recs)}</b> yeni makale bulundu:</p>'
            f'<ul style="padding-left:18px">{"".join(rows)}</ul>'
            f'<p style="font-size:12px;color:#94a3b8">Bu özet Refly konu alarmından gönderildi.</p></div>')


def run_search(pm, search: dict, send_email: bool = True) -> dict:
    """Kayıtlı aramayı çalıştırır. Döner: {new:[recs], n_new, checked, first_run}."""
    query = (search.get("query") or "").strip()
    checked = _now_iso()
    try:
        pmids = pm.search(query, retmax=25)
    except Exception:
        pmids = []
    try:
        seen = set(json.loads(search.get("last_ids") or "[]"))
    except Exception:
        seen = set()

    if not seen:                       # ilk kontrol → baseline kur (alarm üretme)
        db.update_search_seen(search["id"], pmids[:100], checked)
        return {"new": [], "n_new": 0, "checked": checked, "first_run": True}

    new_ids = [p for p in pmids if p not in seen][:15]
    recs = pm.fetch(new_ids) if new_ids else []
    merged = list(dict.fromkeys(pmids + list(seen)))[:120]   # görülenleri güncelle
    db.update_search_seen(search["id"], merged, checked)

    mail_to = (search.get("email") or "").strip()
    if recs and send_email and mail_to and mailer.configured():
        try:
            mailer.send(mail_to, f'Refly: "{query}" — {len(recs)} yeni makale',
                        _digest_html(query, recs))
        except Exception:
            pass
    return {"new": recs, "n_new": len(recs), "checked": checked, "first_run": False}
