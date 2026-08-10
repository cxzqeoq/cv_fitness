#!/usr/bin/env python3
import mimetypes
import os
import socket
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# JS грузится как ES-модули — важны корректные MIME-типы.
# На Windows mimetypes смотрит в реестр и может отдать .js как text/plain.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")

os.chdir(os.path.dirname(os.path.abspath(__file__)))


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    ip = lan_ip()
    print()
    print("Скелет поверх видео — локальный сервер")
    print(f"  ноутбук (камера работает):        http://localhost:{port}/")
    print(f"  телефон по LAN (БЕЗ камеры):      http://{ip}:{port}/")
    print("  телефон с камерой (HTTPS):")
    print(f"     npx localtunnel --port {port}")
    print(f"     cloudflared tunnel --url http://localhost:{port}")
    print("  Ctrl+C — остановить.")
    print()
    server = ThreadingHTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлено.")


if __name__ == "__main__":
    main()