#!/usr/bin/env python3
"""Live debt-state exporter for NeuroMarkets.

Uses the exact debt calculator from Evaluador.py and writes an auditable
snapshot to debt_state.json. It does not open or close positions and does not
change trading decisions.
"""
import json
import os
import time
from datetime import datetime, timezone

from EthSession import CapitalOP
from Evaluador import DEBT_RATE_PER_HOUR, _calculate_accumulated_debt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEBT_STATE_PATH = os.path.join(BASE_DIR, "debt_state.json")
CAPITAL_STATE_PATH = os.path.join(BASE_DIR, "capital_state.json")
INTERVAL_SECONDS = float(os.getenv("DEBT_MONITOR_INTERVAL", "5"))
LOG_EVERY_SECONDS = float(os.getenv("DEBT_MONITOR_LOG_INTERVAL", "30"))


def _atomic_write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _hours_open(created):
    if not created:
        return 0.0
    try:
        text = str(created)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    except Exception:
        return 0.0


def _flatten_positions(raw):
    if isinstance(raw, dict) and "BUY" in raw and "SELL" in raw:
        return list(raw.get("BUY", [])) + list(raw.get("SELL", []))
    if isinstance(raw, dict) and isinstance(raw.get("positions"), list):
        return raw["positions"]
    if isinstance(raw, list):
        return raw
    return []


def build_debt_state(capital_ops):
    raw = capital_ops.get_open_positions()
    items = _flatten_positions(raw)

    positions = {}
    total_debt = 0.0
    buy_debt = 0.0
    sell_debt = 0.0
    total_upl = 0.0
    buy_count = 0
    sell_count = 0

    for wrapper in items:
        if not isinstance(wrapper, dict):
            continue
        pos = wrapper.get("position", wrapper)
        market = wrapper.get("market", {}) if isinstance(wrapper, dict) else {}
        if not isinstance(pos, dict):
            continue

        deal_id = pos.get("dealId")
        if not deal_id:
            continue

        direction = str(pos.get("direction", "N/A")).upper()
        try:
            size = float(pos.get("size", 0) or 0)
        except (TypeError, ValueError):
            size = 0.0
        try:
            upl = float(pos.get("upl", 0) or 0)
        except (TypeError, ValueError):
            upl = 0.0

        created = pos.get("createdDateUTC") or pos.get("createdDate") or pos.get("created")
        hours = _hours_open(created)
        debt = _calculate_accumulated_debt(hours, size)
        net_after_debt = upl - debt
        deficit = max(debt - upl, 0.0)

        total_debt += debt
        total_upl += upl
        if direction == "BUY":
            buy_count += 1
            buy_debt += debt
        elif direction == "SELL":
            sell_count += 1
            sell_debt += debt

        positions[deal_id] = {
            "deal_id": deal_id,
            "epic": market.get("epic", "ETHUSD"),
            "direction": direction,
            "size": size,
            "entry_price": pos.get("level"),
            "created": created,
            "hours_open": round(hours, 4),
            "upl": round(upl, 6),
            "debt": round(debt, 6),
            "net_after_debt": round(net_after_debt, 6),
            "debt_covered": upl >= debt,
            "deficit_to_cover": round(deficit, 6),
        }

    state = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "Evaluador._calculate_accumulated_debt",
        "model": "internal_overnight_debt",
        "debt_rate_per_hour": DEBT_RATE_PER_HOUR,
        "debt_rate_per_24h": DEBT_RATE_PER_HOUR * 24.0,
        "position_count": len(positions),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "total_debt": round(total_debt, 6),
        "buy_debt": round(buy_debt, 6),
        "sell_debt": round(sell_debt, 6),
        "total_upl": round(total_upl, 6),
        "portfolio_net_after_debt": round(total_upl - total_debt, 6),
        "positions": positions,
    }
    return state


def merge_into_capital_state(debt_state):
    try:
        with open(CAPITAL_STATE_PATH, "r", encoding="utf-8") as f:
            capital = json.load(f)
        if not isinstance(capital, dict):
            return
        capital["debt_state"] = {
            "timestamp": debt_state["timestamp"],
            "position_count": debt_state["position_count"],
            "total_debt": debt_state["total_debt"],
            "buy_debt": debt_state["buy_debt"],
            "sell_debt": debt_state["sell_debt"],
            "total_upl": debt_state["total_upl"],
            "portfolio_net_after_debt": debt_state["portfolio_net_after_debt"],
            "source": debt_state["source"],
        }
        _atomic_write_json(CAPITAL_STATE_PATH, capital)
    except Exception:
        pass


def main():
    ops = CapitalOP()
    ops.authenticate()
    try:
        if getattr(ops, "session_token", None):
            ops.ensure_correct_account()
    except Exception:
        pass

    last_log = 0.0
    while True:
        try:
            state = build_debt_state(ops)
            _atomic_write_json(DEBT_STATE_PATH, state)
            merge_into_capital_state(state)

            now = time.time()
            if now - last_log >= LOG_EVERY_SECONDS:
                print(
                    "[DEBT_STATE] "
                    f"positions={state['position_count']} "
                    f"BUY={state['buy_count']} SELL={state['sell_count']} "
                    f"debt=${state['total_debt']:.4f} "
                    f"upl=${state['total_upl']:+.4f} "
                    f"net_after_debt=${state['portfolio_net_after_debt']:+.4f}",
                    flush=True,
                )
                last_log = now
        except Exception as e:
            print(f"[DEBT_STATE][ERROR] {e}", flush=True)
            try:
                ops.authenticate()
                if getattr(ops, "session_token", None):
                    ops.ensure_correct_account()
            except Exception:
                pass
        time.sleep(max(1.0, INTERVAL_SECONDS))


if __name__ == "__main__":
    main()
