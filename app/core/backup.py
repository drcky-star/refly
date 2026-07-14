"""Yedekleme — veritabanı + PDF eklerini tek zip'te toplar, geri yükler ve
arka planda periyodik otomatik yedek alır.

(Bulut senkron ileride; bu modül yerel/indirilebilir yedek sağlar — data kaybolmasın.)
"""
from __future__ import annotations
import io
import time
import shutil
import zipfile
import threading
import datetime as dt
from pathlib import Path

from ..config import Config

_DB = Config.INSTANCE_DIR / "refly.db"
_ATTACH = Config.ATTACH_DIR
_BACKUP_DIR = Config.INSTANCE_DIR / "backups"


def make_zip_bytes() -> bytes:
    """db + ekleri içeren zip'i bellek içinde üretir (indirme için)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if _DB.exists():
            z.write(_DB, "refly.db")
        if _ATTACH.exists():
            for f in _ATTACH.glob("*.pdf"):
                z.write(f, f"attachments/{f.name}")
    return buf.getvalue()


def restore_from_zip(data: bytes) -> dict:
    """Zip'ten db + ekleri geri yükler (mevcutların üzerine yazar).
    Geri yüklemeden önce mevcut durumun bir güvenlik yedeğini alır."""
    snapshot(tag="restore-oncesi")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        if "refly.db" not in names:
            raise ValueError("Geçersiz yedek: refly.db yok")
        _ATTACH.mkdir(parents=True, exist_ok=True)
        with z.open("refly.db") as src, open(_DB, "wb") as dst:
            shutil.copyfileobj(src, dst)
        restored_pdf = 0
        for n in names:
            if n.startswith("attachments/") and n.endswith(".pdf"):
                with z.open(n) as src, open(_ATTACH / Path(n).name, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                    restored_pdf += 1
    return {"restored_pdf": restored_pdf}


def snapshot(tag: str = "") -> Path:
    """Anlık yerel yedek dosyası oluşturur (instance/backups/) ve ayarlıysa
    off-site (S3 uyumlu) kopyasını da yükler — sunucu/disk ölse bile veri kalır."""
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"refly-{stamp}{'-' + tag if tag else ''}.zip"
    path = _BACKUP_DIR / name
    data = make_zip_bytes()
    path.write_bytes(data)
    _prune(keep=12)
    if offsite_configured():
        try:
            push_offsite(data, name)
        except Exception as e:
            print(f"[backup] off-site yükleme başarısız: {e}", flush=True)
    return path


# --------------------------------------------------------- off-site (S3 uyumlu)
def offsite_configured() -> bool:
    """S3 uyumlu off-site yedek eksiksiz ayarlıysa True."""
    return bool(Config.BACKUP_S3_BUCKET and Config.BACKUP_S3_ACCESS_KEY
                and Config.BACKUP_S3_SECRET_KEY)


def _s3_client():
    """boto3 istemcisi (AWS S3 / DigitalOcean Spaces / Backblaze B2 / Cloudflare R2).
    boto3 kurulu değilse anlaşılır bir hata verir."""
    try:
        import boto3  # opsiyonel bağımlılık — sadece off-site yedek için
    except ImportError as e:
        raise RuntimeError("Off-site yedek için 'boto3' gerekli: pip install boto3") from e
    kw = {"aws_access_key_id": Config.BACKUP_S3_ACCESS_KEY,
          "aws_secret_access_key": Config.BACKUP_S3_SECRET_KEY}
    if Config.BACKUP_S3_ENDPOINT:
        kw["endpoint_url"] = Config.BACKUP_S3_ENDPOINT
    if Config.BACKUP_S3_REGION:
        kw["region_name"] = Config.BACKUP_S3_REGION
    return boto3.client("s3", **kw)


def push_offsite(data: bytes, name: str) -> str:
    """Yedek baytlarını S3 uyumlu depoya yükler. Yüklenen anahtarı döndürür."""
    key = f"{Config.BACKUP_S3_PREFIX.rstrip('/')}/{name}" if Config.BACKUP_S3_PREFIX else name
    _s3_client().put_object(Bucket=Config.BACKUP_S3_BUCKET, Key=key, Body=data,
                            ContentType="application/zip")
    return key


def _prune(keep: int = 12):
    files = sorted(_BACKUP_DIR.glob("refly-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[keep:]:
        f.unlink(missing_ok=True)


def list_snapshots() -> list[dict]:
    if not _BACKUP_DIR.exists():
        return []
    out = []
    for f in sorted(_BACKUP_DIR.glob("refly-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = f.stat()
        out.append({"name": f.name, "size_kb": round(st.st_size / 1024),
                    "when": dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    return out


def start_auto(interval_hours: float = 6.0):
    """Arka planda periyodik otomatik yedek başlatır (günde birkaç kez)."""
    def loop():
        # açılışta son yedek 20 saatten eskiyse hemen bir tane al
        snaps = list_snapshots()
        if not snaps:
            try:
                snapshot(tag="acilis")
            except Exception:
                pass
        while True:
            time.sleep(interval_hours * 3600)
            try:
                snapshot(tag="oto")
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True).start()
