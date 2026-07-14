# 📚 Refly

EndNote'un yaptığı işi otomatikleştiren açık referans yöneticisi — **web + masaüstü**.
Kaynak topla, kütüphanende düzenle, dergi stilinde kaynakça üret, Word'e aktar, kopyaları temizle.

[Quil](../quil) ile kardeş uygulamadır: Quil makaleyi yazar, Refly kaynakları yönetir.

## ⭐ Otomatik referanslama (bayrak özellik)
ChatGPT'yle yazılmış, **referanssız ya da sahte referanslı** bir tez/makaleyi **yapıştır
ya da Word/PDF olarak yükle** →
Refly her iddiayı okur, **PubMed'de gerçek kaynağı bulur**, Claude ile özetin cümleyi
gerçekten desteklediğini **doğrular** (desteklemiyorsa atmaz) ve `[1],[2]…` atıflarını
yerleştirip seçtiğin stilde kaynakçayı üretir, Word olarak verir. ChatGPT'nin uydurma
atıf sorunu yok — her kaynak var olan, doğrulanmış bir makale.
**v2:** metindeki **mevcut/sahte atıfları otomatik temizler**, atıf başına **güven %** gösterir,
büyük tezleri **paralel** işler. Gerektirir: `.env` içinde `ANTHROPIC_API_KEY` (Claude).

## v2 yeni özellikler
- **PDF kütüphanesi** — her referansa gerçek PDF ekle/aç (EndNote gibi); bir klasördeki **onlarca PDF'i toplu** at, DOI'leri bulunup kütüphane kurulsun.
- **Kaydı tamamla** — eksik alanlı (DOI/yıl/cilt/sayfa yok) kayıtları CrossRef + PubMed'den otomatik doldur; tek tıkla tüm kütüphaneyi tamamla. Mevcut veriler asla ezilmez.
- **Akıllı kaynak öner** — bir referanstan yola çıkıp PubMed'de benzer/ilgili makaleleri önerir; her birinin **atıf sayısını** (iCite) gösterir, böylece etkili/temel makaleleri seçersin. Literatür taraması için.
- **Otomatik konu etiketleme** — Claude kaynakları konuya göre etiketler (lomber, servikal, rct, covid-19…); mevcut etiket sözlüğünü yeniden kullanarak tutarlı kalır. Tek kayıt ya da tüm kütüphane.

## Özellikler (v1 — 10 paket)
1. **Kaynak ekleme** — DOI/PMID yapıştır, otomatik çeker (CrossRef + PubMed); elle gir.
2. **Toplu import** — alt alta birçok DOI/PMID'i tek seferde ekle.
3. **PubMed araması** — ara, sonuçlardan seçerek ekle.
4. **PDF'ten import** — makale PDF'ini at, içindeki DOI'yi bulup kaydı çeker.
5. **RIS / BibTeX** — EndNote/Zotero/Mendeley'den içe + dışa aktarım.
6. **Kütüphane** — koleksiyonlar, arama, **etiket filtresi**, **yıldız/favori**. Silmeler soft-delete + audit; **çöp kutusundan geri yükleme**.
7. **Kopya yönetimi** — eklerken otomatik atlar; mevcut yinelenenleri bulup birleştirir.
8. **Geri çekilme kontrolü** — PubMed üzerinden retracted / endişe ifadesi / erratum taraması ve uyarı rozeti.
9. **Kaynakça formatlama** — Vancouver, AMA/JAMA, NEJM, Lancet, BMJ, Nature, APA, Harvard, IEEE… **2000+ dergi stili içinde arama** (Spine, Neurosurgery dahil). Kendi `.csl`'lerini de kullanabilirsin.
10. **Word entegrasyonu + Atıf aracı** — tek tıkla `.docx` kaynakça; metne `{{id}}`/`[#id]` koy → numaralı `[n]` atıf + kaynakçalı Word. Ayrıca **panel/istatistik** (yıllara/dergilere dağılım).

## Kurulum
```bash
cd refly
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env          # NCBI e-postanı yaz (opsiyonel)
```

## Çalıştırma
**Web** (tarayıcı):
```bash
./venv/bin/python run.py      # http://127.0.0.1:5006
```
**Masaüstü** (native pencere):
```bash
./venv/bin/python desktop.py
```

## Yayınlama (publish)
- **Web (Docker/Render)**: `Dockerfile` + `render.yaml` hazır. github'a it → Render'da "New Blueprint" → repoyu seç. Kalıcı disk `instance/`'a bağlanır (SQLite + PDF ekleri + yedekler kaybolmaz). Gizli env: `ANTHROPIC_API_KEY`, `NCBI_*`. `REFLY_AUTH=1` → çok kullanıcılı + giriş. Sağlık ucu: `/healthz`.
- **Masaüstü (.app/.exe)**: ikon hazır (`app/static/refly.icns`).
  ```bash
  ./venv/bin/pip install pyinstaller
  ./venv/bin/pyinstaller refly-desktop.spec   # -> dist/Refly.app
  ```

## Word eklentisi (cite-while-write)
Refly çalışırken Word içinden kütüphanende arayıp atıf ekleyebilir, kaynakçayı tek tıkla üretebilirsin.
1. Refly'ı başlat (`run.py`).
2. **Word → Insert → Add-ins → My Add-ins → Upload My Add-in** → `http://localhost:5006/addin/manifest.xml`
   (Mac: `~/Library/Containers/.../wef` klasörüne manifest'i koyarak da sideload edebilirsin.)
3. Açılan **Refly** panelinden ara → "Atıf ekle" → bitince "Kaynakçayı oluştur/güncelle".

> Not: Word eklentileri üretimde **HTTPS** ister; yayınlanmış Refly adresini (https://…) kullan.

## Çok dilli arayüz
Arayüz 5 dilde: **Türkçe, İngilizce, Arapça (RTL), Fransızca, Almanca**. Kenar çubuğundaki dil
seçiciden değiştirilir; tercih tarayıcıda saklanır. Çeviriler elle yapıldı (`app/static/i18n.js`),
makine çevirisi değil. Giriş sayfaları da çevrilir (dil çerezine göre).

## Masaüstü kısayolu (macOS)
`~/Desktop/Refly.app` çift tıklanınca sunucuyu başlatır ve tarayıcıda açar (logolu).
Yeniden oluşturmak için: `osacompile` ile bir AppleScript launcher derleyip `refly.icns`'i ikon yap.

## Çok kullanıcılı mod
`REFLY_AUTH=1` ile her kullanıcı kendi hesabıyla girer, kütüphaneler ayrılır. Yerelde tek kullanıcı için kapalı bırak (varsayılan).

## Güvenlik (halka açılmadan önce)
Sertleştirmeler: veri izolasyonu (her sorgu + her id'li mutasyon kullanıcıya kapsanmış — IDOR kapalı), güvenli oturum çerezi (HttpOnly/SameSite/Secure), güvenlik başlıkları (CSP, X-Frame-Options, nosniff, HSTS), giriş/kayıt için IP-bazlı **hız sınırı** (kaba-kuvvet), oturum-sabitleme koruması, zamanlama-güvenli gizli-anahtar karşılaştırması, yedek/geri-yükleme **sadece admin**, ProxyFix (gerçek IP), pbkdf2 parola özeti, min 8 karakter parola.

**Deploy checklist:**
1. `FLASK_SECRET_KEY` = güçlü rastgele (`python3 -c "import secrets;print(secrets.token_hex(32))"`) — üretimde varsayılan anahtarla **açılmaz**.
2. `REFLY_AUTH=1`, `REFLY_PRODUCTION=1` (HTTPS arkasında).
3. `REFLY_ADMIN_EMAILS=` senin e-postan (yedek/geri-yükleme yetkisi).
4. `REFLY_ADMIN_KEY` / `REFLY_BILLING_SECRET` = rastgele.
5. HTTPS zorunlu (Render/Fly otomatik verir). `.env` asla repoya girmez (`.gitignore`).
6. Kota açık (Claude maliyetini sınırlar); tek gunicorn worker (job store belleğe bağlı).
7. **E-posta doğrulama** — `REFLY_SMTP_*` + `REFLY_PUBLIC_URL` doldur, `REFLY_REQUIRE_EMAIL_VERIFICATION=1`. Doğrulanmayan kullanıcı otomatik referanslama yapamaz (bedava kotayı sahte hesapla sömürmeyi önler). SMTP boşsa doğrulama otomatik kapalı — kimse kilitlenmez.
8. **Off-site yedek** — `REFLY_BACKUP_S3_*` (AWS S3 / DigitalOcean Spaces / Backblaze B2 / Cloudflare R2). Ayarlıysa her yedek buluta da yüklenir; sunucu/disk ölse bile veri güvende. `/api/backup/offsite` (admin) ile test et.
9. **Hata izleme** — `SENTRY_DSN` ver (ücretsiz plan yeterli); kullanıcı hataları sana düşer.
10. **Yasal** — `/privacy` + `/terms` yayında (ödeme sağlayıcıları ister); `REFLY_CONTACT_EMAIL` doldur.
11. **Bağımlılık taraması** — `pip-audit` çalıştır; `pip install -r requirements.txt` taze deploy'da yamalı sürümleri çeker.

## Fiyatlandırma & kota
Planlar (`app/core/quota.py`, `.env`'de `REFLY_PLANS` ile ez): **Free** (5 otomatik referanslama/ay, 150 kaynak), **Student** ~$7 (25/ay, 5.000), **Pro** ~$14.99 (40/ay, 50.000), **Unlimited** (owner/kurumsal). İlk kayıt = unlimited (sen). Homepage'de Pricing bölümü var. Kullanım göstergesi kenar çubuğunda.

**Ödeme bağlama:** Stripe/iyzico'da her plan için bir ürün/Payment Link oluştur. Başarılı ödeme webhook'unda (kendi ince handler'ın ya da Zapier/serverless) şuraya POST at:
```
POST /api/billing/webhook
X-Refly-Secret: <REFLY_BILLING_SECRET>
{ "email": "musteri@x.com", "plan": "pro" }
```
Bu, kullanıcının planını yükseltir. (Doğrudan Stripe imza doğrulaması istersen `stripe` kütüphanesiyle ayrı bir handler eklenebilir — anahtarların hazır olunca bağlarım.)

## EndNote stilleri hakkında
EndNote `.ens` dosyaları kapalı ikili formattır ve okunamaz. Bunun yerine Refly,
aynı dergileri kapsayan açık **CSL** standardını kullanır (~10.000 stil hazır gelir).
Kendi CSL dosyalarını `.env` içindeki `REFLY_CSL_DIR` klasörüne koyabilirsin.
