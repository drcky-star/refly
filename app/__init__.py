"""Refly Flask uygulama fabrikası."""
import secrets
from flask import Flask
from .config import Config

# home.html'in kullandığı CDN'ler dışında hiçbir dış kaynağa izin verme (XSS azaltma)
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com https://esm.sh; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.tailwindcss.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data:; "
    "connect-src 'self' https://esm.sh; "
    "frame-ancestors 'self'; base-uri 'self'; object-src 'none'; form-action 'self'"
)


def _init_sentry():
    """SENTRY_DSN ayarlıysa hata izlemeyi başlatır (yoksa hiçbir şey yapmaz)."""
    if not Config.SENTRY_DSN:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(
            dsn=Config.SENTRY_DSN,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.0,          # sadece hata izleme (performans örneklemesi kapalı)
            send_default_pii=False,          # kullanıcı verisi/PII gönderme
            environment="production" if Config.REFLY_PRODUCTION else "development",
        )
    except Exception as e:
        print(f"[sentry] başlatılamadı: {e}", flush=True)


def create_app():
    _init_sentry()
    app = Flask(__name__)
    app.config.from_object(Config)
    # Statik dosyalar (app.js/i18n.js/style.css) güncellenince tarayıcı ESKİ sürümü
    # önbellekten sunmasın — her istekte ETag ile doğrula (değişmemişse 304, ucuz).
    # (Aksi halde çeviri/UI güncellemeleri kullanıcıya geç yansıyordu.)
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    # Üretimde ters proxy (Render/Fly) arkasında gerçek istemci IP'si + https şeması.
    if Config.REFLY_PRODUCTION:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Üretimde varsayılan gizli anahtarla çalışmayı reddet (oturum sahteciliği önlenir).
    if Config.REFLY_PRODUCTION and Config.SECRET_KEY == "dev-degistir":
        raise RuntimeError(
            "Güvenlik: üretimde FLASK_SECRET_KEY ayarlanmalı. "
            "Örn: python -c \"import secrets;print(secrets.token_hex(32))\""
        )
    if app.config["SECRET_KEY"] == "dev-degistir":
        # yerel geliştirmede en azından süreç-ömürlü rastgele anahtar
        app.config["SECRET_KEY"] = secrets.token_hex(32)

    Config.INSTANCE_DIR.mkdir(exist_ok=True)
    Config.ATTACH_DIR.mkdir(parents=True, exist_ok=True)

    from .core import db
    db.init_db(Config.INSTANCE_DIR / "refly.db")

    from .core import backup
    backup.start_auto()

    from .routes import bp
    app.register_blueprint(bp)

    from .auth import auth_bp, init_auth
    app.register_blueprint(auth_bp)
    init_auth(app)

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Content-Security-Policy", _CSP)
        if Config.REFLY_PRODUCTION:
            resp.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000; includeSubDomains")
        # Word eklentisi Office iframe'inde açılır — çerçeveleme engelini kaldır
        from flask import request
        if request.path.startswith("/addin"):
            resp.headers.pop("X-Frame-Options", None)
            resp.headers["Content-Security-Policy"] = "frame-ancestors https://*.officeapps.live.com https://*.office.com 'self'"
        return resp

    return app
