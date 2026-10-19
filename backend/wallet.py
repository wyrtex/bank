"""Кошелёк USDT (TRC20, сеть Tron): баланс, история, перевод с защитой.

Безопасность денег (переводы необратимы):
- белый список: платить можно только на заранее внесённые адреса;
- лимит на один перевод и суммарный дневной лимит;
- запас TRX на газ не трогаем;
- WALLET_LIVE=0 (по умолчанию) — «сухой прогон»: всё проверяем и считаем, но в сеть НЕ отправляем.
  Реальные переводы включаются осознанно (WALLET_LIVE=1), после теста на копейках.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)

USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"  # USDT TRC20, mainnet
USDT_DECIMALS = 6


def check_payment(to: str, amount: float, *, allowlist: list[str], per_tx: float,
                  daily_limit: float, spent_today: float) -> tuple[bool, str]:
    """Чистая проверка правил (без сети). (ok, причина отказа)."""
    if amount <= 0:
        return False, "сумма должна быть больше нуля"
    if allowlist and to not in allowlist:
        return False, "адрес не в белом списке — платёж запрещён"
    if amount > per_tx:
        return False, f"больше лимита на перевод ({per_tx} USDT) — нужно подтверждение"
    if spent_today + amount > daily_limit:
        return False, f"превышен дневной лимит ({daily_limit} USDT): сегодня уже {spent_today:g}"
    return True, ""


@dataclass
class Decision:
    ok: bool
    reason: str = ""
    needs_approval: bool = False


class Ledger:
    """Сколько потрачено за сегодня и журнал переводов — в json-файле (вне git)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = {"day": "", "spent": 0.0, "log": []}
        try:
            self.data.update(json.loads(self.path.read_text("utf-8")))
        except Exception:
            pass

    def _roll(self, today: str) -> None:
        if self.data.get("day") != today:
            self.data["day"], self.data["spent"] = today, 0.0

    def spent_today(self, today: str) -> float:
        self._roll(today)
        return float(self.data.get("spent", 0.0))

    def record(self, today: str, to: str, amount: float, tx: str) -> None:
        self._roll(today)
        self.data["spent"] = float(self.data.get("spent", 0.0)) + amount
        self.data.setdefault("log", []).insert(0, {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "to": to, "amount": amount, "tx": tx})
        self.data["log"] = self.data["log"][:200]
        self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            log.exception("Не сохранил журнал кошелька")


class TronWallet:
    def __init__(self, settings: Settings, ledger: Ledger):
        self.s = settings
        self.ledger = ledger
        self._client = None
        self._contract = None

    # ---------- подключение к сети (ленивое) ----------

    def _conn(self):
        if self._client is None:
            from tronpy import Tron
            from tronpy.providers import HTTPProvider
            provider = HTTPProvider(self.s.node_url, api_key=self.s.tron_api_key or None)
            self._client = Tron(provider=provider)
            self._contract = self._client.get_contract(USDT_CONTRACT)
        return self._client, self._contract

    # ---------- чтение (безопасно) ----------

    def usdt_balance(self) -> float:
        _, contract = self._conn()
        raw = contract.functions.balanceOf(self.s.address)
        return raw / 10 ** USDT_DECIMALS

    def trx_balance(self) -> float:
        client, _ = self._conn()
        return client.get_account_balance(self.s.address)

    def recent_transfers(self, limit: int = 20) -> list[dict]:
        """Последние движения USDT по адресу — через публичный REST TronGrid."""
        import requests
        url = f"{self.s.node_url}/v1/accounts/{self.s.address}/transactions/trc20"
        headers = {"TRON-PRO-API-KEY": self.s.tron_api_key} if self.s.tron_api_key else {}
        r = requests.get(url, params={"limit": limit, "contract_address": USDT_CONTRACT},
                         headers=headers, timeout=20)
        r.raise_for_status()
        out = []
        for t in r.json().get("data", []):
            amount = int(t.get("value", 0)) / 10 ** int(t.get("token_info", {}).get("decimals", USDT_DECIMALS))
            incoming = t.get("to") == self.s.address
            out.append({"ts": t.get("block_timestamp"), "amount": amount, "incoming": incoming,
                        "from": t.get("from"), "to": t.get("to"), "tx": t.get("transaction_id")})
        return out

    # ---------- перевод (с защитой) ----------

    def plan_payment(self, to: str, amount: float) -> Decision:
        today = dt.date.today().isoformat()
        ok, reason = check_payment(to, amount, allowlist=self.s.allowlist, per_tx=self.s.per_tx_limit,
                                   daily_limit=self.s.daily_limit, spent_today=self.ledger.spent_today(today))
        if not ok:
            # «больше лимита на перевод» — это не запрет, а повод спросить продавца
            needs = reason.startswith("больше лимита")
            return Decision(False, reason, needs_approval=needs)
        return Decision(True)

    def send_usdt(self, to: str, amount: float) -> dict:
        """Отправить USDT с соблюдением правил. Возвращает {status, tx|reason}."""
        decision = self.plan_payment(to, amount)
        if not decision.ok:
            return {"status": "needs_approval" if decision.needs_approval else "blocked",
                    "reason": decision.reason}
        today = dt.date.today().isoformat()
        if not self.s.live:
            # сухой прогон — ничего не отправляем, только фиксируем, что прошло бы
            self.ledger.record(today, to, amount, tx="DRY-RUN")
            return {"status": "dry_run", "to": to, "amount": amount,
                    "note": "WALLET_LIVE=0 — реальный перевод не выполнен"}
        client, contract = self._conn()
        from tronpy.keys import PrivateKey
        priv = PrivateKey(bytes.fromhex(self.s.private_key))
        txn = (contract.functions.transfer(to, int(round(amount * 10 ** USDT_DECIMALS)))
               .with_owner(self.s.address).fee_limit(40_000_000).build().sign(priv).broadcast())
        tx_id = txn.txid
        self.ledger.record(today, to, amount, tx=tx_id)
        return {"status": "sent", "to": to, "amount": amount, "tx": tx_id}
