"""HTTP API кошелька «Казна» — на чистой стандартной библиотеке Python (без установки пакетов).

Запуск из корня репозитория:
    python3 -m backend.server
Хост/порт — из переменных HOST (127.0.0.1) и PORT (8080).
Каждый запрос (кроме /api/health) должен нести заголовок X-Access-Key = ACCESS_KEY.
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config
from .wallet import Ledger, TronWallet

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

settings = config.load()
ledger = Ledger("data/ledger.json")
wallet = TronWallet(settings, ledger)


def summary() -> dict:
    data = {
        "address": settings.address,
        "live": settings.live,
        "limits": {"per_tx": settings.per_tx_limit, "daily": settings.daily_limit},
        "allowlist": settings.allowlist,
    }
    try:
        data["usdt"] = round(wallet.usdt_balance(), 2)
        data["trx"] = round(wallet.trx_balance(), 2)
    except Exception as e:
        log.warning("Баланс: %s", e)
        data["error"] = f"не прочитал баланс: {e}"
    try:
        data["transfers"] = wallet.recent_transfers()
    except Exception as e:
        log.warning("История: %s", e)
        data["transfers"] = []
    return data


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        return bool(settings.access_key) and self.headers.get("X-Access-Key") == settings.access_key

    def do_OPTIONS(self):  # preflight CORS
        self._send(200, {})

    def do_GET(self):
        if self.path == "/api/health":
            return self._send(200, {"ok": True, "live": settings.live})
        if not self._authed():
            return self._send(401, {"detail": "неверный ключ доступа"})
        if self.path == "/api/summary":
            return self._send(200, summary())
        self._send(404, {"detail": "не найдено"})

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"detail": "неверный ключ доступа"})
        if self.path == "/api/pay":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                return self._send(200, wallet.send_usdt(str(body.get("to", "")), float(body.get("amount", 0))))
            except Exception as e:
                return self._send(400, {"detail": f"плохой запрос: {e}"})
        self._send(404, {"detail": "не найдено"})

    def log_message(self, *a):  # не засоряем вывод
        return


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    log.info("Казна API на http://%s:%s (live=%s)", host, port, settings.live)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
