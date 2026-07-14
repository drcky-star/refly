"""Kullanım kotaları — dışarı satış için plan bazlı limitler.

Asıl maliyet Claude kullanımı olduğundan 'autocite' ve 'autotag' aylık sayılır;
'refs' kütüphane boyutu (anlık stok) olarak sınırlanır. Limit değeri None = sınırsız.

- Auth KAPALIYSA (yerel tek kullanıcı) ya da kullanıcı yoksa: sınırsız (kota uygulanmaz).
- Auth AÇIKSA: her kullanıcının planına göre limit uygulanır.
Planlar REFLY_PLANS (JSON) ile ezilebilir.
"""
from __future__ import annotations
import json
import datetime as dt

from . import db
from ..config import Config

DEFAULT_PLANS = {
    "free":      {"autocite": 5,    "autotag": 10,   "refs": 150},     # deneme
    "student":   {"autocite": 25,   "autotag": 100,  "refs": 5000},    # ~$7/ay
    "pro":       {"autocite": 40,   "autotag": 200,  "refs": 50000},   # ~$14.99/ay
    "unlimited": {"autocite": None, "autotag": None, "refs": None},    # owner / kurumsal
}

_LABELS = {"autocite": "AI citations", "autotag": "AI auto-tag", "refs": "Library size"}


def plans() -> dict:
    if Config.REFLY_PLANS:
        try:
            merged = dict(DEFAULT_PLANS)
            merged.update(json.loads(Config.REFLY_PLANS))
            return merged
        except Exception:
            pass
    return DEFAULT_PLANS


def period() -> str:
    return dt.datetime.now().strftime("%Y-%m")


def _limits_for(uid) -> tuple[str, dict]:
    plan = db.get_plan(uid) if uid is not None else "unlimited"
    p = plans()
    return plan, p.get(plan, p["free"])


def _used(uid, metric: str) -> int:
    if metric == "refs":
        return db.count_active()          # anlık kütüphane boyutu
    return db.usage_get(uid, period(), metric)


def check(metric: str, amount: int = 1) -> tuple[bool, dict]:
    """Döner: (izin_var_mı, bilgi). uid yoksa (yerel) her zaman izinli/sınırsız."""
    uid = db.current_user()
    if uid is None:
        return True, {"plan": "unlimited", "metric": metric, "used": _used(None, metric),
                      "limit": None, "remaining": None, "unlimited": True}
    plan, lim = _limits_for(uid)
    limit = lim.get(metric)
    used = _used(uid, metric)
    if limit is None:
        return True, {"plan": plan, "metric": metric, "used": used, "limit": None,
                      "remaining": None, "unlimited": True}
    remaining = max(0, limit - used)
    ok = (used + amount) <= limit
    return ok, {"plan": plan, "metric": metric, "used": used, "limit": limit,
                "remaining": remaining, "unlimited": False}


def consume(metric: str, amount: int = 1):
    """Başarılı işlemden sonra kullanımı artırır (refs sayaç değil, atlanır)."""
    uid = db.current_user()
    if uid is None or metric == "refs":
        return
    db.usage_incr(uid, period(), metric, amount)


def message(info: dict) -> str:
    label = _LABELS.get(info.get("metric"), info.get("metric"))
    return (f"You've reached your {label} limit for this month "
            f"({info.get('used')}/{info.get('limit')} on the {info.get('plan')} plan). "
            f"Upgrade to continue.")


def summary() -> dict:
    """Geçerli kullanıcının plan + kullanım özeti (UI için)."""
    uid = db.current_user()
    plan, lim = _limits_for(uid)
    out = {"plan": plan, "period": period(), "metrics": {}}
    for m in ("autocite", "autotag", "refs"):
        out["metrics"][m] = {"used": _used(uid, m), "limit": lim.get(m),
                             "label": _LABELS[m]}
    return out
