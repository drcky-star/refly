"""Opsiyonel çok kullanıcılı kimlik doğrulama.

REFLY_AUTH=1 ise: giriş zorunlu, her istek db.set_current_user ile kullanıcıya
bağlanır (veriler ayrılır). REFLY_AUTH=0 (varsayılan) ise hiçbir şey değişmez —
tek kullanıcı, girişsiz, mevcut davranış.
"""
from __future__ import annotations
import time
import secrets
import threading
from flask import (Blueprint, request, session, redirect, jsonify,
                   render_template_string, url_for)
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from .config import Config
from .core import db, mailer

auth_bp = Blueprint("auth", __name__)

# Basit IP bazlı hız sınırı (tek worker deployment için bellek içi yeterli).
_HITS: dict[str, list] = {}
_HLOCK = threading.Lock()


def _rate_limited(key: str, limit: int, window: int) -> bool:
    """key için son 'window' saniyede 'limit' aşıldıysa True."""
    now = time.monotonic()
    with _HLOCK:
        arr = [t for t in _HITS.get(key, []) if now - t < window]
        if len(arr) >= limit:
            _HITS[key] = arr
            return True
        arr.append(now)
        _HITS[key] = arr
        # ara sıra temizlik
        if len(_HITS) > 5000:
            for k in [k for k, v in _HITS.items() if not any(now - t < window for t in v)]:
                _HITS.pop(k, None)
    return False


def _client_ip() -> str:
    return request.remote_addr or "?"

_PAGE = """<!doctype html><html dir="{{ dir }}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Refly · {{ title }}</title>
<style>
 body{font-family:-apple-system,"Segoe UI",sans-serif;background:#f6f7f9;display:flex;
   align-items:center;justify-content:center;height:100vh;margin:0}
 .card{background:#fff;border:1px solid #e3e7ec;border-radius:14px;padding:30px;width:340px;
   box-shadow:0 6px 24px rgba(20,30,50,.06)}
 h1{font-size:22px;margin:0 0 4px;display:flex;align-items:center;gap:9px}
 h1 img{width:30px;height:30px;border-radius:7px}
 p.sub{color:#6b7785;margin:0 0 18px;font-size:13px}
 input{width:100%;padding:10px;border:1px solid #d8dee6;border-radius:8px;margin-bottom:10px;box-sizing:border-box;font-size:14px}
 button{width:100%;padding:11px;background:#6d28d9;color:#fff;border:0;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}
 .err{color:#c0392b;font-size:13px;margin-bottom:10px}
 .alt{text-align:center;margin-top:14px;font-size:13px}
 a{color:#6d28d9}
 .legal{text-align:center;margin-top:16px;font-size:11px;color:#9aa4b0}
 .legal a{color:#9aa4b0}
 .gbtn{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;padding:11px;
   background:#fff;color:#3c4043;border:1px solid #d8dee6;border-radius:8px;font-size:14px;
   font-weight:600;cursor:pointer;text-decoration:none;box-sizing:border-box}
 .gbtn:hover{background:#f7f8fa}
 .divider{display:flex;align-items:center;gap:10px;margin:14px 0;color:#9aa4b0;font-size:12px}
 .divider::before,.divider::after{content:"";flex:1;height:1px;background:#e3e7ec}
</style></head><body>
<form class="card" method="post">
  <h1><img src="/static/refly-icon-128.png" alt="">Refly</h1>
  <p class="sub">{{ subtitle }}</p>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  {% if google_on %}
  <a class="gbtn" href="{{ google_url }}">
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
    {{ tr.google }}
  </a>
  <div class="divider">{{ tr.or }}</div>
  {% endif %}
  {% if register %}<input name="name" placeholder="{{ tr.name }}" autofocus>{% endif %}
  <input name="email" type="email" placeholder="{{ tr.email }}" required {% if not register %}autofocus{% endif %}>
  <input name="password" type="password" placeholder="{{ tr.password }}" required>
  <button>{{ title }}</button>
  <div class="alt">{{ alt_text }} <a href="{{ alt_url }}">{{ alt_link }}</a></div>
  <div class="legal"><a href="/privacy" target="_blank">Privacy</a> · <a href="/terms" target="_blank">Terms</a></div>
</form></body></html>"""


# Giriş/kayıt sayfası çevirileri (dil çerezine göre)
AUTH_T = {
    "tr": {"login": "Giriş yap", "register": "Kayıt ol", "sub_login": "Kütüphanene eriş",
           "sub_reg": "Yeni Refly hesabı oluştur", "name": "Adınız", "email": "E-posta",
           "password": "Parola", "bad": "E-posta veya parola hatalı.",
           "weak": "Geçerli e-posta ve en az 8 karakter parola gerekli.",
           "exists": "Bu e-posta zaten kayıtlı.", "no_acc": "Hesabın yok mu?",
           "has_acc": "Zaten hesabın var mı?", "google": "Google ile devam et", "or": "veya"},
    "en": {"login": "Log in", "register": "Sign up", "sub_login": "Access your library",
           "sub_reg": "Create a new Refly account", "name": "Your name", "email": "Email",
           "password": "Password", "bad": "Wrong email or password.",
           "weak": "A valid email and a password of at least 8 characters are required.",
           "exists": "This email is already registered.", "no_acc": "Don't have an account?",
           "has_acc": "Already have an account?", "google": "Continue with Google", "or": "or"},
    "fr": {"login": "Se connecter", "register": "S'inscrire", "sub_login": "Accédez à votre bibliothèque",
           "sub_reg": "Créer un nouveau compte Refly", "name": "Votre nom", "email": "E-mail",
           "password": "Mot de passe", "bad": "E-mail ou mot de passe incorrect.",
           "weak": "Un e-mail valide et un mot de passe d'au moins 8 caractères sont requis.",
           "exists": "Cet e-mail est déjà enregistré.", "no_acc": "Pas encore de compte ?",
           "has_acc": "Vous avez déjà un compte ?", "google": "Continuer avec Google", "or": "ou"},
    "de": {"login": "Anmelden", "register": "Registrieren", "sub_login": "Auf Ihre Bibliothek zugreifen",
           "sub_reg": "Neues Refly-Konto erstellen", "name": "Ihr Name", "email": "E-Mail",
           "password": "Passwort", "bad": "Falsche E-Mail oder Passwort.",
           "weak": "Eine gültige E-Mail und ein Passwort mit mindestens 8 Zeichen sind erforderlich.",
           "exists": "Diese E-Mail ist bereits registriert.", "no_acc": "Noch kein Konto?",
           "has_acc": "Schon ein Konto?", "google": "Mit Google fortfahren", "or": "oder"},
    "ar": {"login": "تسجيل الدخول", "register": "إنشاء حساب", "sub_login": "ادخل إلى مكتبتك",
           "sub_reg": "إنشاء حساب Refly جديد", "name": "اسمك", "email": "البريد الإلكتروني",
           "password": "كلمة المرور", "bad": "بريد إلكتروني أو كلمة مرور غير صحيحة.",
           "weak": "مطلوب بريد إلكتروني صالح وكلمة مرور من 8 أحرف على الأقل.",
           "exists": "هذا البريد الإلكتروني مسجّل بالفعل.", "no_acc": "ليس لديك حساب؟",
           "has_acc": "لديك حساب بالفعل؟", "google": "المتابعة عبر Google", "or": "أو"},
}


def _tr():
    lang = request.cookies.get("lang", "en")   # varsayılan: İngilizce
    return AUTH_T.get(lang, AUTH_T["en"]), lang


# ------------------------------------------------- e-posta doğrulama
def verify_required() -> bool:
    """Doğrulama yalnızca hem açıkken hem de SMTP ayarlıyken zorunlu — aksi
    halde kimse kilitlenmez (yerel/geliştirme ya da eksik SMTP)."""
    return Config.REQUIRE_EMAIL_VERIFICATION and mailer.configured()


def _serializer():
    return URLSafeTimedSerializer(Config.SECRET_KEY, salt="refly-email-verify")


def make_verify_token(uid: int, email: str) -> str:
    return _serializer().dumps({"uid": uid, "email": email})


def read_verify_token(token: str, max_age: int = 3 * 24 * 3600):
    try:
        return _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def _public_base() -> str:
    return Config.PUBLIC_URL or request.host_url.rstrip("/")


# Doğrulama e-postası + sonuç sayfası çevirileri
VERIFY_T = {
    "en": {"subject": "Verify your Refly email", "hi": "Welcome to Refly",
           "body": "Please confirm your email address to activate automatic citation and start using your library.",
           "btn": "Verify my email", "expiry": "This link expires in 3 days.",
           "ok_title": "Email verified ✓", "ok_body": "Your email is confirmed. You can now use Refly fully.",
           "bad_title": "Link invalid or expired", "bad_body": "Please request a new verification email from the app.",
           "open": "Open Refly"},
    "tr": {"subject": "Refly e-postanı doğrula", "hi": "Refly'a hoş geldin",
           "body": "Otomatik referanslamayı etkinleştirip kütüphaneni kullanmaya başlamak için e-posta adresini onayla.",
           "btn": "E-postamı doğrula", "expiry": "Bu bağlantı 3 gün içinde geçersiz olur.",
           "ok_title": "E-posta doğrulandı ✓", "ok_body": "E-postan onaylandı. Artık Refly'ı tam kullanabilirsin.",
           "bad_title": "Bağlantı geçersiz ya da süresi dolmuş", "bad_body": "Uygulamadan yeni bir doğrulama e-postası iste.",
           "open": "Refly'ı aç"},
    "fr": {"subject": "Vérifiez votre e-mail Refly", "hi": "Bienvenue sur Refly",
           "body": "Confirmez votre adresse e-mail pour activer la citation automatique et utiliser votre bibliothèque.",
           "btn": "Vérifier mon e-mail", "expiry": "Ce lien expire dans 3 jours.",
           "ok_title": "E-mail vérifié ✓", "ok_body": "Votre e-mail est confirmé. Vous pouvez utiliser Refly.",
           "bad_title": "Lien invalide ou expiré", "bad_body": "Demandez un nouvel e-mail de vérification depuis l'application.",
           "open": "Ouvrir Refly"},
    "de": {"subject": "Bestätigen Sie Ihre Refly-E-Mail", "hi": "Willkommen bei Refly",
           "body": "Bitte bestätigen Sie Ihre E-Mail-Adresse, um die automatische Zitation zu aktivieren.",
           "btn": "E-Mail bestätigen", "expiry": "Dieser Link läuft in 3 Tagen ab.",
           "ok_title": "E-Mail bestätigt ✓", "ok_body": "Ihre E-Mail ist bestätigt. Sie können Refly nun nutzen.",
           "bad_title": "Link ungültig oder abgelaufen", "bad_body": "Fordern Sie eine neue Bestätigungs-E-Mail an.",
           "open": "Refly öffnen"},
    "ar": {"subject": "تأكيد بريد Refly الإلكتروني", "hi": "مرحبًا بك في Refly",
           "body": "يرجى تأكيد بريدك الإلكتروني لتفعيل الاقتباس التلقائي واستخدام مكتبتك.",
           "btn": "تأكيد بريدي", "expiry": "تنتهي صلاحية هذا الرابط خلال 3 أيام.",
           "ok_title": "تم تأكيد البريد ✓", "ok_body": "تم تأكيد بريدك. يمكنك الآن استخدام Refly بالكامل.",
           "bad_title": "الرابط غير صالح أو منتهي", "bad_body": "اطلب رسالة تأكيد جديدة من التطبيق.",
           "open": "افتح Refly"},
}

_VERIFY_EMAIL_HTML = """<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:480px;margin:auto;padding:24px">
  <h2 style="color:#6d28d9;margin:0 0 6px">📚 {hi}</h2>
  <p style="color:#374151;font-size:15px;line-height:1.5">{body}</p>
  <p style="margin:26px 0">
    <a href="{link}" style="background:#6d28d9;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:600;display:inline-block">{btn}</a>
  </p>
  <p style="color:#9ca3af;font-size:12px">{expiry}</p>
  <p style="color:#9ca3af;font-size:12px;word-break:break-all">{link}</p>
</div>"""

_VERIFY_RESULT = """<!doctype html><html dir="{dir}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Refly</title>
<style>body{{font-family:-apple-system,Segoe UI,sans-serif;background:#f6f7f9;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{background:#fff;border:1px solid #e3e7ec;border-radius:14px;padding:34px;width:360px;text-align:center;
box-shadow:0 6px 24px rgba(20,30,50,.06)}}
h1{{font-size:22px;margin:0 0 8px;color:{color}}}p{{color:#6b7785;font-size:14px;margin:0 0 20px}}
a.btn{{display:inline-block;background:#6d28d9;color:#fff;text-decoration:none;padding:11px 22px;border-radius:8px;font-weight:600}}
</style></head><body><div class="card">
<h1>{title}</h1><p>{body}</p><a class="btn" href="/">{open}</a></div></body></html>"""


def _send_verification(uid: int, email: str, name: str, lang: str):
    vt = VERIFY_T.get(lang, VERIFY_T["en"])
    link = f"{_public_base()}/verify/{make_verify_token(uid, email)}"
    html = _VERIFY_EMAIL_HTML.format(hi=vt["hi"], body=vt["body"], btn=vt["btn"],
                                     expiry=vt["expiry"], link=link)
    mailer.send(email, vt["subject"], html, text=f"{vt['body']}\n\n{link}")


# ------------------------------------------------- Google ile giriş (OAuth 2.0)
def google_enabled() -> bool:
    """CLIENT_ID + SECRET ayarlıysa 'Google ile devam et' gösterilir."""
    return bool(Config.GOOGLE_CLIENT_ID and Config.GOOGLE_CLIENT_SECRET)


def _google_redirect_uri() -> str:
    """Google konsolunda whitelist edilmesi GEREKEN tam callback URL'i."""
    return f"{_public_base()}/auth/google/callback"


def _login_user(uid: int, fallback_name: str = ""):
    """Oturumu kullanıcı için başlatır (sabitleme önlenir) ve ana sayfaya döner."""
    session.clear()
    session.permanent = True
    session["uid"] = uid
    u = db.get_user(uid)
    session["uname"] = (u and (u.get("name") or u.get("email"))) or fallback_name
    return redirect(url_for("refly.index"))


@auth_bp.route("/auth/google")
def google_login():
    """OAuth akışını başlat — Google'ın onay ekranına yönlendir."""
    if not google_enabled():
        return redirect(url_for("auth.login"))
    from urllib.parse import urlencode
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = {
        "client_id": Config.GOOGLE_CLIENT_ID,
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@auth_bp.route("/auth/google/callback")
def google_callback():
    """Google'dan dönüş — kod→token→kullanıcı bilgisi, hesabı aç/oluştur, giriş yap."""
    if not google_enabled():
        return redirect(url_for("auth.login"))
    # CSRF: state eşleşmeli
    state = request.args.get("state", "")
    if not state or state != session.pop("oauth_state", None):
        return redirect(url_for("auth.login"))
    if request.args.get("error") or not request.args.get("code"):
        return redirect(url_for("auth.login"))
    if _rate_limited(f"goog:{_client_ip()}", 20, 300):
        return redirect(url_for("auth.login"))
    import requests
    try:
        tok = requests.post("https://oauth2.googleapis.com/token", data={
            "code": request.args["code"],
            "client_id": Config.GOOGLE_CLIENT_ID,
            "client_secret": Config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": _google_redirect_uri(),
            "grant_type": "authorization_code",
        }, timeout=15)
        tok.raise_for_status()
        access = tok.json().get("access_token")
        if not access:
            return redirect(url_for("auth.login"))
        ui = requests.get("https://openidconnect.googleapis.com/v1/userinfo",
                          headers={"Authorization": f"Bearer {access}"}, timeout=15)
        ui.raise_for_status()
        info = ui.json()
    except Exception as e:
        print(f"[google-oauth] failed: {e}", flush=True)
        return redirect(url_for("auth.login"))

    email = (info.get("email") or "").strip().lower()
    if not email or not info.get("email_verified", False):
        return redirect(url_for("auth.login"))
    name = (info.get("name") or info.get("given_name") or "").strip()

    u = db.get_user_by_email(email)
    if u:
        uid = u["id"]
    else:
        # Google ile ilk giriş → hesabı oluştur (rastgele parola; kullanıcı hiç kullanmaz)
        uid = db.create_user(email, secrets.token_urlsafe(32), name, verified=True)
    if not db.is_verified(uid):        # Google e-postayı zaten doğruladı
        db.set_verified(uid, True)
    return _login_user(uid, name or email)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    tr, lang = _tr()
    error = None
    if request.method == "POST":
        if _rate_limited(f"login:{_client_ip()}", 10, 300):
            error = tr.get("too_many") or "Too many attempts — please wait a few minutes."
        else:
            u = db.verify_user(request.form.get("email", ""), request.form.get("password", ""))
            if u:
                return _login_user(u["id"], u["name"] or u["email"])
            error = tr["bad"]
    return render_template_string(_PAGE, title=tr["login"], subtitle=tr["sub_login"], tr=tr,
                                  dir="rtl" if lang == "ar" else "ltr", error=error, register=False,
                                  google_on=google_enabled(), google_url=url_for("auth.google_login"),
                                  alt_text=tr["no_acc"], alt_url="/register", alt_link=tr["register"])


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    tr, lang = _tr()
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        if not Config.REFLY_OPEN_REGISTRATION:
            error = "Registration is currently closed."
        elif _rate_limited(f"reg:{_client_ip()}", 5, 3600):
            error = tr.get("too_many") or "Too many attempts — please wait."
        elif not email or "@" not in email or len(pw) < 8:
            error = tr.get("weak") or "A valid email and a password of at least 8 characters are required."
        elif db.get_user_by_email(email):
            error = tr["exists"]
        else:
            name = request.form.get("name", "")[:80]
            uid = db.create_user(email, pw, name)
            # Doğrulama zorunlu ve owner değilse doğrulama e-postası gönder
            if verify_required() and not db.is_verified(uid):
                _send_verification(uid, email, name, lang)
            return _login_user(uid, (name or email)[:80])
    return render_template_string(_PAGE, title=tr["register"], subtitle=tr["sub_reg"], tr=tr,
                                  dir="rtl" if lang == "ar" else "ltr", error=error, register=True,
                                  google_on=google_enabled(), google_url=url_for("auth.google_login"),
                                  alt_text=tr["has_acc"], alt_url="/login", alt_link=tr["login"])


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@auth_bp.route("/verify/<token>")
def verify_email(token):
    _, lang = _tr()
    vt = VERIFY_T.get(lang, VERIFY_T["en"])
    d = read_verify_token(token)
    ok = bool(d and d.get("uid"))
    if ok:
        db.set_verified(int(d["uid"]), True)
    return render_template_string(
        _VERIFY_RESULT,
        dir="rtl" if lang == "ar" else "ltr",
        color="#16a34a" if ok else "#c0392b",
        title=vt["ok_title"] if ok else vt["bad_title"],
        body=vt["ok_body"] if ok else vt["bad_body"],
        open=vt["open"])


@auth_bp.post("/resend-verification")
def resend_verification():
    uid = session.get("uid")
    if not uid:
        return jsonify({"error": "Giriş gerekli"}), 401
    u = db.get_user(uid)
    if not u:
        return jsonify({"error": "Kullanıcı yok"}), 404
    if u.get("verified"):
        return jsonify({"ok": True, "already_verified": True})
    if _rate_limited(f"resend:{uid}", 3, 3600):
        return jsonify({"error": "Çok fazla istek — birkaç dakika bekle."}), 429
    _send_verification(uid, u["email"], u.get("name", ""), request.cookies.get("lang", "en"))
    return jsonify({"ok": True, "sent_to": u["email"]})


# Giriş gerektirmeyen uç noktalar (auth açıkken bile)
_OPEN = {"auth.login", "auth.register", "auth.logout", "auth.verify_email", "static",
         "auth.google_login", "auth.google_callback",
         "refly.addin_manifest", "refly.healthz", "refly.home", "refly.contact_sales",
         "refly.user_count",
         "refly.privacy", "refly.terms", "refly.api_billing_webhook",
         "refly.extension_info", "refly.extension_download",
         "refly.api_stripe_webhook", "refly.api_billing_config"}


def init_auth(app):
    if not Config.REFLY_AUTH:
        return

    @app.before_request
    def _require_login():
        db.set_current_user(None)
        ep = request.endpoint or ""
        if ep in _OPEN or ep.startswith("static"):
            return
        uid = session.get("uid")
        if not uid:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Giriş gerekli"}), 401
            # Anonim ziyaretçi ana sayfayı (/) açınca login'e atma; index() tanıtım sayfasını gösterir
            if ep == "refly.index":
                return
            return redirect(url_for("auth.login"))
        db.set_current_user(uid)
