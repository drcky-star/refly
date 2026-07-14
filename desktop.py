"""Refly Desktop — aynı uygulamayı yerel bir pencerede açar (pywebview).

Tek tıkla masaüstü deneyimi: web sunucusunu arka planda başlatır, native pencerede gösterir.
    ./venv/bin/python desktop.py
"""
import threading
import webview
from app import create_app

app = create_app()


def _run():
    app.run(host="127.0.0.1", port=5099, debug=False, use_reloader=False)


if __name__ == "__main__":
    threading.Thread(target=_run, daemon=True).start()
    webview.create_window("Refly", "http://127.0.0.1:5099", width=1200, height=820, min_size=(900, 600))
    webview.start()
