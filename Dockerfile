FROM python:3.12-slim

WORKDIR /app

# Sistem bağımlılıkları (citeproc/lxml, docx için yeterli)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Kalıcı veri (SQLite + PDF ekleri + yedekler) için hacim
VOLUME ["/app/instance"]

ENV PORT=8000
EXPOSE 8000

# Üretim: gunicorn. TEK worker + çok thread ZORUNLU — otomatik referanslama işleri
# ve otomatik yedek arka plan thread'i belleğe bağlı; çok worker'da iş takibi bozulur.
# Yatay ölçekleme gerekirse job store'u Redis/DB'ye taşımak gerekir.
CMD ["gunicorn", "app:create_app()", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "180"]
