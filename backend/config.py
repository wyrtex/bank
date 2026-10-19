"""Настройки бэкенда из переменных окружения (.env). Секреты — только здесь, НИКОГДА в git."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def _list(v: str) -> list[str]:
    return [x.strip() for x in (v or "").replace(";", ",").split(",") if x.strip()]


@dataclass
class Settings:
    tron_api_key: str                 # ключ TronGrid
    address: str                      # адрес горячего кошелька (T...)
    private_key: str                  # приватный ключ горячего кошелька (подпись переводов)
    access_key: str                   # ключ доступа приложения к API
    allowlist: list[str] = field(default_factory=list)  # кому вообще можно платить
    per_tx_limit: float = 50          # максимум за один перевод, USDT
    daily_limit: float = 300          # максимум за сутки, USDT
    reserve_trx: float = 20           # не трогаем этот запас TRX (газ)
    live: bool = False                # False — «сухой прогон» (ничего не отправляем), True — реальные переводы
    node_url: str = "https://api.trongrid.io"


def load() -> Settings:
    try:  # подхватываем backend/.env, если он есть, чтобы не экспортировать переменные вручную
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parent / ".env")
    except Exception:
        pass
    env = os.environ.get
    return Settings(
        tron_api_key=env("TRON_API_KEY", "").strip(),
        address=env("WALLET_ADDRESS", "").strip(),
        private_key=env("WALLET_PRIVATE_KEY", "").strip(),
        access_key=env("ACCESS_KEY", "").strip(),
        allowlist=_list(env("ALLOWLIST", "")),
        per_tx_limit=float(env("PER_TX_LIMIT", "50")),
        daily_limit=float(env("DAILY_LIMIT", "300")),
        reserve_trx=float(env("RESERVE_TRX", "20")),
        live=_bool(env("WALLET_LIVE", "0")),
        node_url=env("TRON_NODE_URL", "https://api.trongrid.io").strip(),
    )
