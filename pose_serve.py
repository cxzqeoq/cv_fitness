#!/usr/bin/env python3
import os
import sys
from http.server import ThreadingHTTPServer

from pose_http import NoCacheHandler, lan_ip

os.chdir(os.path.dirname(os.path.abspath(__file__)))


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
    server = ThreadingHTTPServer(("0.0.0.0", port), NoCacheHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nостановлено.")


if __name__ == "__main__":
    main()
