"""HTTP API кошелька для приложения «Казна».

Запуск: uvicorn backend.server:app --host 0.0.0.0 --port 8080
Доступ: каждый запрос должен нести заголовок X-Access-Key = ACCESS_KEY.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config
from .wallet import Ledger, TronWallet

log = logging.getLogger(__name__)

settings = config.load()
ledger = Ledger("data/ledger.json")
wallet = TronWallet(settings, ledger)

app = FastAPI(title="Казна API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _auth(key: str | None) -> None:
    if not settings.access_key or key != settings.access_key:
        raise HTTPException(status_code=401, detail="неверный ключ доступа")


class PayIn(BaseModel):
    to: str
    amount: float


@app.get("/api/summary")
def summary(x_access_key: str | None = Header(default=None)):
    _auth(x_access_key)
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


@app.post("/api/pay")
def pay(body: PayIn, x_access_key: str | None = Header(default=None)):
    _auth(x_access_key)
    return wallet.send_usdt(body.to, body.amount)


@app.get("/api/health")
def health():
    return {"ok": True, "live": settings.live}
