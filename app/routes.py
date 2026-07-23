"""Refly HTTP uçları — kütüphane, import, formatlama, dedup, export."""
from __future__ import annotations
import io
import threading
import uuid
from flask import Blueprint, render_template, request, jsonify, send_file, session

from .config import Config
from .core import (db, pubmed, crossref, references as ref, csl, docx_export,
                   integrity, pdf_import, manuscript, autocite, enrich, icite, tagger,
                   backup, quota, mailer, sources, audit, synthesis, library_qa, metrics,
                   alerts, billing)

bp = Blueprint("refly", __name__)

# Sık kullanılan stiller (kullanıcının yerel .csl dosyaları bunlara eklenir)
COMMON_STYLES = [
    ("vancouver", "Vancouver (numaralı)"),
    ("ama", "AMA / JAMA"),
    ("nejm", "NEJM"),
    ("the-lancet", "The Lancet"),
    ("bmj", "BMJ"),
    ("nature", "Nature"),
    ("apa", "APA 7"),
    ("harvard", "Harvard"),
    ("chicago", "Chicago (author-date)"),
    ("ieee", "IEEE"),
    ("elsevier-vancouver", "Elsevier (Vancouver)"),
]


@bp.route("/")
def index():
    # Anonim ziyaretçi → premium tanıtım (landing) sayfası; giriş yapmış kullanıcı → uygulama
    if Config.REFLY_AUTH and not session.get("uid"):
        return send_file(str(Config.BASE_DIR / "app" / "static" / "home.html"))
    return render_template("index.html", csl_ok=csl.available(),
                           user_csl=Config.USER_CSL_DIR or "",
                           auth_on=Config.REFLY_AUTH,
                           uname=session.get("uname", ""))


# ----------------------------------------------------------- Word eklentisi
def _base_url():
    # REFLY_PUBLIC_URL ayarlıysa (ör. https://reflyapp.com) onu kullan; yoksa istek host'u.
    return Config.PUBLIC_URL or request.host_url.rstrip("/")


@bp.get("/home")
def home():
    """Premium tanıtım/dashboard anasayfası (React + Tailwind + Framer Motion)."""
    return send_file(str(Config.BASE_DIR / "app" / "static" / "home.html"))


def _legal_page(fname: str):
    path = Config.BASE_DIR / "app" / "static" / fname
    html = path.read_text(encoding="utf-8").replace("{{CONTACT}}", Config.CONTACT_EMAIL)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@bp.get("/privacy")
def privacy():
    """Gizlilik Politikası (herkese açık — ödeme sağlayıcıları ve KVKK/GDPR için)."""
    return _legal_page("privacy.html")


@bp.get("/terms")
def terms():
    """Kullanım Şartları (herkese açık)."""
    return _legal_page("terms.html")


@bp.get("/robots.txt")
def robots_txt():
    """Arama motorları için — pazarlama sayfaları taransın, uygulama/API/auth taranmasın."""
    body = ("User-agent: *\n"
            "Disallow: /api/\n"
            "Disallow: /login\n"
            "Disallow: /register\n"
            "Disallow: /logout\n"
            "Disallow: /verify\n"
            "Disallow: /addin\n"
            "Disallow: /auth/\n"
            f"Sitemap: {_base_url()}/sitemap.xml\n")
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}


@bp.get("/sitemap.xml")
def sitemap_xml():
    """Herkese açık pazarlama sayfaları."""
    base = _base_url()
    pages = ["/", "/home", "/privacy", "/terms"]
    items = "".join(f"<url><loc>{base}{p}</loc><changefreq>weekly</changefreq></url>" for p in pages)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + items + '</urlset>')
    return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}


@bp.post("/api/contact-sales")
def contact_sales():
    """Özel/Kurumsal plan talebi → support@reflyapp.com'a iletir (herkese açık).

    SMTP ayarlıysa e-posta gönderir (delivered=True); değilse delivered=False döner
    ve istemci mailto:support@reflyapp.com yedeğine geçer."""
    from .auth import _rate_limited, _client_ip
    if _rate_limited(f"sales:{_client_ip()}", 5, 3600):
        return jsonify({"ok": False, "error": "rate"}), 429
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()[:120]
    email = (data.get("email") or "").strip()[:200]
    company = (data.get("company") or "").strip()[:160]
    message = (data.get("message") or "").strip()[:4000]
    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "email"}), 400
    if not mailer.configured():
        # Backend e-posta ayarlı değil → istemci mailto ile göndersin
        return jsonify({"ok": True, "delivered": False})
    import html as _html
    esc = lambda s: _html.escape(s or "")
    body_html = ("<h3>Refly — Custom / Enterprise plan inquiry</h3>"
                 f"<p><b>Name:</b> {esc(name)}</p>"
                 f"<p><b>Work email:</b> {esc(email)}</p>"
                 f"<p><b>Company:</b> {esc(company)}</p>"
                 f"<p><b>Message:</b><br>{esc(message).replace(chr(10), '<br>')}</p>")
    text = (f"Custom / Enterprise plan inquiry\nName: {name}\nWork email: {email}\n"
            f"Company: {company}\n\n{message}")
    mailer.send(Config.CONTACT_EMAIL, f"[Refly] Custom plan inquiry — {name or email}",
                body_html, text=text, reply_to=email)
    return jsonify({"ok": True, "delivered": True})


@bp.get("/api/user-count")
def user_count():
    """Kayıtlı kullanıcı sayısı (GERÇEK veri: users tablosundaki tüm hesaplar, ücretli/ücretsiz
    fark etmez). 60 sn önbellekli; yeni kayıt olunca anında güncellenir. Herkese açık."""
    return jsonify({"count": db.count_users_cached()})


@bp.get("/api/me")
def api_me():
    """Geçerli kullanıcı durumu — arayüz doğrulama/onboarding rozetleri için."""
    uid = db.current_user()
    need = Config.REQUIRE_EMAIL_VERIFICATION and mailer.configured()
    if uid is None:                       # auth kapalı = yerel tek kullanıcı
        return jsonify({"auth": False, "verified": True, "verify_required": False,
                        "refs": db.count_active()})
    u = db.get_user(uid) or {}
    return jsonify({"auth": True, "email": u.get("email", ""), "name": u.get("name", ""),
                    "verified": bool(u.get("verified")), "verify_required": need,
                    "plan": db.get_plan(uid), "refs": db.count_active()})


@bp.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "refs": db.count_active(), "csl": csl.available()})


@bp.get("/addin")
def addin_taskpane():
    return render_template("addin_taskpane.html", base=_base_url())


@bp.get("/addin/manifest.xml")
def addin_manifest():
    base = _base_url()
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<OfficeApp xmlns="http://schemas.microsoft.com/office/appforoffice/1.1"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:bt="http://schemas.microsoft.com/office/officeappbasictypes/1.0"
  xsi:type="TaskPaneApp">
  <Id>b6f2e7a4-9c1d-4f3a-8e21-0a1b2c3d4e5f</Id>
  <Version>1.0.0.0</Version>
  <ProviderName>Refly</ProviderName>
  <DefaultLocale>tr-TR</DefaultLocale>
  <DisplayName DefaultValue="Refly"/>
  <Description DefaultValue="Refly referans yöneticisi — Word içinde canlı atıf ve kaynakça."/>
  <IconUrl DefaultValue="{base}/static/refly-icon-64.png"/>
  <HighResolutionIconUrl DefaultValue="{base}/static/refly-icon-128.png"/>
  <Hosts><Host Name="Document"/></Hosts>
  <DefaultSettings><SourceLocation DefaultValue="{base}/addin"/></DefaultSettings>
  <Permissions>ReadWriteDocument</Permissions>
</OfficeApp>"""
    return xml, 200, {"Content-Type": "application/xml"}


# ----------------------------------------------------------- koleksiyonlar
# ----------------------------------------------------------- kota
def _quota_block(metric, amount=1):
    """Kota aşıldıysa 402 yanıtı döner, yoksa None."""
    ok, info = quota.check(metric, amount)
    if not ok:
        return jsonify({"error": quota.message(info), "quota": info}), 402
    return None


def _verify_block():
    """Doğrulama zorunluyken doğrulanmamış kullanıcının maliyetli işlemini engeller.
    (Ücretsiz auto-cite'lerin sahte hesaplarla sömürülmesini önler.)"""
    if not (Config.REQUIRE_EMAIL_VERIFICATION and mailer.configured()):
        return None
    uid = db.current_user()
    if uid is not None and not db.is_verified(uid):
        return jsonify({"error": "Lütfen önce e-posta adresini doğrula — bağlantı e-postana gönderildi.",
                        "need_verification": True}), 403
    return None


@bp.get("/api/usage")
def api_usage():
    return jsonify(quota.summary())


def _secret_ok(given, expected) -> bool:
    """Zamanlama-güvenli gizli anahtar karşılaştırması."""
    import hmac
    if not expected or not given:
        return False
    return hmac.compare_digest(str(given), str(expected))


@bp.post("/api/admin/plan")
def api_admin_plan():
    """Kullanıcı planını değiştir (REFLY_ADMIN_KEY ile korunur — ödeme webhook'undan çağrılır)."""
    d = request.json or {}
    if not _secret_ok(d.get("key"), Config.REFLY_ADMIN_KEY):
        return jsonify({"error": "yetkisiz"}), 403
    u = db.get_user_by_email(d.get("email", ""))
    if not u:
        return jsonify({"error": "kullanıcı yok"}), 404
    db.set_plan(u["id"], d.get("plan", "free"))
    return jsonify({"ok": True, "email": u["email"], "plan": d.get("plan", "free")})


@bp.post("/api/billing/webhook")
def api_billing_webhook():
    """Ödeme sağlayıcı (Stripe/iyzico) başarılı ödeme sonrası çağırır — kullanıcının
    planını yükseltir/düşürür. Güvenlik: REFLY_BILLING_SECRET (yoksa REFLY_ADMIN_KEY).
    Beklenen: {email, plan}  (plan: free|student|pro|unlimited). Secret X-Refly-Secret
    başlığında ya da gövdede. Sağlayıcıyı buraya kendi ince handler'ınla bağlarsın."""
    secret = Config.REFLY_BILLING_SECRET or Config.REFLY_ADMIN_KEY
    d = request.json or {}
    given = request.headers.get("X-Refly-Secret") or d.get("secret")
    if not _secret_ok(given, secret):
        return jsonify({"error": "yetkisiz"}), 403
    email = (d.get("email") or "").strip().lower()
    plan = d.get("plan", "pro")
    if plan not in quota.plans():
        return jsonify({"error": f"geçersiz plan: {plan}"}), 400
    u = db.get_user_by_email(email)
    if not u:
        return jsonify({"error": "kullanıcı bulunamadı", "email": email}), 404
    db.set_plan(u["id"], plan)
    return jsonify({"ok": True, "email": email, "plan": plan})


# --------------------------------------------------- Stripe aboneliği (iskelet)
@bp.get("/api/billing/config")
def api_billing_config():
    """UI için: ödeme aktif mi + satın alınabilir planlar + publishable key."""
    return jsonify(billing.public_config())


@bp.post("/api/billing/checkout")
def api_billing_checkout():
    """Bir plan için Stripe Checkout oturumu açar, ödeme sayfasının URL'sini döner.
    Giriş gerekli — ödeme geçerli kullanıcının e-postasına bağlanır."""
    plan = ((request.json or {}).get("plan") or "").strip()
    if plan not in ("student", "pro"):
        return jsonify({"error": "Geçersiz plan"}), 400
    email = db.current_user_email()
    if not email:
        return jsonify({"error": "Önce giriş yap"}), 401
    base = _base_url()
    success = Config.BILLING_SUCCESS_URL or f"{base}/?upgraded=1"
    cancel = Config.BILLING_CANCEL_URL or f"{base}/home#pricing"
    res = billing.create_checkout(email, plan, success, cancel)
    if res.get("error"):
        return jsonify(res), 400
    return jsonify(res)


@bp.post("/api/billing/stripe-webhook")
def api_stripe_webhook():
    """Stripe olay webhook'u — imza doğrulanır, aboneliğe göre plan otomatik güncellenir.
    Stripe panelinde bu URL'yi + STRIPE_WEBHOOK_SECRET'i tanımla."""
    res = billing.handle_webhook(request.get_data(), request.headers.get("Stripe-Signature", ""))
    if res.get("error"):
        return jsonify(res), 400
    if res.get("email") and res.get("plan"):
        u = db.get_user_by_email(res["email"])
        if u:
            db.set_plan(u["id"], res["plan"])
            return jsonify({"ok": True, "email": res["email"], "plan": res["plan"]})
        return jsonify({"ok": True, "note": "user not found yet", "email": res["email"]})
    return jsonify({"ok": True, "event": res.get("event")})


@bp.get("/api/collections")
def api_collections():
    return jsonify({"collections": db.list_collections(), "total": db.count_active(),
                    "trash": db.count_deleted(), "tags": db.list_tags(),
                    "usage": quota.summary()})


@bp.post("/api/collections")
def api_create_collection():
    name = (request.json or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "İsim gerekli"}), 400
    return jsonify({"id": db.create_collection(name)})


@bp.post("/api/collections/<int:cid>/rename")
def api_rename_collection(cid):
    name = (request.json or {}).get("name", "").strip()
    db.rename_collection(cid, name)
    return jsonify({"ok": True})


@bp.post("/api/collections/<int:cid>/delete")
def api_delete_collection(cid):
    db.delete_collection(cid)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ referanslar
@bp.get("/api/refs")
def api_refs():
    coll = request.args.get("collection", "all")
    search = request.args.get("search", "").strip()
    tag = request.args.get("tag", "").strip()
    starred = request.args.get("starred") == "1"
    return jsonify({"refs": db.list_refs(coll, search, tag=tag, starred=starred)})


@bp.post("/api/refs/<int:rid>/star")
def api_star(rid):
    return jsonify({"starred": db.toggle_star(rid)})


# ------------------------------------------------------------- PDF ekleri
def _save_pdf(rid: int, data: bytes) -> str:
    Config.ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"ref{rid}_{uuid.uuid4().hex[:8]}.pdf"
    (Config.ATTACH_DIR / fname).write_bytes(data)
    db.set_attachment(rid, fname)
    return fname


@bp.post("/api/refs/<int:rid>/attach")
def api_attach(rid):
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "PDF yok"}), 400
    old = db.get_attachment(rid)
    if old:
        (Config.ATTACH_DIR / old).unlink(missing_ok=True)
    _save_pdf(rid, f.read())
    return jsonify({"ok": True})


@bp.get("/api/refs/<int:rid>/attachment")
def api_attachment(rid):
    fname = db.get_attachment(rid)
    if not fname or not (Config.ATTACH_DIR / fname).exists():
        return jsonify({"error": "Ek bulunamadı"}), 404
    return send_file(str(Config.ATTACH_DIR / fname), mimetype="application/pdf")


@bp.post("/api/refs/<int:rid>/detach")
def api_detach(rid):
    old = db.get_attachment(rid)
    if old:
        (Config.ATTACH_DIR / old).unlink(missing_ok=True)
    db.set_attachment(rid, None)
    return jsonify({"ok": True})


@bp.get("/api/refs/<int:rid>")
def api_ref(rid):
    r = db.get_ref(rid)
    return jsonify(r) if r else (jsonify({"error": "bulunamadı"}), 404)


@bp.post("/api/refs")
def api_add_ref():
    data = request.json or {}
    if not data.get("title"):
        return jsonify({"error": "Başlık gerekli"}), 400
    blk = _quota_block("refs")
    if blk:
        return blk
    return jsonify({"id": db.add_ref(data)})


@bp.put("/api/refs/<int:rid>")
def api_update_ref(rid):
    db.update_ref(rid, request.json or {})
    return jsonify({"ok": True})


@bp.post("/api/refs/<int:rid>/delete")
def api_delete_ref(rid):
    db.delete_ref(rid)
    return jsonify({"ok": True})


@bp.post("/api/refs/move")
def api_move_refs():
    d = request.json or {}
    db.move_refs(d.get("ids", []), d.get("collection"))
    return jsonify({"ok": True})


# ------------------------------------------------------------------- import
def _pm():
    return pubmed.PubMed(Config.NCBI_EMAIL, Config.NCBI_API_KEY)


def _rec_keys(rec: dict) -> set[str]:
    doi = (rec.get("doi") or "").lower()
    pmid = rec.get("pmid") or ""
    title = "".join(ch for ch in (rec.get("title") or "").lower() if ch.isalnum())[:60]
    return {k for k in (doi, pmid, title) if k}


def _split_new(items: list[dict]):
    """Kütüphanede zaten olanları ayıklar. Döner: (yeni, atlanan_sayısı)."""
    existing = db.existing_keys()
    new, skipped = [], 0
    seen = set()
    for it in items:
        keys = _rec_keys(it)
        if keys & existing or keys & seen:
            skipped += 1
            continue
        seen |= keys
        new.append(it)
    return new, skipped


def _fetch_one(raw: str) -> dict | None:
    raw = raw.strip()
    if crossref.clean_doi(raw):
        return crossref.fetch_doi(raw, Config.CROSSREF_EMAIL)
    pid = raw.replace("PMID:", "").strip()
    if pid.isdigit():
        recs = _pm().fetch([pid])
        return recs[0] if recs else None
    return None


@bp.post("/api/import/identifier")
def api_import_identifier():
    """DOI veya PMID otomatik algılar, kaydı çekip kütüphaneye ekler."""
    d = request.json or {}
    raw = (d.get("value") or "").strip()
    coll = d.get("collection")
    if not raw:
        return jsonify({"error": "DOI veya PMID girin"}), 400
    if not (crossref.clean_doi(raw) or raw.replace("PMID:", "").strip().isdigit()):
        return jsonify({"error": "Geçerli bir DOI veya PMID değil"}), 400
    blk = _quota_block("refs")
    if blk:
        return blk
    rec = _fetch_one(raw)
    if not rec:
        return jsonify({"error": "Kayıt bulunamadı"}), 404
    # Kopya kontrolü (force ile zorlanabilir)
    if not d.get("force") and (_rec_keys(rec) & db.existing_keys()):
        return jsonify({"duplicate": True, "title": rec.get("title", "")})
    rid = db.add_ref({**rec, "collection_id": coll})
    return jsonify({"id": rid, "ref": db.get_ref(rid)})


@bp.post("/api/import/bulk")
def api_import_bulk():
    """Çok sayıda DOI/PMID (her satıra biri) — hepsini çeker, kopyaları atlar."""
    d = request.json or {}
    lines = [l.strip() for l in (d.get("text") or "").splitlines() if l.strip()]
    coll = d.get("collection")
    if not lines:
        return jsonify({"error": "En az bir DOI/PMID girin"}), 400
    blk = _quota_block("refs")
    if blk:
        return blk
    fetched, failed = [], []
    for line in lines[:200]:
        rec = _fetch_one(line)
        (fetched.append(rec) if rec else failed.append(line))
    new, skipped = _split_new(fetched)
    ids = db.add_refs(new, coll)
    return jsonify({"added": len(ids), "skipped_duplicates": skipped,
                    "failed": failed, "total": len(lines)})


@bp.post("/api/import/pdf")
def api_import_pdf():
    """Makale PDF'inden DOI yakalayıp kaydı çeker."""
    f = request.files.get("file")
    coll = request.form.get("collection") or None
    if not f:
        return jsonify({"error": "PDF dosyası yok"}), 400
    blk = _quota_block("refs")
    if blk:
        return blk
    doi = pdf_import.extract_doi(f.read())
    if not doi:
        return jsonify({"error": "PDF içinde DOI bulunamadı. DOI/PMID ile elle ekleyebilirsin."}), 422
    rec = crossref.fetch_doi(doi, Config.CROSSREF_EMAIL)
    if not rec:
        return jsonify({"error": f"DOI bulundu ({doi}) ama kayıt çekilemedi."}), 404
    if _rec_keys(rec) & db.existing_keys():
        return jsonify({"duplicate": True, "title": rec.get("title", ""), "doi": doi})
    rid = db.add_ref({**rec, "collection_id": coll})
    return jsonify({"id": rid, "doi": doi, "ref": db.get_ref(rid)})


@bp.post("/api/import/pdf-bulk")
def api_import_pdf_bulk():
    """Birden çok PDF: her birinin DOI'sini bul, kaydı çek ve PDF'i kayda ekle."""
    files = request.files.getlist("files")
    coll = request.form.get("collection") or None
    if not files:
        return jsonify({"error": "PDF seçilmedi"}), 400
    blk = _quota_block("refs")
    if blk:
        return blk
    added, skipped, no_doi = 0, 0, []
    existing = db.existing_keys()
    for f in files:
        data = f.read()
        doi = pdf_import.extract_doi(data)
        if not doi:
            no_doi.append(f.filename)
            continue
        rec = crossref.fetch_doi(doi, Config.CROSSREF_EMAIL)
        if not rec:
            no_doi.append(f.filename)
            continue
        if _rec_keys(rec) & existing:
            skipped += 1
            continue
        existing |= _rec_keys(rec)
        rid = db.add_ref({**rec, "collection_id": coll})
        _save_pdf(rid, data)   # PDF'i bu kayda ekle
        added += 1
    return jsonify({"added": added, "skipped_duplicates": skipped,
                    "no_doi": no_doi, "total": len(files)})


@bp.post("/api/import/search")
def api_import_search():
    """PubMed araması — adayları döner (kaydetmez; kullanıcı seçer)."""
    d = request.json or {}
    q = (d.get("query") or "").strip()
    if not q:
        return jsonify({"error": "Arama terimi girin"}), 400
    pmids = _pm().search(q, retmax=int(d.get("limit", 25)))
    return jsonify({"candidates": _pm().fetch(pmids)})


@bp.post("/api/import/add")
def api_import_add():
    """Seçilen adayları (arama/önizleme) kütüphaneye ekler; kopyaları atlar."""
    blk = _quota_block("refs")
    if blk:
        return blk
    d = request.json or {}
    new, skipped = _split_new(d.get("items", []))
    ids = db.add_refs(new, d.get("collection"))
    return jsonify({"added": len(ids), "skipped_duplicates": skipped, "ids": ids})


@bp.post("/api/import/file")
def api_import_file():
    """RIS / BibTeX dosyası yükle ve içeri aktar (EndNote/Zotero çıktıları)."""
    f = request.files.get("file")
    coll = request.form.get("collection") or None
    if not f:
        return jsonify({"error": "Dosya yok"}), 400
    blk = _quota_block("refs")
    if blk:
        return blk
    text = f.read().decode("utf-8", errors="ignore")
    name = (f.filename or "").lower()
    if name.endswith(".bib") or text.lstrip().startswith("@"):
        recs = ref.parse_bibtex(text)
    else:
        recs = ref.parse_ris(text)
    if not recs:
        return jsonify({"error": "Tanınan kayıt bulunamadı (RIS/BibTeX bekleniyor)"}), 400
    new, skipped = _split_new(recs)
    ids = db.add_refs(new, coll)
    return jsonify({"added": len(ids), "skipped_duplicates": skipped})


# --------------------------------------------------------------- formatlama
@bp.get("/api/styles")
def api_styles():
    local = [(n, f"{n} (yerel .csl)") for n in csl.list_local_styles()]
    return jsonify({"styles": local + COMMON_STYLES, "csl_ok": csl.available()})


@bp.get("/api/styles/search")
def api_styles_search():
    """2000+ dergi CSL stili içinde arama."""
    return jsonify({"results": csl.search_styles(request.args.get("q", ""), limit=40)})


# --------------------------------------------------------------- bütünlük
@bp.post("/api/integrity/check")
def api_integrity_check():
    """PMID'li kayıtları geri çekilme / endişe ifadesi açısından tarar."""
    recs = [r for r in db.list_refs(request.json.get("collection", "all") if request.json else "all")
            if r.get("pmid")]
    pmid_to_id = {r["pmid"]: r["id"] for r in recs}
    flags = integrity.check_pmids(list(pmid_to_id.keys()), _pm())
    flagged = []
    for pmid, info in flags.items():
        rid = pmid_to_id[pmid]
        db.set_integrity(rid, info)
        flagged.append({"id": rid, "pmid": pmid, **info})
    # Temizlenenleri (artık işaretli olmayan) sıfırla
    for r in recs:
        if r["pmid"] not in flags and r.get("integrity"):
            db.set_integrity(r["id"], None)
    return jsonify({"checked": len(recs), "flagged": flagged})


# --------------------------------------------------------- kaydı tamamla
@bp.get("/api/incomplete")
def api_incomplete():
    """Eksik alanlı kayıtları döner (tamamlanmaya aday)."""
    recs = db.list_refs(request.args.get("collection", "all"))
    out = [{"id": r["id"], "title": r["title"], "missing": enrich.missing_fields(r)}
           for r in recs if enrich.needs_enrichment(r)]
    return jsonify({"incomplete": out, "count": len(out)})


@bp.get("/api/refs/<int:rid>/related")
def api_related(rid):
    """Bir referansa PubMed'de benzer/ilgili makaleleri önerir (atıf sayısıyla)."""
    r = db.get_ref(rid)
    if not r:
        return jsonify({"error": "bulunamadı"}), 404
    pm = _pm()
    pmid = r.get("pmid")
    if not pmid and r.get("title"):   # PMID yoksa başlıkla bul
        hits = pm.search(r["title"], retmax=1)
        pmid = hits[0] if hits else None
    if not pmid:
        return jsonify({"error": "Bu kayıt için PMID bulunamadı (öneri PubMed gerektirir)."}), 422
    related_ids = pm.related(pmid, retmax=25)
    recs = pm.fetch(related_ids)
    # kütüphanede zaten olanları ele
    existing = db.existing_keys()
    recs = [x for x in recs if not (_rec_keys(x) & existing)]
    # atıf sayısı/etki ekle
    met = icite.metrics([x.get("pmid", "") for x in recs])
    for x in recs:
        m = met.get(x.get("pmid", ""), {})
        x["citations"] = m.get("citations", 0)
        x["rcr"] = m.get("rcr")
    return jsonify({"candidates": recs[:20], "source_title": r.get("title", "")})


@bp.post("/api/refs/<int:rid>/enrich")
def api_enrich_one(rid):
    r = db.get_ref(rid)
    if not r:
        return jsonify({"error": "bulunamadı"}), 404
    filled = enrich.enrich(r, _pm(), Config.CROSSREF_EMAIL)
    if filled:
        db.update_ref(rid, {**r, **filled})
    return jsonify({"filled": list(filled.keys()), "ref": db.get_ref(rid)})


def _tagger():
    return tagger.Tagger(Config.ANTHROPIC_API_KEY, Config.HELPER_MODEL)


@bp.post("/api/refs/<int:rid>/autotag")
def api_autotag_one(rid):
    r = db.get_ref(rid)
    if not r:
        return jsonify({"error": "bulunamadı"}), 404
    if not Config.ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY gerekli"}), 400
    blk = _quota_block("autotag")
    if blk:
        return blk
    existing_vocab = [t["tag"] for t in db.list_tags()]
    tags_map = _tagger().tag_batch([r], existing_vocab)
    quota.consume("autotag")
    new_tags = tags_map.get(0, [])
    merged = sorted(set((r.get("tags") or []) + new_tags))
    db.update_ref(rid, {**r, "tags": merged})
    return jsonify({"tags": merged, "added": new_tags})


@bp.post("/api/autotag/all")
def api_autotag_all():
    """Koleksiyondaki kayıtları otomatik etiketle (varsayılan: etiketsizler, en çok 60)."""
    if not Config.ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY gerekli"}), 400
    blk = _quota_block("autotag")
    if blk:
        return blk
    d = request.json or {}
    recs = db.list_refs(d.get("collection", "all"))
    if d.get("only_untagged", True):
        recs = [r for r in recs if not (r.get("tags") or [])]
    batch = recs[:60]
    vocab = [t["tag"] for t in db.list_tags()]
    tagged = 0
    # 10'arlı gruplar (tek Claude çağrısı/grup)
    tg = _tagger()
    for i in range(0, len(batch), 10):
        chunk = batch[i:i + 10]
        tags_map = tg.tag_batch(chunk, vocab)
        for j, r in enumerate(chunk):
            new_tags = tags_map.get(j, [])
            if new_tags:
                merged = sorted(set((r.get("tags") or []) + new_tags))
                db.update_ref(r["id"], {**r, "tags": merged})
                vocab = sorted(set(vocab + new_tags))   # sözlüğü büyüt (tutarlılık)
                tagged += 1
    if tagged:
        quota.consume("autotag")
    return jsonify({"processed": len(batch), "tagged": tagged,
                    "remaining": max(0, len(recs) - len(batch))})


@bp.post("/api/enrich/all")
def api_enrich_all():
    """Koleksiyondaki tüm eksik kayıtları tamamla (tek seferde en çok 80)."""
    d = request.json or {}
    recs = [r for r in db.list_refs(d.get("collection", "all")) if enrich.needs_enrichment(r)]
    batch = recs[:80]
    enriched, fields_total = 0, 0
    for r in batch:
        filled = enrich.enrich(r, _pm(), Config.CROSSREF_EMAIL)
        if filled:
            db.update_ref(r["id"], {**r, **filled})
            enriched += 1
            fields_total += len(filled)
    return jsonify({"processed": len(batch), "enriched": enriched,
                    "fields_filled": fields_total, "remaining": max(0, len(recs) - len(batch))})


# --------------------------------------------------------------- çöp kutusu
@bp.get("/api/trash")
def api_trash():
    return jsonify({"refs": db.list_deleted()})


@bp.post("/api/refs/<int:rid>/restore")
def api_restore(rid):
    db.restore_ref(rid)
    return jsonify({"ok": True})


# --------------------------------------------------------------- istatistik
@bp.get("/api/stats")
def api_stats():
    return jsonify(db.stats())


# --------------------------------------------------------------- atıf aracı
@bp.post("/api/manuscript")
def api_manuscript():
    """Metindeki {{id}} / [#id] işaretçilerini numaralı atıf + kaynakçaya çevirir."""
    d = request.json or {}
    result = manuscript.process(d.get("text", ""), db.get_ref, style=d.get("style", "vancouver"))
    return jsonify(result)


@bp.post("/api/manuscript/export")
def api_manuscript_export():
    d = request.json or {}
    result = manuscript.process(d.get("text", ""), db.get_ref, style=d.get("style", "vancouver"))
    data = manuscript.to_docx(result, title=d.get("title", ""))
    return send_file(io.BytesIO(data), as_attachment=True, download_name="makale-atifli.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# --------------------------------------------------- otomatik referanslama (Claude)
_AUTOCITE_JOBS: dict[str, dict] = {}
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _autocite_worker(job_id: str, text: str, style: str, max_claims: int, clean_existing: bool):
    job = _AUTOCITE_JOBS[job_id]
    try:
        pm = _pm()
        searcher = sources.MultiSource(pm, Config.CROSSREF_EMAIL)  # çoklu veritabanı
        ac = autocite.AutoCite(Config.ANTHROPIC_API_KEY, Config.MODEL, Config.HELPER_MODEL,
                               pm, Config.CROSSREF_EMAIL, searcher=searcher)

        def progress(stage, done, total):
            job.update(stage=stage, done=done, total=total)

        # NCBI anahtarı varsa daha çok paralel işçi (rate limit daha yüksek)
        workers = 6 if Config.NCBI_API_KEY else 4
        result = ac.run(text, style=style, max_claims=max_claims,
                        clean_existing=clean_existing, workers=workers, progress=progress)
        job.update(state="done", result=result)
    except Exception as e:
        job.update(state="error", error=str(e))


@bp.post("/api/autocite/start")
def api_autocite_start():
    """Referanssız metni (yapıştırılan ya da Word/PDF yüklenen) tara, atıfları yerleştir."""
    if not Config.ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY tanımlı değil (.env). Otomatik referanslama Claude gerektirir."}), 400
    # Dosya yüklendiyse metni çıkar; yoksa JSON'dan al
    if request.files.get("file"):
        f = request.files["file"]
        text = autocite.read_manuscript(f.filename, f.read())
        style = request.form.get("style", "vancouver")
        max_claims = int(request.form.get("max_claims", 30))
        clean = request.form.get("clean_existing", "1") != "0"
    else:
        d = request.json or {}
        text = (d.get("text") or "").strip()
        style = d.get("style", "vancouver")
        max_claims = int(d.get("max_claims", 30))
        clean = d.get("clean_existing", True)
    if not text or len(text.strip()) < 40:
        return jsonify({"error": "Metin çok kısa ya da boş"}), 400
    if (vb := _verify_block()):               # e-posta doğrulaması (maliyet koruması)
        return vb
    blk = _quota_block("autocite")            # kota kontrolü
    if blk:
        return blk
    job_id = uuid.uuid4().hex[:12]
    _AUTOCITE_JOBS[job_id] = {"state": "running", "stage": "Başlatılıyor", "done": 0, "total": 0,
                             "style": style}
    t = threading.Thread(target=_autocite_worker, daemon=True,
                         args=(job_id, text, style, max_claims, clean))
    t.start()
    quota.consume("autocite")                 # kullanımı say
    return jsonify({"job_id": job_id})


@bp.get("/api/autocite/status/<job_id>")
def api_autocite_status(job_id):
    job = _AUTOCITE_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "İş bulunamadı"}), 404
    out = {k: job.get(k) for k in ("state", "stage", "done", "total", "error")}
    if job.get("state") == "done":
        r = job["result"]
        out["result"] = {k: r[k] for k in ("annotated_text", "entries", "citations", "n_claims",
                                            "n_cited", "n_inserted", "removed_existing", "unmatched")}
    return jsonify(out)


# --------------------------------------------------- atıf denetleyici (Citation Audit)
_AUDIT_JOBS: dict[str, dict] = {}


def _audit_worker(job_id: str, text: str):
    job = _AUDIT_JOBS[job_id]
    try:
        ca = audit.CitationAudit(Config.ANTHROPIC_API_KEY, Config.MODEL, _pm(), Config.CROSSREF_EMAIL)
        result = ca.run(text, progress=lambda s, d, t: job.update(stage=s, done=d, total=t))
        job.update(state="done", result=result)
    except Exception as e:
        job.update(state="error", error=str(e))


@bp.post("/api/audit/start")
def api_audit_start():
    """Yapıştırılan kaynakça/atıfları alır; her referans gerçek mi diye CrossRef+PubMed'de doğrular."""
    if not Config.ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY tanımlı değil (.env)."}), 400
    text = ((request.json or {}).get("text") or "").strip()
    if len(text) < 30:
        return jsonify({"error": "Metin çok kısa ya da boş"}), 400
    if (vb := _verify_block()):
        return vb
    blk = _quota_block("autocite")            # Claude-maliyetli; autocite kotasını paylaşır
    if blk:
        return blk
    job_id = uuid.uuid4().hex[:12]
    _AUDIT_JOBS[job_id] = {"state": "running", "stage": "Başlatılıyor", "done": 0, "total": 0}
    threading.Thread(target=_audit_worker, daemon=True, args=(job_id, text)).start()
    quota.consume("autocite")
    return jsonify({"job_id": job_id})


@bp.get("/api/audit/status/<job_id>")
def api_audit_status(job_id):
    job = _AUDIT_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "İş bulunamadı"}), 404
    out = {k: job.get(k) for k in ("state", "stage", "done", "total", "error")}
    if job.get("state") == "done":
        out["result"] = job["result"]
    return jsonify(out)


# --------------------------------------------------- AI literatür derlemesi (sentez)
@bp.post("/api/synthesize")
def api_synthesize():
    """Seçili kaynaklardan (ids ya da collection) Claude ile atıflı sentez paragrafı üretir."""
    if not Config.ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY tanımlı değil (.env)."}), 400
    d = request.json or {}
    recs = _collect(d)[:25]                        # token/maliyet sınırı
    if not recs:
        return jsonify({"error": "Kaynak seçilmedi"}), 400
    if (vb := _verify_block()):
        return vb
    if (blk := _quota_block("autocite")):
        return blk
    syn = synthesis.Synthesizer(Config.ANTHROPIC_API_KEY, Config.MODEL)
    res = syn.run(recs, question=(d.get("question") or "").strip())
    quota.consume("autocite")
    sources = [{"n": n, "title": recs[n - 1].get("title", ""), "year": recs[n - 1].get("year", ""),
                "doi": recs[n - 1].get("doi", ""), "pmid": recs[n - 1].get("pmid", "")}
               for n in res.get("used", []) if 1 <= n <= len(recs)]
    return jsonify({"synthesis": res.get("synthesis", ""), "sources": sources,
                    "n_sources": res.get("n_sources", 0)})


# --------------------------------------------------- Kütüphanene Sor (Ask-your-library)
def _ref_text(r: dict) -> str:
    """Bir kaynağın QA için metni: özet + (varsa) ekli PDF'in metni (kısaltılmış)."""
    text = (r.get("abstract") or "").strip()
    att = r.get("attachment")
    if att and len(text) < 6000:
        path = Config.ATTACH_DIR / att
        if path.exists():
            try:
                from pypdf import PdfReader
                pages = PdfReader(str(path)).pages[:12]
                pdf_txt = "\n".join((p.extract_text() or "") for p in pages)
                text = (text + "\n" + pdf_txt).strip()[:20000]
            except Exception:
                pass
    return text


@bp.post("/api/library/ask")
def api_library_ask():
    """Seçili kaynakların özet/PDF metni üzerinde Claude ile atıflı yanıt üretir."""
    if not Config.ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY tanımlı değil (.env)."}), 400
    d = request.json or {}
    question = (d.get("question") or "").strip()
    if len(question) < 4:
        return jsonify({"error": "Soru çok kısa"}), 400
    recs = _collect(d)
    docs = [{"id": r["id"], "title": r.get("title", ""), "text": _ref_text(r)}
            for r in recs if _ref_text(r)]
    if not docs:
        return jsonify({"error": "Seçili kaynaklarda özet ya da PDF metni yok"}), 400
    if (vb := _verify_block()):
        return vb
    if (blk := _quota_block("autocite")):
        return blk
    qa = library_qa.LibraryQA(Config.ANTHROPIC_API_KEY, Config.MODEL)
    res = qa.ask(question, docs)
    quota.consume("autocite")
    by_id = {r["id"]: r for r in recs}
    sources = [{"id": i, "title": by_id.get(i, {}).get("title", ""),
                "doi": by_id.get(i, {}).get("doi", ""), "pmid": by_id.get(i, {}).get("pmid", "")}
               for i in res.get("used", []) if i in by_id]
    return jsonify({"answer": res.get("answer", ""), "sources": sources,
                    "n_docs": res.get("n_docs", 0)})


# --------------------------------------------------- dergi metrikleri (OpenAlex)
@bp.get("/api/refs/<int:rid>/metrics")
def api_ref_metrics(rid):
    """Kaydın dergisinin bibliyometrik metrikleri (etki, h-index, tier) — OpenAlex."""
    r = db.get_ref(rid)
    if not r:
        return jsonify({"error": "Kayıt bulunamadı"}), 404
    m = metrics.journal_metrics(name=(r.get("journal") or r.get("iso") or ""),
                                email=Config.CROSSREF_EMAIL)
    return jsonify({"metrics": m})


# --------------------------------------------------- tarayıcı eklentisi: tek-tık yakalama
def _capture_page(msg: str, kind: str, sub: str = ""):
    color = {"ok": "#16a34a", "dup": "#d97706", "err": "#e11d48"}.get(kind, "#334155")
    icon = {"ok": "✓", "dup": "•", "err": "✕"}.get(kind, "")
    return (f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Refly</title>
<style>body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0b1736;
color:#fff;display:grid;place-items:center;height:100vh}}.card{{background:#111f42;border:1px solid #24345f;
border-radius:18px;padding:32px 34px;max-width:440px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.4)}}
.ic{{width:56px;height:56px;border-radius:50%;display:grid;place-items:center;margin:0 auto 14px;
font-size:28px;font-weight:800;background:{color}22;color:{color}}}h2{{margin:.2em 0}}
.sub{{color:#9fb0d0;font-size:14px;margin:6px 0 18px}}a{{display:inline-block;background:linear-gradient(135deg,#6366f1,#8b5cf6);
color:#fff;text-decoration:none;padding:10px 18px;border-radius:10px;font-weight:600}}</style></head>
<body><div class="card"><div class="ic">{icon}</div><h2>{msg}</h2>
<div class="sub">{sub}</div><a href="/">Refly'ı aç →</a></div>
<script>setTimeout(()=>{{try{{window.close()}}catch(e){{}}}}, 2500)</script></body></html>""",
            200, {"Content-Type": "text/html; charset=utf-8"})


@bp.get("/capture")
def capture():
    """Tarayıcı eklentisinin açtığı tek-tık yakalama sayfası — oturumla çalışır (CORS yok).
    ?doi= veya ?pmid= alır, kaydı çekip kütüphaneye ekler."""
    raw = (request.args.get("doi") or request.args.get("pmid") or request.args.get("id") or "").strip()
    if not raw:
        return _capture_page("DOI/PMID bulunamadı", "err", "Eklenti sayfada tanımlayıcı algılayamadı.")
    if (blk := _quota_block("refs")) is not None:
        return _capture_page("Kota doldu", "err", "Bu ay için kaynak limitine ulaşıldı.")
    rec = _fetch_one(raw)
    if not rec:
        return _capture_page("Kayıt bulunamadı", "err", f"'{raw}' için kayıt çekilemedi.")
    if _rec_keys(rec) & db.existing_keys():
        return _capture_page("Zaten kütüphanede", "dup", rec.get("title", ""))
    db.add_ref(rec)
    return _capture_page("Kütüphaneye eklendi ✓", "ok", rec.get("title", ""))


@bp.get("/extension")
def extension_info():
    """Tarayıcı eklentisi kurulum sayfası + .zip indirme."""
    return send_file(str(Config.BASE_DIR / "app" / "static" / "extension" / "install.html"))


@bp.get("/extension/download")
def extension_download():
    """Eklenti klasörünü .zip olarak indir (Chrome/Edge: 'Load unpacked' ile kur)."""
    import zipfile
    ext_dir = Config.BASE_DIR / "app" / "static" / "extension"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in ext_dir.iterdir():
            if p.is_file() and p.name != "install.html":
                z.write(str(p), p.name)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="refly-extension.zip",
                     mimetype="application/zip")


# --------------------------------------------------- konu alarmları / kayıtlı aramalar
@bp.get("/api/alerts")
def api_alerts_list():
    return jsonify({"alerts": db.list_searches()})


@bp.post("/api/alerts")
def api_alerts_create():
    """Yeni kayıtlı arama/alarm. İlk çalıştırmada baseline kurulur (alarm üretmez)."""
    d = request.json or {}
    query = (d.get("query") or "").strip()
    if len(query) < 3:
        return jsonify({"error": "Arama çok kısa"}), 400
    sid = db.add_search(query, (d.get("email") or "").strip())
    alerts.run_search(_pm(), db.get_search(sid), send_email=False)   # baseline
    return jsonify({"id": sid, "alert": db.get_search(sid)})


@bp.delete("/api/alerts/<int:sid>")
def api_alerts_delete(sid):
    db.delete_search(sid)
    return jsonify({"ok": True})


@bp.post("/api/alerts/<int:sid>/check")
def api_alerts_check(sid):
    """Alarmı hemen kontrol et — yeni makaleleri döner (+ e-posta ayarlıysa özet gönderir)."""
    search = db.get_search(sid)
    if not search:
        return jsonify({"error": "Alarm bulunamadı"}), 404
    return jsonify(alerts.run_search(_pm(), search, send_email=True))


@bp.post("/api/alerts/run-all")
def api_alerts_run_all():
    """TÜM aktif alarmları kontrol eder — dış zamanlayıcıdan (cron) tetiklenir.
    X-Refly-Secret: REFLY_ADMIN_KEY ile korunur (ya da admin oturumu)."""
    if not (_secret_ok(request.headers.get("X-Refly-Secret"), Config.REFLY_ADMIN_KEY) or _is_admin()):
        return jsonify({"error": "Yetkisiz"}), 403
    pm = _pm()
    total_new = 0
    n = 0
    for s in db.all_active_searches():
        res = alerts.run_search(pm, s, send_email=True)
        total_new += res.get("n_new", 0)
        n += 1
    return jsonify({"checked": n, "total_new": total_new})


# --------------------------------------------------- ekip / paylaşımlı kütüphaneler
@bp.post("/api/collections/<int:cid>/share")
def api_share_collection(cid):
    """Koleksiyonu bir e-posta ile paylaş (viewer/editor). Sadece koleksiyon sahibi."""
    d = request.json or {}
    sid = db.share_collection(cid, d.get("email", ""), d.get("role", "viewer"))
    if sid is None:
        return jsonify({"error": "Paylaşılamadı (koleksiyon sana ait değil ya da e-posta boş)"}), 400
    return jsonify({"id": sid, "shares": db.list_shares(cid)})


@bp.get("/api/collections/<int:cid>/shares")
def api_list_shares(cid):
    return jsonify({"shares": db.list_shares(cid)})


@bp.delete("/api/shares/<int:share_id>")
def api_unshare(share_id):
    return jsonify({"ok": db.unshare(share_id)})


@bp.get("/api/shared")
def api_shared_with_me():
    return jsonify({"shared": db.shared_with_me()})


@bp.get("/api/shared/<int:cid>/refs")
def api_shared_refs(cid):
    """Bana paylaşılmış bir koleksiyonun kayıtları — yetki (paylaşım) kontrolüyle."""
    refs = db.shared_collection_refs(cid)
    if refs is None:
        return jsonify({"error": "Bu koleksiyona erişimin yok"}), 403
    return jsonify({"refs": refs, "role": db.shared_role(cid)})


@bp.post("/api/autocite/save/<job_id>")
def api_autocite_save(job_id):
    """Bulunan kaynakları kütüphaneye ekler (kopyaları atlar)."""
    job = _AUTOCITE_JOBS.get(job_id)
    if not job or job.get("state") != "done":
        return jsonify({"error": "Sonuç hazır değil"}), 400
    coll = (request.json or {}).get("collection")
    new, skipped = _split_new(job["result"]["references"])
    ids = db.add_refs(new, coll)
    return jsonify({"added": len(ids), "skipped_duplicates": skipped})


@bp.post("/api/autocite/export/<job_id>")
def api_autocite_export(job_id):
    """Otomatik referanslama sonucunu dışa aktar. format: docx (metin+kaynakça) |
    endnote (EndNote XML) | ris | bibtex | csl — bulunan gerçek kaynaklardan üretir."""
    job = _AUTOCITE_JOBS.get(job_id)
    if not job or job.get("state") != "done":
        return jsonify({"error": "Sonuç hazır değil"}), 400
    r = job["result"]
    fmt = (request.json or {}).get("format", "docx")
    recs = r.get("references", [])
    if fmt == "endnote":
        return _text(ref.to_endnote_xml(recs), "refly-endnote.xml")
    if fmt == "ris":
        return _text(ref.to_ris(recs), "refly.ris")
    if fmt == "bibtex":
        return _text(ref.to_bibtex(recs), "refly.bib")
    if fmt == "csl":
        return _text(ref.to_csl_json(recs), "refly-csl.json")
    data = manuscript.to_docx({"text": r["annotated_text"], "entries": r["entries"]},
                              title=(request.json or {}).get("title", ""))
    return send_file(io.BytesIO(data), as_attachment=True, download_name="referansli-makale.docx",
                     mimetype=_DOCX_MIME)


def _collect(d: dict) -> list[dict]:
    """ids verilmişse o kayıtları; yoksa collection'daki tüm kayıtları getirir."""
    ids = d.get("ids")
    if ids:
        return [r for r in (db.get_ref(i) for i in ids) if r]
    return db.list_refs(d.get("collection", "all"))


@bp.post("/api/format")
def api_format():
    d = request.json or {}
    recs = _collect(d)
    entries = csl.build_reference_list(recs, style=d.get("style", "vancouver"))
    return jsonify({"entries": entries, "count": len(entries)})


# --------------------------------------------------------------- dedup
@bp.get("/api/duplicates")
def api_duplicates():
    recs = db.list_refs(request.args.get("collection", "all"))
    groups = ref.find_duplicates(recs)
    return jsonify({"groups": [[{"id": r["id"], "title": r["title"], "year": r["year"],
                                 "journal": r.get("journal") or r.get("iso", ""),
                                 "doi": r.get("doi", ""), "pmid": r.get("pmid", "")}
                                for r in g] for g in groups]})


@bp.post("/api/duplicates/merge")
def api_merge():
    """keep_id korunur, drop_ids soft-delete edilir."""
    d = request.json or {}
    for rid in d.get("drop_ids", []):
        db.delete_ref(int(rid))
    return jsonify({"merged": len(d.get("drop_ids", []))})


# --------------------------------------------------------------- export
@bp.post("/api/export")
def api_export():
    d = request.json or {}
    recs = _collect(d)
    fmt = d.get("format", "docx")
    style = d.get("style", "vancouver")

    if fmt == "docx":
        data = docx_export.bibliography_docx(recs, style=style,
                                             title=d.get("title", "Kaynaklar"))
        return send_file(io.BytesIO(data), as_attachment=True,
                         download_name="kaynakca.docx",
                         mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if fmt == "ris":
        return _text(ref.to_ris(recs), "refly.ris")
    if fmt == "bibtex":
        return _text(ref.to_bibtex(recs), "refly.bib")
    if fmt == "csl":
        return _text(ref.to_csl_json(recs), "refly-csl.json")
    if fmt == "endnote":
        return _text(ref.to_endnote_xml(recs), "refly-endnote.xml")
    # txt — düz numaralı kaynakça
    return _text("\n".join(csl.build_reference_list(recs, style=style)), "kaynakca.txt")


@bp.post("/api/format/multi")
def api_format_multi():
    """Tek/seçili kayıtları birden çok stilde aynı anda biçimlendirir (hızlı kopya)."""
    d = request.json or {}
    recs = _collect(d)
    styles = d.get("styles") or ["vancouver", "ama", "apa", "harvard", "the-lancet"]
    import re
    lead = re.compile(r"^\s*\d+[.)]?\s*")
    out = {}
    for s in styles:
        entries = csl.build_reference_list(recs, style=s)
        out[s] = [lead.sub("", e) for e in entries]   # baştaki numarayı at (tek kayıt kopyası)
    return jsonify({"styles": out})


def _text(content: str, name: str):
    return send_file(io.BytesIO(content.encode("utf-8")), as_attachment=True,
                     download_name=name, mimetype="text/plain")


# --------------------------------------------------------------- yedekleme
# GÜVENLİK: yedek/geri-yükleme TÜM sistemi (tüm kullanıcılar) kapsar — sadece admin.
# (Tek kullanıcının kendi verisini dışa aktarması için /api/export kullanılır, o kapsanmış.)
def _is_admin() -> bool:
    uid = db.current_user()
    if uid is None:                       # auth kapalı = yerel tek kullanıcı = admin
        return True
    u = db.get_user(uid)
    return bool(u and (u.get("email") or "").lower() in Config.REFLY_ADMIN_EMAILS)


def _admin_block():
    if not _is_admin():
        return jsonify({"error": "Bu işlem yalnızca yönetici içindir"}), 403
    return None


@bp.get("/api/backup")
def api_backup():
    if (b := _admin_block()):
        return b
    import datetime as _dt
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M")
    return send_file(io.BytesIO(backup.make_zip_bytes()), as_attachment=True,
                     download_name=f"refly-yedek-{stamp}.zip", mimetype="application/zip")


@bp.get("/api/backups")
def api_backups():
    if (b := _admin_block()):
        return b
    return jsonify({"snapshots": backup.list_snapshots()})


@bp.post("/api/backup/now")
def api_backup_now():
    if (b := _admin_block()):
        return b
    path = backup.snapshot(tag="elle")
    return jsonify({"ok": True, "name": path.name, "offsite": backup.offsite_configured()})


@bp.post("/api/backup/offsite")
def api_backup_offsite():
    """Yedeği hemen off-site (S3 uyumlu) depoya yükler — kurulumu test etmek için."""
    if (b := _admin_block()):
        return b
    if not backup.offsite_configured():
        return jsonify({"error": "Off-site yedek ayarlı değil — .env'de REFLY_BACKUP_S3_* doldur."}), 400
    import datetime as _dt
    name = f"refly-elle-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    try:
        key = backup.push_offsite(backup.make_zip_bytes(), name)
    except Exception as e:
        return jsonify({"error": f"Off-site yükleme başarısız: {e}"}), 500
    return jsonify({"ok": True, "key": key, "bucket": Config.BACKUP_S3_BUCKET})


@bp.post("/api/restore")
def api_restore_backup():
    if (b := _admin_block()):
        return b
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Zip dosyası yok"}), 400
    try:
        info = backup.restore_from_zip(f.read())
    except Exception:
        return jsonify({"error": "Geri yükleme başarısız (geçersiz zip?)"}), 400
    return jsonify({"ok": True, **info})
