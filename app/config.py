"""Refly yapılandırması — .env dosyasından okur."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _flag(name, default="0"):
    return os.getenv(name, default) in ("1", "true", "True", "yes")


class Config:
    BASE_DIR = BASE_DIR
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-degistir")

    # Çok kullanıcılı mod (publish için). Açıkken giriş zorunlu, veriler kullanıcıya göre ayrılır.
    REFLY_AUTH = _flag("REFLY_AUTH")

    # Üretim: HTTPS arkasında güvenli çerezler + güvenlik başlıkları.
    # Açıkça REFLY_PRODUCTION verilirse o geçerli; yoksa auth açıkken otomatik açık.
    REFLY_PRODUCTION = _flag("REFLY_PRODUCTION") if os.getenv("REFLY_PRODUCTION") is not None else REFLY_AUTH

    # Admin e-postaları (yedek/geri-yükleme gibi tüm-sistem işlemleri sadece bunlara)
    REFLY_ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("REFLY_ADMIN_EMAILS", "").split(",") if e.strip()]

    # Açık kayıt (kapatmak istersen 0)
    REFLY_OPEN_REGISTRATION = _flag("REFLY_OPEN_REGISTRATION", "1")

    # Güvenli oturum çerezi ayarları
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = REFLY_PRODUCTION      # HTTPS'te çerez sadece güvenli bağlantıda
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14  # 14 gün

    # Kullanım kotaları (dışarı satış). Plan limitlerini JSON ile ezebilirsin:
    # REFLY_PLANS='{"free":{"autocite":10,"autotag":10,"refs":200},"pro":{...}}'
    REFLY_PLANS = os.getenv("REFLY_PLANS", "")
    REFLY_DEFAULT_PLAN = os.getenv("REFLY_DEFAULT_PLAN", "free")
    REFLY_ADMIN_KEY = os.getenv("REFLY_ADMIN_KEY", "")   # kullanıcı planını değiştirmek için
    # Ödeme sağlayıcı (Stripe/iyzico) webhook'u için gizli anahtar (manuel/genel yol)
    REFLY_BILLING_SECRET = os.getenv("REFLY_BILLING_SECRET", "")

    # --- Stripe aboneliği (anahtarlar girilince OTOMATİK devreye girer; yoksa dormant) ---
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")           # sk_live_… / sk_test_…
    STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")  # pk_… (opsiyonel, UI)
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")    # whsec_…
    STRIPE_PRICE_STUDENT = os.getenv("STRIPE_PRICE_STUDENT", "")      # price_… (Student plan)
    STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")             # price_… (Pro plan)
    BILLING_SUCCESS_URL = os.getenv("REFLY_BILLING_SUCCESS_URL", "")  # boşsa istekten türetilir
    BILLING_CANCEL_URL = os.getenv("REFLY_BILLING_CANCEL_URL", "")

    # Claude — otomatik referanslama (iddia tespiti + doğrulama)
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    MODEL = os.getenv("REFLY_MODEL", "claude-sonnet-4-6")          # doğrulama (yargı ister)
    HELPER_MODEL = os.getenv("REFLY_HELPER_MODEL", "claude-haiku-4-5-20251001")  # iddia tespiti

    # PubMed / NCBI (opsiyonel ama önerilir — daha yüksek hız limiti)
    NCBI_EMAIL = os.getenv("NCBI_EMAIL", "")
    NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")

    # CrossRef nazik havuzu için e-posta
    CROSSREF_EMAIL = os.getenv("CROSSREF_EMAIL", "") or os.getenv("NCBI_EMAIL", "")

    # Kullanıcının kendi CSL stil klasörü (masaüstündeki klasör de olabilir)
    # Örn: /Users/kaan/Desktop/refly-stiller
    USER_CSL_DIR = os.getenv("REFLY_CSL_DIR", "")

    # --- E-posta gönderimi (SMTP) — doğrulama + bildirimler ---
    SMTP_HOST = os.getenv("REFLY_SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("REFLY_SMTP_PORT", "587") or "587")
    SMTP_USER = os.getenv("REFLY_SMTP_USER", "")
    SMTP_PASS = os.getenv("REFLY_SMTP_PASS", "")
    SMTP_FROM = os.getenv("REFLY_SMTP_FROM", "") or os.getenv("REFLY_SMTP_USER", "")
    SMTP_FROM_NAME = os.getenv("REFLY_SMTP_FROM_NAME", "Refly")
    # Herkese görünen uygulama adresi (doğrulama linkleri için). Boşsa istekten türetilir.
    PUBLIC_URL = os.getenv("REFLY_PUBLIC_URL", "").rstrip("/")
    # E-posta doğrulaması zorunlu mu? (SMTP yoksa otomatik kapalı — kimse kilitlenmez)
    REQUIRE_EMAIL_VERIFICATION = _flag("REFLY_REQUIRE_EMAIL_VERIFICATION")

    # --- Off-site yedek (S3 uyumlu: AWS S3 / DigitalOcean Spaces / Backblaze B2 / Cloudflare R2) ---
    BACKUP_S3_BUCKET = os.getenv("REFLY_BACKUP_S3_BUCKET", "")
    BACKUP_S3_ENDPOINT = os.getenv("REFLY_BACKUP_S3_ENDPOINT", "")   # Spaces/R2/B2 için; AWS'de boş
    BACKUP_S3_REGION = os.getenv("REFLY_BACKUP_S3_REGION", "")
    BACKUP_S3_ACCESS_KEY = os.getenv("REFLY_BACKUP_S3_ACCESS_KEY", "")
    BACKUP_S3_SECRET_KEY = os.getenv("REFLY_BACKUP_S3_SECRET_KEY", "")
    BACKUP_S3_PREFIX = os.getenv("REFLY_BACKUP_S3_PREFIX", "refly-backups")

    # --- Hata izleme (Sentry) — DSN verilirse otomatik açılır ---
    SENTRY_DSN = os.getenv("SENTRY_DSN", "")

    # İletişim / destek e-postası (yasal sayfalarda görünür)
    CONTACT_EMAIL = os.getenv("REFLY_CONTACT_EMAIL", "") or os.getenv("REFLY_SMTP_FROM", "") or "support@reflyapp.com"

    INSTANCE_DIR = BASE_DIR / "instance"
    ATTACH_DIR = BASE_DIR / "instance" / "attachments"   # referans PDF ekleri
    MAX_CONTENT_LENGTH = 60 * 1024 * 1024  # 60 MB (PDF ekleri için)
