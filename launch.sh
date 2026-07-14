#!/bin/bash
# Refly masaüstü başlatıcı — sunucuyu (reloader'sız) başlatır, hazır olunca tarayıcıyı açar.
cd "$(dirname "$0")" || exit 1

# Zaten çalışıyorsa tekrar başlatma
if ! /usr/bin/curl -s -m 2 http://127.0.0.1:5006/healthz >/dev/null 2>&1; then
  # Detached + reloader KAPALI (detached reloader ölüyor)
  nohup ./venv/bin/python -c "from app import create_app; create_app().run(host='127.0.0.1', port=5006, debug=False, use_reloader=False)" </dev/null >/tmp/refly.log 2>&1 &
fi

# Sunucu hazır olana kadar bekle (en çok ~20 sn)
for i in $(seq 1 40); do
  if /usr/bin/curl -s -m 1 http://127.0.0.1:5006/healthz >/dev/null 2>&1; then break; fi
  sleep 0.5
done

/usr/bin/open http://127.0.0.1:5006/home
