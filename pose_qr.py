#!/usr/bin/env python3
"""QR для "Скелет поверх видео".

Использование:
  python pose_qr.py            поднимает сервер + https-туннель, показывает QR
  python pose_qr.py --local    только LAN-адрес (без камеры)
  python pose_qr.py <url>      показать QR для любой ссылки
  python pose_qr.py --port 8NNN   другой порт

Требует: pip install segno   (и npx для туннеля).
"""
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# JS грузится как ES-модули — важны корректные MIME-типы.
# На Windows mimetypes смотрит в реестр и может отдать .js как text/plain.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")

os.chdir(os.path.dirname(os.path.abspath(__file__)))

HINT = (
    "Отсканируй телефоном.\n"
    "Если localhost показал предупреждение — нажми «Bypass/Continue».\n"
    "Разреши доступ к камере. Ctrl+C в консоли — остановить."
)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def tunnel_url(port):
    """Запускает npx localtunnel и ждёт, пока он напечатает https-URL."""
    try:
        import segno  # noqa: F401  (проверка наличия без вызова)
    except ImportError:
        pass
    cmd = shutil.which("npx") or "npx"
    proc = subprocess.Popen([cmd, "-y", "localtunnel", "--port", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, encoding="utf-8", errors="replace")
    out = {"url": None}
    found = threading.Event()
    def reader():
        for line in proc.stdout:
            plain = line.strip()
            m = re.search(r"https://\S+", plain)
            if m:
                out["url"] = m.group(0).rstrip(".,);").split("?")[0]
                found.set()
                return
    threading.Thread(target=reader, daemon=True).start()
    try:
        found.wait(timeout=90)
    except KeyboardInterrupt:
        pass
    return out["url"], proc


def open_qr(url):
    try:
        import segno
        qr = segno.make(url, error="m")
        tmp = tempfile.mkdtemp(prefix="pose_qr_")
        png = os.path.join(tmp, "qr.png")
        qr.save(png, scale=12, border=2)
        path = os.path.join(tmp, "index.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"""<!doctype html><html lang=\"ru\"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QR — Скелет поверх видео</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;background:#0f1115;color:#eael;font-family:system-ui,sans-serif;text-align:center;padding:16px}}
b{{margins}}h1{{font-size:18px;font-weight:500}}code{{font-size:14px;background:#1c2027;padding:8px 12px;border-radius:8px;word-break:break-all;max-width:90vw}}p{{color:#9aa;font-size:14px;line-height:1.5}}img{{width:min(70vw,420px);height:auto;background:#fff;padding:10px;border-radius:12px}}</style></head>
<body><h1>Скелет поверх видео</h1>
<img src="qr.png" alt="QR">
<code>{url}</code>
<p>{HINT}</p></body></html>""")
        webbrowser.open("file:///" + path.replace("\\", "/"))
    except Exception as e:
        print(f"Не удалось показать QR: {e}")
        print(f"Открой ссылку вручную: {url}")


def print_console_qr(url):
    print(f"\nURL для телефона: {url}\n")
    try:
        import segno
        segno.make(url).terminal()
    except Exception:
        pass


def main():
    args = sys.argv[1:]

    if "-h" in args or "--help" in args:
        print(__doc__)
        return

    # --port N может стоять где угодно
    port = 8000
    while "--port" in args:
        i = args.index("--port")
        if len(args) > i + 1:
            try: port = int(args[i + 1])
            except ValueError: pass
        args = args[:i] + args[i + 2:] if len(args) > i + 1 else args[:i] + args[i + 1:]

    # Режим: передали URL аргументом
    custom = [a for a in args if a.startswith("http")]
    if custom:
        url = custom[0]
        print(f"QR для: {url}")
        print_console_qr(url)
        open_qr(url)
        return

    local_only = "--local" in args

    ip = lan_ip()
    local_url = f"http://{ip}:{port}/"

    handler = SimpleHTTPRequestHandler
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Локальный сервер: http://localhost:{port}/")

    proc = None
    if local_only:
        print("Режим --local: показываю LAN-адрес (камеры на телефоне НЕ будет).")
        print_console_qr(local_url)
        open_qr(local_url)
    else:
        print("\nСкелет поверх видео — поднимаем туннель…")
        url, proc = tunnel_url(port)
        if url:
            print(f"\nТуннель готов: {url}")
            print_console_qr(url)
            open_qr(url)
        else:
            print("\nТуннель не поднялся за 90 с. Показываю LAN-адрес (камера не будет работать).")
            print_console_qr(local_url)
            open_qr(local_url)

    print("\nCtrl+C — остановить.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        if proc:
            try: proc.terminate()
            except Exception: pass


if __name__ == "__main__":
    main()