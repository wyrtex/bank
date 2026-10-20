"""Защита переводов: белый список, лимиты, дневной лимит, сухой прогон."""

from backend.config import Settings
from backend.wallet import Ledger, TronWallet, check_payment

A, B = "TADDR_ALLOWED_1", "TADDR_ALLOWED_2"
BAD = "TADDR_NOT_LISTED"


def test_check_rejects_unlisted_address():
    ok, why = check_payment(BAD, 10, allowlist=[A, B], per_tx=50, daily_limit=300, spent_today=0)
    assert not ok and "белом списке" in why


def test_check_rejects_over_per_tx():
    ok, why = check_payment(A, 80, allowlist=[A], per_tx=50, daily_limit=300, spent_today=0)
    assert not ok and "лимита на перевод" in why


def test_check_rejects_over_daily():
    ok, why = check_payment(A, 40, allowlist=[A], per_tx=50, daily_limit=100, spent_today=70)
    assert not ok and "дневной лимит" in why


def test_check_allows_within_rules():
    ok, why = check_payment(A, 40, allowlist=[A], per_tx=50, daily_limit=300, spent_today=10)
    assert ok and why == ""


def test_empty_allowlist_blocks_nothing_by_list_but_limits_apply():
    # пустой белый список = ограничение по адресам выключено, лимиты всё равно работают
    assert check_payment(BAD, 10, allowlist=[], per_tx=50, daily_limit=300, spent_today=0)[0]
    assert not check_payment(BAD, 60, allowlist=[], per_tx=50, daily_limit=300, spent_today=0)[0]


def test_ledger_rolls_over_by_day(tmp_path):
    led = Ledger(tmp_path / "l.json")
    led.record("2026-10-20", A, 30, "tx1")
    assert led.spent_today("2026-10-20") == 30
    assert led.spent_today("2026-10-21") == 0  # новый день — счётчик обнулился


def _wallet(tmp_path, live=False, **kw):
    s = Settings(tron_api_key="", address="TME", private_key="", access_key="k",
                 allowlist=[A], per_tx_limit=50, daily_limit=100, live=live, **kw)
    return TronWallet(s, Ledger(tmp_path / "l.json"))


def test_dry_run_does_not_send_but_counts(tmp_path):
    w = _wallet(tmp_path, live=False)
    r = w.send_usdt(A, 40)
    assert r["status"] == "dry_run" and w.ledger.spent_today(__import__("datetime").date.today().isoformat()) == 40


def test_over_limit_needs_approval(tmp_path):
    w = _wallet(tmp_path)
    r = w.send_usdt(A, 90)
    assert r["status"] == "needs_approval"


def test_blocked_address(tmp_path):
    w = _wallet(tmp_path)
    r = w.send_usdt(BAD, 10)
    assert r["status"] == "blocked" and "белом списке" in r["reason"]


def test_daily_limit_blocks_second_payment(tmp_path):
    w = _wallet(tmp_path, live=False)  # дневной лимит 100
    assert w.send_usdt(A, 45)["status"] == "dry_run"
    assert w.send_usdt(A, 45)["status"] == "dry_run"  # 90 всего
    assert w.send_usdt(A, 45)["status"] == "blocked"  # 135 > 100
