"""Stripe abonelik iskeleti — .env'e Stripe anahtarları girilince OTOMATİK devreye girer.

Yapılandırılmamışsa (STRIPE_SECRET_KEY yok) her şey 'dormant' döner; UI upgrade butonları
"henüz aktif değil" mesajı gösterir, mevcut manuel /api/billing/webhook yolu çalışmaya devam eder.
Anahtarlar girildiğinde: checkout (abonelik ödemesi) + webhook (plan otomatik güncelleme) aktifleşir.

Gerekli env: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_STUDENT, STRIPE_PRICE_PRO.
`stripe` paketi requirements'ta; kurulu değilse configured() True olsa bile çağrılar {error} döner.
"""
from __future__ import annotations

from ..config import Config


def configured() -> bool:
    """Stripe checkout için asgari yapılandırma var mı (secret + en az bir price)."""
    return bool(Config.STRIPE_SECRET_KEY and (Config.STRIPE_PRICE_PRO or Config.STRIPE_PRICE_STUDENT))


def _stripe():
    import stripe                      # opsiyonel bağımlılık — sadece yapılandırılınca gerekir
    stripe.api_key = Config.STRIPE_SECRET_KEY
    return stripe


def _plan_to_price(plan: str) -> str:
    return {"student": Config.STRIPE_PRICE_STUDENT, "pro": Config.STRIPE_PRICE_PRO}.get(plan, "")


def _price_to_plan(price_id: str) -> str | None:
    m = {}
    if Config.STRIPE_PRICE_STUDENT:
        m[Config.STRIPE_PRICE_STUDENT] = "student"
    if Config.STRIPE_PRICE_PRO:
        m[Config.STRIPE_PRICE_PRO] = "pro"
    return m.get(price_id)


def public_config() -> dict:
    """UI için — ödeme aktif mi + hangi planlar satın alınabilir + publishable key."""
    return {
        "enabled": configured(),
        "publishable_key": Config.STRIPE_PUBLISHABLE_KEY,
        "buyable": [p for p in ("student", "pro") if _plan_to_price(p)],
    }


def create_checkout(email: str, plan: str, success_url: str, cancel_url: str) -> dict:
    """Bir plan için Stripe Checkout (abonelik) oturumu açar. Döner: {url} ya da {error}."""
    if not configured():
        return {"error": "Ödeme sistemi henüz yapılandırılmadı (Stripe anahtarları bekleniyor)."}
    price = _plan_to_price(plan)
    if not price:
        return {"error": f"Bu plan için fiyat tanımlı değil: {plan}"}
    try:
        s = _stripe()
        sess = s.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price, "quantity": 1}],
            customer_email=email or None,
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=True,
            metadata={"plan": plan, "email": email},
            subscription_data={"metadata": {"plan": plan, "email": email}},
        )
        return {"url": sess.url, "id": sess.id}
    except Exception as e:
        return {"error": f"Stripe: {e}"}


def _customer_email(s, customer_id: str) -> str:
    if not customer_id:
        return ""
    try:
        c = s.Customer.retrieve(customer_id)
        return (c.get("email") or "").lower()
    except Exception:
        return ""


def handle_webhook(payload: bytes, sig_header: str) -> dict:
    """Stripe webhook olayını imza doğrulayıp yorumlar.
    Döner: {email, plan, event} (plan uygulanmalı) | {event} (işlenmedi) | {error}."""
    if not Config.STRIPE_SECRET_KEY or not Config.STRIPE_WEBHOOK_SECRET:
        return {"error": "not configured"}
    try:
        s = _stripe()
        event = s.Webhook.construct_event(payload, sig_header, Config.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return {"error": f"signature: {e}"}

    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {})

    # Ödeme tamamlandı → metadata'daki plan (checkout'ta gömdük)
    if etype == "checkout.session.completed":
        email = (obj.get("customer_email")
                 or (obj.get("customer_details") or {}).get("email")
                 or (obj.get("metadata") or {}).get("email") or "").lower()
        plan = (obj.get("metadata") or {}).get("plan")
        if not plan:
            # price'tan türet
            try:
                items = _stripe().checkout.Session.list_line_items(obj.get("id"), limit=1)
                plan = _price_to_plan((items["data"][0]["price"]["id"]) if items.get("data") else "")
            except Exception:
                plan = None
        if email and plan:
            return {"email": email, "plan": plan, "event": etype}

    # Abonelik yenilendi/değişti → aktifse price'a göre plan
    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        status = obj.get("status")
        price_id = ""
        try:
            price_id = obj["items"]["data"][0]["price"]["id"]
        except Exception:
            pass
        plan = _price_to_plan(price_id)
        email = ((obj.get("metadata") or {}).get("email") or _customer_email(_stripe(), obj.get("customer"))).lower()
        if email and plan and status in ("active", "trialing"):
            return {"email": email, "plan": plan, "event": etype}
        if email and status in ("canceled", "unpaid", "incomplete_expired"):
            return {"email": email, "plan": "free", "event": etype}

    # Abonelik iptal → free'ye düşür
    if etype == "customer.subscription.deleted":
        email = ((obj.get("metadata") or {}).get("email") or _customer_email(_stripe(), obj.get("customer"))).lower()
        if email:
            return {"email": email, "plan": "free", "event": etype}

    return {"event": etype}   # işlenmeyen olay — 200 dön, yok say
