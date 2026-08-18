#!/usr/bin/env python3
"""Общий HTTP-слой для pose_serve.py и pose_qr.py.

Что здесь:
  * MIME-типы для ES-модулей — иначе на Windows .js отдаётся как text/plain
    и браузер отказывается их грузить («unexpected token import»).
  * NoCacheHandler — запрет кэширования: браузер иначе кэширует ES-модули по
    отдельности и после правок держит старый utils.js при новых импортёрах.
  * Whitelist приватности — наружу отдаются только файлы приложения и видео-
    фикстуры тестов; some/, *.csv и dotfiles в LAN/туннель не светятся.
  * lan_ip — адрес для QR/LAN-подсказок.
"""
import mimetypes
import re
import socket
from http.server import SimpleHTTPRequestHandler

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")

# Что можно отдавать снаружи. Всё остальное — 404: личные видео (some/),
# экспорты (*.csv) и служебные файлы не должны быть доступны в LAN/туннеле.
ALLOWED = re.compile(
    r"^/(index\.html)?$"
    r"|^/js/[A-Za-z0-9_\-/]+\.(?:js|mjs)$"
    r"|^/styles\.css$"
    r"|^/tests/fixtures/[A-Za-z0-9_\-]+\.mp4$"
)


class NoCacheHandler(SimpleHTTPRequestHandler):
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


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()
