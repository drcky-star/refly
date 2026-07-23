"""Refly veritabanı — SQLite. Kütüphane = koleksiyonlar + referanslar.

İlke: hard-delete YOK. Silinen kayıt deleted_at ile işaretlenir (geri alınabilir),
her değişiklik audit tablosuna yazılır.
"""
from __future__ import annotations
import json
import sqlite3
import threading
import datetime as dt
from pathlib import Path

_DB_PATH: Path | None = None

# İstek başına geçerli kullanıcı (auth açıkken doldurulur). None = scoping yok (tek kullanıcı).
_ctx = threading.local()


def set_current_user(uid):
    _ctx.uid = uid


def current_user():
    return getattr(_ctx, "uid", None)

SCHEMA = """
CREATE TABLE IF NOT EXISTS collections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    parent_id   INTEGER,
    created_at  TEXT NOT NULL,
    deleted_at  TEXT
);

CREATE TABLE IF NOT EXISTS refs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER,
    type        TEXT DEFAULT 'article-journal',
    title       TEXT,
    authors     TEXT,          -- JSON listesi ["Smith J", ...]
    journal     TEXT,
    iso         TEXT,          -- dergi kısaltması
    year        TEXT,
    volume      TEXT,
    issue       TEXT,
    pages       TEXT,
    doi         TEXT,
    pmid        TEXT,
    pmcid       TEXT,
    abstract    TEXT,
    url         TEXT,
    publisher   TEXT,
    tags        TEXT,          -- JSON listesi
    notes       TEXT,
    starred     INTEGER DEFAULT 0,
    integrity   TEXT,          -- JSON {kind, severity} (geri çekilme vb.)
    attachment  TEXT,          -- eklenen PDF'in saklanan dosya adı
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT
);

CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity      TEXT,
    entity_id   INTEGER,
    detail      TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT UNIQUE NOT NULL,
    name        TEXT,
    pw_hash     TEXT NOT NULL,
    plan        TEXT DEFAULT 'free',
    verified    INTEGER DEFAULT 0,   -- e-posta doğrulandı mı
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage (
    user_id     INTEGER NOT NULL,
    period      TEXT NOT NULL,     -- 'YYYY-MM'
    metric      TEXT NOT NULL,     -- 'autocite' | 'autotag'
    count       INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, period, metric)
);

CREATE TABLE IF NOT EXISTS shares (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL,
    owner_id      INTEGER,
    email         TEXT NOT NULL,     -- paylaşılan kişinin e-postası (küçük harf)
    role          TEXT DEFAULT 'viewer',   -- viewer | editor
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER,
    query        TEXT NOT NULL,
    email        TEXT,               -- özet gönderilecek e-posta (boşsa hesabınki)
    last_ids     TEXT DEFAULT '[]',  -- JSON: en son görülen PMID listesi
    active       INTEGER DEFAULT 1,
    created_at   TEXT NOT NULL,
    last_checked TEXT
);

CREATE INDEX IF NOT EXISTS idx_refs_doi  ON refs(doi);
CREATE INDEX IF NOT EXISTS idx_refs_pmid ON refs(pmid);
CREATE INDEX IF NOT EXISTS idx_refs_coll ON refs(collection_id);
"""

_JSON_FIELDS = ("authors", "tags")


def init_db(path: Path):
    global _DB_PATH
    _DB_PATH = path
    with _conn() as c:
        c.executescript(SCHEMA)
        _migrate(c)


def _migrate(c):
    """Eski veritabanlarına eksik kolonları ekler (kayıp olmadan)."""
    have = {r["name"] for r in c.execute("PRAGMA table_info(refs)").fetchall()}
    for col, ddl in (("starred", "INTEGER DEFAULT 0"), ("integrity", "TEXT"),
                     ("attachment", "TEXT"), ("user_id", "INTEGER")):
        if col not in have:
            c.execute(f"ALTER TABLE refs ADD COLUMN {col} {ddl}")
    hc = {r["name"] for r in c.execute("PRAGMA table_info(collections)").fetchall()}
    if "user_id" not in hc:
        c.execute("ALTER TABLE collections ADD COLUMN user_id INTEGER")
    hu = {r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()}
    if hu and "plan" not in hu:
        c.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'")
    if hu and "verified" not in hu:
        # Eski kullanıcılar zaten kullanıyordu — hepsini doğrulanmış say (kilitleme).
        c.execute("ALTER TABLE users ADD COLUMN verified INTEGER DEFAULT 0")
        c.execute("UPDATE users SET verified=1")

    # Performans indeksleri — user_id kolonları migration'dan SONRA kesin var.
    # Çok kiracılı (_scope) sorgular her istekte user_id filtreliyor; ölçekte kritik.
    # Her biri ayrı guard'lı: bir kolon/tablo yoksa yalnız o atlanır, başlatma bozulmaz.
    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_refs_user     ON refs(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_refs_user_del ON refs(user_id, deleted_at)",
        "CREATE INDEX IF NOT EXISTS idx_coll_user     ON collections(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_shares_email  ON shares(email)",
        "CREATE INDEX IF NOT EXISTS idx_shares_coll   ON shares(collection_id)",
        "CREATE INDEX IF NOT EXISTS idx_saved_user    ON saved_searches(user_id)",
    ):
        try:
            c.execute(ddl)
        except Exception as e:
            print(f"[db] indeks atlandı ({ddl.split()[5]}): {e}", flush=True)


# ---- kullanıcı kapsamı (auth açıkken) -------------------------------------
def _scope(q: str, args: list, table_alias: str = "") -> tuple[str, list]:
    """Geçerli kullanıcı varsa sorguya user_id filtresi ekler."""
    uid = current_user()
    if uid is not None:
        col = f"{table_alias}.user_id" if table_alias else "user_id"
        q += f" AND {col}=?"
        args.append(uid)
    return q, args


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _audit(c, action: str, entity: str, entity_id, detail: str = ""):
    c.execute("INSERT INTO audit (ts, action, entity, entity_id, detail) VALUES (?,?,?,?,?)",
              (_now(), action, entity, entity_id, detail))


def _row_to_ref(row: sqlite3.Row) -> dict:
    d = dict(row)
    for f in _JSON_FIELDS:
        try:
            d[f] = json.loads(d[f]) if d.get(f) else []
        except (TypeError, json.JSONDecodeError):
            d[f] = []
    try:
        d["integrity"] = json.loads(d["integrity"]) if d.get("integrity") else None
    except (TypeError, json.JSONDecodeError):
        d["integrity"] = None
    d["starred"] = bool(d.get("starred"))
    d["has_attachment"] = bool(d.get("attachment"))
    return d


# --------------------------------------------------------------- koleksiyonlar
def list_collections() -> list[dict]:
    q = ("SELECT col.*, "
         "(SELECT COUNT(*) FROM refs r WHERE r.collection_id=col.id AND r.deleted_at IS NULL) AS n "
         "FROM collections col WHERE col.deleted_at IS NULL")
    q, args = _scope(q, [], "col")
    q += " ORDER BY col.name"
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def create_collection(name: str, parent_id=None) -> int:
    with _conn() as c:
        cur = c.execute("INSERT INTO collections (name, parent_id, user_id, created_at) VALUES (?,?,?,?)",
                        (name.strip(), parent_id, current_user(), _now()))
        _audit(c, "create", "collection", cur.lastrowid, name)
        return cur.lastrowid


def rename_collection(cid: int, name: str):
    q, args = _scope("UPDATE collections SET name=? WHERE id=?", [name.strip(), cid])
    with _conn() as c:
        c.execute(q, args)
        _audit(c, "rename", "collection", cid, name)


def delete_collection(cid: int):
    """Soft-delete; içindeki referanslar 'koleksiyonsuz' (collection_id=NULL) kalır."""
    q, args = _scope("UPDATE collections SET deleted_at=? WHERE id=?", [_now(), cid])
    qr, ar = _scope("UPDATE refs SET collection_id=NULL, updated_at=? "
                    "WHERE collection_id=? AND deleted_at IS NULL", [_now(), cid])
    with _conn() as c:
        c.execute(q, args)
        c.execute(qr, ar)
        _audit(c, "delete", "collection", cid, "")


# ------------------------------------------------------------------ referanslar
_REF_COLS = ("collection_id", "type", "title", "authors", "journal", "iso", "year",
             "volume", "issue", "pages", "doi", "pmid", "pmcid", "abstract", "url",
             "publisher", "tags", "notes")


def _prep(data: dict) -> dict:
    out = {}
    for k in _REF_COLS:
        v = data.get(k)
        if k in _JSON_FIELDS:
            v = json.dumps(v or [], ensure_ascii=False)
        out[k] = v
    return out


def add_ref(data: dict) -> int:
    p = _prep(data)
    cols = ", ".join(p.keys()) + ", user_id, created_at, updated_at"
    ph = ", ".join("?" for _ in p) + ", ?, ?, ?"
    now = _now()
    with _conn() as c:
        cur = c.execute(f"INSERT INTO refs ({cols}) VALUES ({ph})",
                        (*p.values(), current_user(), now, now))
        _audit(c, "add", "ref", cur.lastrowid, data.get("title", "")[:80])
        return cur.lastrowid


def add_refs(items: list[dict], collection_id=None) -> list[int]:
    ids = []
    for it in items:
        if collection_id is not None:
            it = {**it, "collection_id": collection_id}
        ids.append(add_ref(it))
    return ids


def update_ref(rid: int, data: dict):
    p = _prep(data)
    sets = ", ".join(f"{k}=?" for k in p) + ", updated_at=?"
    q, args = _scope(f"UPDATE refs SET {sets} WHERE id=?", [*p.values(), _now(), rid])
    with _conn() as c:
        c.execute(q, args)
        _audit(c, "update", "ref", rid, data.get("title", "")[:80])


def get_ref(rid: int) -> dict | None:
    q, args = _scope("SELECT * FROM refs WHERE id=? AND deleted_at IS NULL", [rid])
    with _conn() as c:
        row = c.execute(q, args).fetchone()
    return _row_to_ref(row) if row else None


def list_refs(collection_id="all", search: str = "", tag: str = "", starred: bool = False) -> list[dict]:
    q = "SELECT * FROM refs WHERE deleted_at IS NULL"
    args: list = []
    if collection_id not in ("all", None, ""):
        if collection_id == "none":
            q += " AND collection_id IS NULL"
        else:
            q += " AND collection_id=?"
            args.append(int(collection_id))
    if search:
        q += " AND (title LIKE ? OR authors LIKE ? OR journal LIKE ? OR year LIKE ? OR doi LIKE ?)"
        s = f"%{search}%"
        args += [s, s, s, s, s]
    if tag:
        q += " AND tags LIKE ?"
        args.append(f'%"{tag}"%')
    if starred:
        q += " AND starred=1"
    q, args = _scope(q, args)
    q += " ORDER BY year DESC, id DESC"
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [_row_to_ref(r) for r in rows]


def set_attachment(rid: int, filename: str | None):
    q, args = _scope("UPDATE refs SET attachment=?, updated_at=? WHERE id=?", [filename, _now(), rid])
    with _conn() as c:
        c.execute(q, args)
        _audit(c, "attach" if filename else "detach", "ref", rid, filename or "")


def get_attachment(rid: int) -> str | None:
    q, args = _scope("SELECT attachment FROM refs WHERE id=?", [rid])
    with _conn() as c:
        row = c.execute(q, args).fetchone()
    return row["attachment"] if row else None


def toggle_star(rid: int) -> bool:
    qs, sa = _scope("SELECT starred FROM refs WHERE id=?", [rid])
    with _conn() as c:
        cur = c.execute(qs, sa).fetchone()
        if cur is None:                       # sahip değil / yok
            return False
        new = 0 if cur["starred"] else 1
        qu, ua = _scope("UPDATE refs SET starred=?, updated_at=? WHERE id=?", [new, _now(), rid])
        c.execute(qu, ua)
    return bool(new)


def set_integrity(rid: int, info: dict | None):
    q, args = _scope("UPDATE refs SET integrity=? WHERE id=?", [json.dumps(info) if info else None, rid])
    with _conn() as c:
        c.execute(q, args)


def list_tags() -> list[dict]:
    """Tüm etiketleri sayılarıyla döner."""
    counts: dict[str, int] = {}
    for r in list_refs("all"):
        for t in r.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": k, "n": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


def existing_keys() -> set[str]:
    """Aktif kütüphanedeki dedup anahtarları (kopya kontrolü için)."""
    keys = set()
    for r in list_refs("all"):
        doi = (r.get("doi") or "").lower()
        pmid = r.get("pmid") or ""
        title = "".join(ch for ch in (r.get("title") or "").lower() if ch.isalnum())[:60]
        for k in (doi, pmid, title):
            if k:
                keys.add(k)
    return keys


# --------------------------------------------------------------- çöp kutusu
def list_deleted() -> list[dict]:
    q, args = _scope("SELECT * FROM refs WHERE deleted_at IS NOT NULL", [])
    q += " ORDER BY deleted_at DESC LIMIT 200"
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [_row_to_ref(r) for r in rows]


def restore_ref(rid: int):
    q, args = _scope("UPDATE refs SET deleted_at=NULL, updated_at=? WHERE id=?", [_now(), rid])
    with _conn() as c:
        c.execute(q, args)
        _audit(c, "restore", "ref", rid, "")


def count_deleted() -> int:
    q, args = _scope("SELECT COUNT(*) FROM refs WHERE deleted_at IS NOT NULL", [])
    with _conn() as c:
        return c.execute(q, args).fetchone()[0]


# --------------------------------------------------------------- istatistik
def stats() -> dict:
    def s(q):
        return _scope(q, [])
    with _conn() as c:
        total = c.execute(*s("SELECT COUNT(*) FROM refs WHERE deleted_at IS NULL")).fetchone()[0]
        starred = c.execute(*s("SELECT COUNT(*) FROM refs WHERE deleted_at IS NULL AND starred=1")).fetchone()[0]
        flagged = c.execute(*s("SELECT COUNT(*) FROM refs WHERE deleted_at IS NULL AND integrity IS NOT NULL")).fetchone()[0]
        with_doi = c.execute(*s("SELECT COUNT(*) FROM refs WHERE deleted_at IS NULL AND doi<>''")).fetchone()[0]
        q, a = s("SELECT year, COUNT(*) n FROM refs WHERE deleted_at IS NULL AND year<>''")
        by_year = c.execute(q + " GROUP BY year ORDER BY year DESC LIMIT 15", a).fetchall()
        q, a = s("SELECT COALESCE(NULLIF(iso,''), journal) j, COUNT(*) n FROM refs WHERE deleted_at IS NULL")
        by_journal = c.execute(q + " GROUP BY j ORDER BY n DESC LIMIT 10", a).fetchall()
    return {
        "total": total, "starred": starred, "flagged": flagged, "with_doi": with_doi,
        "by_year": [{"year": r["year"], "n": r["n"]} for r in by_year if r["year"]],
        "by_journal": [{"journal": r["j"], "n": r["n"]} for r in by_journal if r["j"]],
    }


def delete_ref(rid: int):
    q, args = _scope("UPDATE refs SET deleted_at=?, updated_at=? WHERE id=?", [_now(), _now(), rid])
    with _conn() as c:
        c.execute(q, args)
        _audit(c, "delete", "ref", rid, "")


def move_refs(ids: list[int], collection_id):
    cid = None if collection_id in ("none", "", None) else int(collection_id)
    with _conn() as c:
        for rid in ids:
            q, args = _scope("UPDATE refs SET collection_id=?, updated_at=? WHERE id=?", [cid, _now(), rid])
            c.execute(q, args)
        _audit(c, "move", "ref", None, f"{len(ids)} kayıt -> {cid}")


def count_active() -> int:
    q, args = _scope("SELECT COUNT(*) FROM refs WHERE deleted_at IS NULL", [])
    with _conn() as c:
        return c.execute(q, args).fetchone()[0]


def recent_audit(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------- kullanıcılar
def create_user(email: str, password: str, name: str = "", plan: str = "free",
                verified: bool = False) -> int:
    from werkzeug.security import generate_password_hash
    from ..config import Config
    email_l = email.strip().lower()
    with _conn() as c:
        # OWNER (sınırsız + otomatik doğrulanmış) = REFLY_ADMIN_EMAILS'teki hesap.
        # PUBLIC'te "ilk kayıt owner" GÜVENSİZ (rastgele biri kapabilir); bu yüzden ilk-kayıt
        # kolaylığı SADECE hiç admin e-postası tanımlı DEĞİLKEN (yerel/tek kullanıcı) geçerli.
        first = c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        owner = (email_l in Config.REFLY_ADMIN_EMAILS) or (first and not Config.REFLY_ADMIN_EMAILS)
        use_plan = "unlimited" if owner else plan
        is_verified = 1 if (verified or owner) else 0
        # scrypt bazı sistemlerde (LibreSSL) yok; pbkdf2 her yerde çalışır
        pw_hash = generate_password_hash(password, method="pbkdf2:sha256")
        cur = c.execute(
            "INSERT INTO users (email, name, pw_hash, plan, verified, created_at) VALUES (?,?,?,?,?,?)",
            (email_l, name.strip(), pw_hash, use_plan, is_verified, _now()))
    _bust_user_count()   # yeni kayıt → sayaç önbelleğini düşür (sayı anında güncellenir)
    return cur.lastrowid


def set_verified(uid: int, value: bool = True):
    with _conn() as c:
        c.execute("UPDATE users SET verified=? WHERE id=?", (1 if value else 0, uid))


def is_verified(uid: int) -> bool:
    with _conn() as c:
        row = c.execute("SELECT verified FROM users WHERE id=?", (uid,)).fetchone()
    return bool(row and row["verified"])


def get_plan(uid: int) -> str:
    with _conn() as c:
        row = c.execute("SELECT plan FROM users WHERE id=?", (uid,)).fetchone()
    return (row["plan"] if row and row["plan"] else "free")


def set_plan(uid: int, plan: str):
    with _conn() as c:
        c.execute("UPDATE users SET plan=? WHERE id=?", (plan, uid))
        _audit(c, "plan", "user", uid, plan)


def usage_get(uid: int, period: str, metric: str) -> int:
    with _conn() as c:
        row = c.execute("SELECT count FROM usage WHERE user_id=? AND period=? AND metric=?",
                        (uid, period, metric)).fetchone()
    return row["count"] if row else 0


def usage_incr(uid: int, period: str, metric: str, n: int = 1):
    with _conn() as c:
        c.execute("INSERT INTO usage (user_id, period, metric, count) VALUES (?,?,?,?) "
                  "ON CONFLICT(user_id, period, metric) DO UPDATE SET count = count + ?",
                  (uid, period, metric, n, n))


def usage_all(uid: int, period: str) -> dict:
    with _conn() as c:
        rows = c.execute("SELECT metric, count FROM usage WHERE user_id=? AND period=?",
                         (uid, period)).fetchall()
    return {r["metric"]: r["count"] for r in rows}


def get_user_by_email(email: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    return dict(row) if row else None


def get_user(uid: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT id, email, name, verified FROM users WHERE id=?", (uid,)).fetchone()
    return dict(row) if row else None


def verify_user(email: str, password: str) -> dict | None:
    from werkzeug.security import check_password_hash
    u = get_user_by_email(email)
    if u and check_password_hash(u["pw_hash"], password):
        return {"id": u["id"], "email": u["email"], "name": u["name"],
                "verified": bool(u.get("verified"))}
    return None


def count_users() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# Kayıtlı kullanıcı sayacı — 60 sn önbellek (her sayfa yüklemesinde tam sorgu atma).
# Yeni kayıt olunca create_user() önbelleği düşürür → sayı anında artar.
_uc_cache = {"n": None, "ts": 0.0}
_UC_TTL = 60.0


def count_users_cached() -> int:
    import time
    now = time.monotonic()
    if _uc_cache["n"] is None or (now - _uc_cache["ts"]) > _UC_TTL:
        _uc_cache["n"] = count_users()
        _uc_cache["ts"] = now
    return _uc_cache["n"]


def _bust_user_count():
    _uc_cache["n"] = None


# ---- kayıtlı aramalar / konu alarmları -------------------------------------
def add_search(query: str, email: str = "") -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO saved_searches (user_id,query,email,last_ids,active,created_at) "
            "VALUES (?,?,?,'[]',1,?)", (current_user(), query.strip(), email.strip(), _now()))
        return cur.lastrowid


def list_searches() -> list[dict]:
    q, args = _scope("SELECT * FROM saved_searches WHERE 1=1", [])
    with _conn() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY id DESC", args).fetchall()]


def get_search(sid: int) -> dict | None:
    q, args = _scope("SELECT * FROM saved_searches WHERE id=?", [sid])
    with _conn() as c:
        r = c.execute(q, args).fetchone()
        return dict(r) if r else None


def delete_search(sid: int):
    q, args = _scope("DELETE FROM saved_searches WHERE id=?", [sid])
    with _conn() as c:
        c.execute(q, args)


def update_search_seen(sid: int, ids: list, checked: str):
    q, args = _scope("UPDATE saved_searches SET last_ids=?, last_checked=? WHERE id=?",
                     [json.dumps(ids), checked, sid])
    with _conn() as c:
        c.execute(q, args)


def all_active_searches() -> list[dict]:
    """Cron/toplu kontrol için — TÜM kullanıcıların aktif aramaları (kapsam yok)."""
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM saved_searches WHERE active=1").fetchall()]


# ---- ekip / paylaşımlı kütüphaneler ----------------------------------------
def current_user_email() -> str:
    uid = current_user()
    if uid is None:
        return ""
    u = get_user(uid)
    return (u or {}).get("email", "").lower()


def _owns_collection(cid: int) -> bool:
    q, args = _scope("SELECT id FROM collections WHERE id=? AND deleted_at IS NULL", [cid])
    with _conn() as c:
        return c.execute(q, args).fetchone() is not None


def share_collection(cid: int, email: str, role: str = "viewer") -> int | None:
    """Koleksiyonu bir e-posta ile paylaşır. SADECE koleksiyon sahibi yapabilir."""
    if not _owns_collection(cid):
        return None
    email = (email or "").strip().lower()
    role = "editor" if role == "editor" else "viewer"
    if not email:
        return None
    with _conn() as c:
        ex = c.execute("SELECT id FROM shares WHERE collection_id=? AND email=?", (cid, email)).fetchone()
        if ex:
            c.execute("UPDATE shares SET role=? WHERE id=?", (role, ex["id"]))
            return ex["id"]
        cur = c.execute("INSERT INTO shares (collection_id,owner_id,email,role,created_at) "
                        "VALUES (?,?,?,?,?)", (cid, current_user(), email, role, _now()))
        return cur.lastrowid


def list_shares(cid: int) -> list[dict]:
    """Bir koleksiyonun paylaşımları — sadece sahibi görebilir."""
    if not _owns_collection(cid):
        return []
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id,email,role,created_at FROM shares WHERE collection_id=? ORDER BY id", (cid,)).fetchall()]


def unshare(share_id: int) -> bool:
    uid = current_user()
    with _conn() as c:
        r = c.execute("SELECT owner_id FROM shares WHERE id=?", (share_id,)).fetchone()
        if not r:
            return False
        if uid is not None and r["owner_id"] != uid:
            return False
        c.execute("DELETE FROM shares WHERE id=?", (share_id,))
        return True


def shared_with_me() -> list[dict]:
    """Bana paylaşılmış koleksiyonlar (e-postama göre) + sahibi + kayıt sayısı."""
    email = current_user_email()
    if not email:
        return []
    with _conn() as c:
        rows = c.execute(
            "SELECT s.role, s.collection_id, c.name, s.owner_id FROM shares s "
            "JOIN collections c ON c.id=s.collection_id "
            "WHERE s.email=? AND c.deleted_at IS NULL", (email,)).fetchall()
        out = []
        for r in rows:
            n = c.execute("SELECT COUNT(*) FROM refs WHERE collection_id=? AND deleted_at IS NULL",
                          (r["collection_id"],)).fetchone()[0]
            owner = get_user(r["owner_id"]) or {}
            out.append({"collection_id": r["collection_id"], "name": r["name"], "role": r["role"],
                        "n": n, "owner": owner.get("email", "")})
        return out


def shared_role(cid: int) -> str | None:
    """Geçerli kullanıcının bu koleksiyon üzerindeki paylaşım rolü (yoksa None)."""
    email = current_user_email()
    if not email:
        return None
    with _conn() as c:
        r = c.execute("SELECT role FROM shares WHERE collection_id=? AND email=?", (cid, email)).fetchone()
        return r["role"] if r else None


def shared_collection_refs(cid: int) -> list[dict] | None:
    """Paylaşılan koleksiyonun kayıtları — SADECE kullanıcının paylaşımı varsa (yetki kontrolü)."""
    if shared_role(cid) is None:
        return None
    with _conn() as c:
        rows = c.execute("SELECT * FROM refs WHERE collection_id=? AND deleted_at IS NULL "
                         "ORDER BY id DESC", (cid,)).fetchall()
    return [_row_to_ref(r) for r in rows]
