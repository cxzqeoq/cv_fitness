#!/usr/bin/env python3
"""pose_debug.py — локальный сервер для эксперимента сегментации (segtest/).

Самодостаточный: не зависит от pose_http.py реального проекта.
Отдаёт только debug_seg.html и js/*.js|mjs (видео/модель грузятся
через <input type=file>, серверу не нужны), с правильным MIME для
ES-модулей (.js иначе на Windows отдаётся как text/plain) и без кэша.

Запуск:
    python pose_debug.py            # порт 8000 (если занят — свободный)
    python pose_debug.py 9000       # явный порт

После старта автоматически открывается http://localhost:<port>/debug_seg.html.
Ctrl+C — остановить.
"""
import mimetypes
import os
import re
import socket
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")

# Наружу — только файлы эксперимента.
ALLOWED = re.compile(
    r"^/debug_seg\.html$"
    r"|^/js/[A-Za-z0-9_\-/]+\.(?:js|mjs)$"
)


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        # Cross-origin isolation: включает многопоточность MediaPipe WASM.
        # Без этого детекция идёт в один поток CPU (~70 мс/кадр вместо ~15 мс).
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        super().end_headers()

    def _allowed(self):
        return bool(ALLOWED.match(self.path.split("?", 1)[0]))

    def do_GET(self):
        if not self._allowed():
            self.send_error(404, "Not Found")
            return
        super().do_GET()

    def do_HEAD(self):
        if not self._allowed():
            self.send_error(404, "Not Found")
            return
        super().do_HEAD()


def free_port(pref):
    """Порт pref, если свободен, иначе — любой свободный."""
    for p in (pref, 0):
        s = socket.socket()
        try:
            s.bind(("0.0.0.0", p))
            return s.getsockname()[1]
        except OSError:
            pass
        finally:
            s.close()
    return 0


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    port = int(sys.argv[1]) if len(sys.argv) > 1 else free_port(8000)
    threading.Timer(0.8, lambda: webbrowser.open(f"http://localhost:{port}/debug_seg.html")).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print()
    print("Эксперимент сегментации — локальный сервер (segtest/)")
    print(f"  http://localhost:{port}/debug_seg.html  (вкладка откроется сама)")
    print("  Ctrl+C — остановить.")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлено.")


if __name__ == "__main__":
    main()