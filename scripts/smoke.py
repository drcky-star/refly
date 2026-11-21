#!/usr/bin/env python3
"""Refly deploy-öncesi smoke testi.

Flask test_client ile kritik rotaları ve davranışları doğrular — her `git push` (canlıya
deploy) ÖNCESİ çalıştır, kazara kırılmayı yakala:

    ./venv/bin/python scripts/smoke.py

Tümü geçerse exit 0; biri başarısızsa exit 1 (ve hangisi başarısız yazılır).
REFLY_AUTH=1 ile üretim davranışı simüle edilir (anonim kullanıcı akışı).
"""
import os
import sys

os.environ.setdefault("REFLY_AUTH", "1")
os.environ.setdefault("REFLY_PRODUCTION", "0")
os.environ.setdefault("FLASK_SECRET_KEY", "smoke-secret-" + "x" * 24)
os.environ.setdefault("REFLY_ADMIN_EMAILS", "smoke@example.com")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

app = create_app()
c = app.test_client()
fails = []


def check(label, cond):
    print(("  ✓ " if cond else "  ✗ FAIL ") + label)
    if not cond:
        fails.append(label)


print("== Public sayfalar ==")
check("anonim / → 200 (landing)", c.get("/").status_code == 200)
check("landing 'Get Started' içeriyor", "Get Started" in c.get("/").get_data(as_text=True))
check("/login → 200", c.get("/login").status_code == 200)
check("/register → 200", c.get("/register").status_code == 200)
check("/privacy → 200", c.get("/privacy").status_code == 200)
check("/terms → 200", c.get("/terms").status_code == 200)
check("/robots.txt → 200 (login'e atmıyor)", c.get("/robots.txt").status_code == 200)
check("/sitemap.xml → 200", c.get("/sitemap.xml").status_code == 200)
check("/healthz ok", c.get("/healthz").get_json().get("status") == "ok")
check("/api/user-count → 200 int", isinstance(c.get("/api/user-count").get_json().get("count"), int))

print("== Auth kapısı (anonim → 401) ==")
for ep in ["/api/refs", "/api/rephrase", "/api/evidence", "/api/compare",
           "/api/ai-disclosure", "/api/synthesize", "/api/autotag/all"]:
    m = c.get(ep) if ep == "/api/refs" else c.post(ep, json={})
    check(f"{ep} → 401", m.status_code == 401)

print("== Rota kaydı (yeni özellikler) ==")
rules = {r.endpoint for r in app.url_map.iter_rules()}
for ep in ["refly.api_snowball", "refly.api_evidence", "refly.api_compare",
           "refly.api_rephrase", "refly.api_ai_disclosure", "refly.robots_txt",
           "refly.sitemap_xml", "refly.user_count", "auth.google_callback"]:
    check(f"{ep} kayıtlı", ep in rules)

print("== Statik varlıklar ==")
for path in ["style.css", "app.js", "i18n.js", "home.html", "og-image.png"]:
    check(f"/static/{path} → 200", c.get(f"/static/{path}").status_code == 200)

print()
if fails:
    print(f"❌ {len(fails)} BAŞARISIZ — DEPLOY ETME:")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("✅ TÜM SMOKE TESTLER GEÇTİ — deploy güvenli")
sys.exit(0)
