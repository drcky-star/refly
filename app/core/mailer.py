"""E-posta gönderimi (SMTP) — e-posta doğrulama ve bildirimler için.

Standart kütüphane (smtplib) kullanır, ek bağımlılık yok. SMTP ayarlanmamışsa
sessizce devre dışıdır (configured() False döner) — yerel/geliştirmede kimse
kilitlenmez. Gönderim arka planda yapılır (istek yanıtını yavaşlatmaz).
"""
from __future__ import annotations
import ssl
import smtplib
import threading
from email.message import EmailMessage
from email.utils import formataddr

from ..config import Config


def configured() -> bool:
    """SMTP eksiksiz ayarlıysa True (host + kullanıcı + gönderen)."""
    return bool(Config.SMTP_HOST and Config.SMTP_USER and Config.SMTP_FROM)


def _send_sync(to: str, subject: str, html: str, text: str | None = None) -> bool:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((Config.SMTP_FROM_NAME, Config.SMTP_FROM))
    msg["To"] = to
    msg.set_content(text or "Bu e-postayı görüntülemek için HTML destekli bir istemci kullanın.")
    msg.add_alternative(html, subtype="html")
    ctx = ssl.create_default_context()
    port = Config.SMTP_PORT
    try:
        if port == 465:                      # örtük SSL
            with smtplib.SMTP_SSL(Config.SMTP_HOST, port, context=ctx, timeout=20) as s:
                s.login(Config.SMTP_USER, Config.SMTP_PASS)
                s.send_message(msg)
        else:                                # STARTTLS (587 vb.)
            with smtplib.SMTP(Config.SMTP_HOST, port, timeout=20) as s:
                s.ehlo()
                s.starttls(context=ctx)
                s.login(Config.SMTP_USER, Config.SMTP_PASS)
                s.send_message(msg)
        return True
    except Exception as e:                    # gönderim hatası kayıt/işlemi bozmasın
        print(f"[mailer] gönderilemedi ({to}): {e}", flush=True)
        return False


def send(to: str, subject: str, html: str, text: str | None = None, background: bool = True):
    """E-posta gönderir. Ayarlı değilse hiçbir şey yapmaz. background=True ise
    arka planda gönderir (istek yanıtını beklemez)."""
    if not configured() or not to:
        return
    if background:
        threading.Thread(target=_send_sync, args=(to, subject, html, text), daemon=True).start()
    else:
        _send_sync(to, subject, html, text)
