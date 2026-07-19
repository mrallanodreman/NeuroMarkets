"""
EthBoy Dashboard Server.

Servidor local que expone los archivos de estado del bot como API JSON.
Abre http://localhost:8765 en el navegador.
"""
import csv
import glob
import http.server
import json
import os
import sys
import threading
import webbrowser
from datetime import datetime, timezone

# Importar EthSession desde Demos
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "Demos"))
try:
    from EthSession import CapitalOP
    ETHSESSION_AVAILABLE = True
except ImportError:
    ETHSESSION_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEMOS_DIR = os.path.join(BASE_DIR, "Demos")  # EthBoy escribe sus datos aquí
PORT = 8765
DEBT_RATE_PER_HOUR = 0.01 / 24.0  # $ flat por posición por hora (sync con Evaluador.py)

DASHBOARD_HTML = os.path.join(BASE_DIR, "dashboard.html")

# 🔹 INSTANCIA GLOBAL DE CAPITAL_OPS
# Se inicializa una sola vez al arrancar el servidor
CAPITAL_OPS = None

def initialize_capital_ops():
    """Inicializa la instancia global de CapitalOP una sola vez."""
    global CAPITAL_OPS
    if not ETHSESSION_AVAILABLE or CAPITAL_OPS is not None:
        return

    try:
        CAPITAL_OPS = CapitalOP()
        CAPITAL_OPS.authenticate()
        print("[INFO] ✅ CapitalOP autenticado correctamente")
    except Exception as e:
        print(f"[ERROR] ❌ Error al autenticar CapitalOP: {e}")
        CAPITAL_OPS = None


def read_json(filename):
    # Buscar primero en Demos/ (donde EthBoy escribe), luego en raíz
    for base in [DEMOS_DIR, BASE_DIR]:
        path = os.path.join(base, filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def _hours_open_from_created(created_str):
    if not created_str:
        return None
    try:
        ts = str(created_str)
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        dt_created = datetime.fromisoformat(ts)
        if dt_created.tzinfo is None:
            dt_created = dt_created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt_created).total_seconds() / 3600.0
    except Exception:
        return None


def read_last_process_line():
    # Buscar en Demos/ primero
    path = os.path.join(DEMOS_DIR, "process_data.jsonl")
    if not os.path.exists(path):
        path = os.path.join(BASE_DIR, "process_data.jsonl")
    try:
        with open(path, "rb") as f:
            # Leer última línea eficientemente
            f.seek(0, 2)
            end = f.tell()
            pos = max(0, end - 4096)
            f.seek(pos)
            lines = f.read().decode("utf-8", errors="replace").strip().split("\n")
            for line in reversed(lines):
                line = line.strip()
                if line:
                    return json.loads(line)
    except Exception:
        pass
    return {}


def read_last_n_process_lines(n=2500):
    # Buscar en Demos/ primero
    path = os.path.join(DEMOS_DIR, "process_data.jsonl")
    if not os.path.exists(path):
        path = os.path.join(BASE_DIR, "process_data.jsonl")
    results = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            end = f.tell()
            # Leer últimos 2.5MB para conseguir ~2500 líneas
            pos = max(0, end - 2621440)
            f.seek(pos)
            lines = f.read().decode("utf-8", errors="replace").strip().split("\n")
            for line in reversed(lines):
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except Exception:
                        pass
                    if len(results) >= n:
                        break
    except Exception:
        pass
    return list(reversed(results))


def _parse_ts_to_epoch(ts_str):
    """Convierte un timestamp string (ISO o 'YYYY-MM-DD HH:MM:SS') a segundos epoch."""
    if not ts_str:
        return None
    try:
        # Normalizar: quitar timezone si viene con +00:00 o Z, tomar los primeros 19 chars
        s = str(ts_str).replace("T", " ")[:19]
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


def read_last_closed_positions(n=200):
    """
    Lee y combina posiciones cerradas de tres fuentes, evitando duplicados:
    1. web_closed_positions.json  — cierres detectados por Evaluador
    2. trade_closures_log.json    — cierres registrados por el bot (con razón)
    3. funds_history*.csv         — exportación oficial de Capital.com

    Deduplicación:
    - Entre JSON: por dealId
    - CSV vs JSON: por timestamp (±5 min) + monto P&L (±0.01)
    - Entre filas CSV: por Id de transacción
    """
    combined = {}  # clave -> record

    # ── Fuente 1: web_closed_positions.json ──
    for base in [DEMOS_DIR, BASE_DIR]:
        path = os.path.join(base, "web_closed_positions.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for rec in data:
                        key = rec.get("dealId") or rec.get("timestamp", "")
                        combined[key] = rec
            except Exception:
                pass
            break

    # ── Fuente 2: trade_closures_log.json ──
    for base in [DEMOS_DIR, BASE_DIR]:
        path = os.path.join(base, "trade_closures_log.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for rec in data:
                        deal_id = rec.get("deal_id") or rec.get("dealId", "")
                        if deal_id not in combined:
                            combined[deal_id] = {
                                "dealId": deal_id,
                                "timestamp": rec.get("timestamp"),
                                "direction": rec.get("direction"),
                                "epic": rec.get("epic"),
                                "entry_price": None,
                                "last_upl": rec.get("upl"),
                                "last_upl_pct": None,
                                "max_profit_pct": None,
                                "hours_open": None,
                                "reason": rec.get("reason"),
                                "strategy_score": rec.get("strategy_score"),
                                "source": "bot",
                            }
                        else:
                            combined[deal_id]["reason"] = rec.get("reason")
            except Exception:
                pass
            break

    # ── Construcción del índice de timestamps para deduplicar contra CSV ──
    # Lista de (epoch, upl) de todos los registros JSON ya cargados
    json_index = []
    for rec in combined.values():
        ep = _parse_ts_to_epoch(rec.get("timestamp"))
        if ep is not None:
            try:
                json_index.append((ep, float(rec.get("last_upl") or rec.get("upl") or 0)))
            except Exception:
                json_index.append((ep, None))

    # ── Fuente 3: funds_history*.csv ──
    csv_path = find_latest_funds_csv()
    if csv_path:
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Solo filas de tipo TRADE (excluir SWAP, DEMO_TRANSFER, etc.)
                    if row.get("Type", "").strip() != "TRADE":
                        continue
                    trade_id = row.get("Trade Id", "").strip()
                    if not trade_id:
                        continue
                    try:
                        csv_amount = float(row.get("Amount", "0").strip())
                        csv_ts_str = row.get("Modified", "").strip()
                        csv_ep = _parse_ts_to_epoch(csv_ts_str)
                    except Exception:
                        continue

                    # Deduplicar: ¿existe ya en JSON un registro con mismo timestamp (±5 min) y mismo monto?
                    is_dup = False
                    if csv_ep is not None:
                        for (j_ep, j_upl) in json_index:
                            if abs(csv_ep - j_ep) <= 300:  # ±5 minutos
                                if j_upl is None or abs(j_upl - csv_amount) < 0.02:
                                    is_dup = True
                                    break
                    if is_dup:
                        continue

                    csv_key = f"csv_{row.get('Id', '').strip()}"
                    if csv_key in combined:
                        continue  # duplicado dentro del propio CSV

                    combined[csv_key] = {
                        "dealId": csv_key,
                        "trade_id": trade_id,
                        "timestamp": csv_ts_str,
                        "direction": None,
                        "epic": row.get("Instrument Symbol", "").strip() or row.get("Instrument Name", "").strip(),
                        "entry_price": None,
                        "last_upl": csv_amount,
                        "last_upl_pct": None,
                        "max_profit_pct": None,
                        "hours_open": None,
                        "balance_after": float(row.get("Balance", "0").strip()),
                        "reason": "Capital.com Export",
                        "source": "csv",
                    }
                    # Agregar al índice para deduplicar siguientes filas del mismo CSV
                    if csv_ep is not None:
                        json_index.append((csv_ep, csv_amount))
        except Exception as e:
            print(f"[DEBUG] Error leyendo CSV de fondos: {e}")

    # Ordenar por timestamp y retornar los últimos N
    result = sorted(combined.values(), key=lambda x: x.get("timestamp") or "", reverse=False)
    return result[-n:]


def get_ethsession_account_info():
    """Obtiene información actualizada de la cuenta usando la instancia global de CapitalOP."""
    global CAPITAL_OPS
    if not ETHSESSION_AVAILABLE or CAPITAL_OPS is None:
        return None

    try:
        # Llamar a get_account_summary() para obtener datos frescos
        account_info = CAPITAL_OPS.get_account_summary()
        return account_info
    except Exception as e:
        print(f"[DEBUG] Error en get_account_summary: {e}")
        pass
    return None


def get_state():
    """Obtiene el estado actualizado del bot combinando datos locales y en tiempo real de CapitalOP."""
    global CAPITAL_OPS

    # Datos locales del bot
    capital = read_json("capital_state.json")
    positions_local = read_json("last_seen_positions.json")
    tick = read_json("momentum_tick.json")
    last_decision = read_last_process_line()
    history = read_last_n_process_lines(2500)
    closed_positions = read_last_closed_positions(200)

    # Leer entry_snapshots.json (indicadores + razón al momento de abrir)
    entry_snapshots = {}
    for base in [DEMOS_DIR, BASE_DIR]:
        snap_path = os.path.join(base, "entry_snapshots.json")
        if os.path.exists(snap_path):
            try:
                with open(snap_path, "r", encoding="utf-8") as _sf:
                    entry_snapshots = json.load(_sf)
            except Exception:
                pass
            break

    # Enriquecer posiciones ABIERTAS con datos de apertura (indicadores + razón)
    if isinstance(positions_local, dict) and entry_snapshots:
        for deal_id, pos_data in positions_local.items():
            snap = entry_snapshots.get(deal_id, {})
            if snap:
                pos_data["open_indicators"] = snap.get("indicators", {})
                pos_data["open_reason"] = snap.get("reason", "")
                pos_data["open_datetime"] = snap.get("open_datetime", "")
                if not pos_data.get("entry_price") and snap.get("open_price"):
                    pos_data["entry_price"] = snap.get("open_price")

    # Enriquecer posiciones CERRADAS con datos de apertura
    # Capital.com genera dealIds diferentes para apertura y cierre (ej: ...2272a vs ...2272b)
    # Hacemos fuzzy match: si los primeros 30 chars coinciden, es la misma operación
    if entry_snapshots:
        for rec in closed_positions:
            closed_deal = rec.get("dealId", "")
            # Intento 1: match exacto
            snap = entry_snapshots.get(closed_deal, {})
            # Intento 2: fuzzy match por prefijo (30 chars)
            if not snap and closed_deal and len(closed_deal) >= 30:
                prefix = closed_deal[:30]
                for snap_id, snap_data in entry_snapshots.items():
                    if snap_id[:30] == prefix:
                        snap = snap_data
                        break
            if snap:
                # Sobreescribir campos vacíos (setdefault no funciona si ya están como "" o {})
                if not rec.get("open_indicators"):
                    rec["open_indicators"] = snap.get("indicators", {})
                if not rec.get("open_reason"):
                    rec["open_reason"] = snap.get("reason", "")
                if not rec.get("open_datetime"):
                    rec["open_datetime"] = snap.get("open_datetime", "")
                if not rec.get("entry_price") and snap.get("open_price"):
                    rec["entry_price"] = snap.get("open_price")

    # Obtener información EN TIEMPO REAL de CapitalOP (como hace EthBoy)
    ethsession_account = None
    live_positions_api = {}
    if CAPITAL_OPS is not None:
        try:
            # Obtener información de la cuenta (balance, available, profitLoss, etc.)
            ethsession_account = CAPITAL_OPS.get_account_summary()
            print(f"[INFO] ✅ EthSession Account Summary obtenido: Balance=${ethsession_account.get('balance', 0)}")
        except Exception as e:
            print(f"[DEBUG] Error al obtener account summary de CAPITAL_OPS: {e}")
        try:
            # Obtener TODAS las posiciones abiertas desde Capital.com API
            # get_open_positions() retorna dict {"BUY": [...], "SELL": [...]}
            # cada item es {"position": {...}, "market": {...}}
            raw_positions = CAPITAL_OPS.get_open_positions()
            if isinstance(raw_positions, dict):
                all_items = []
                for direction, items in raw_positions.items():
                    if isinstance(items, list):
                        all_items.extend(items)
                for item in all_items:
                    if isinstance(item, dict):
                        pos = item.get("position", item)
                        mkt = item.get("market", {})
                        deal_id = pos.get("dealId", "")
                        if deal_id:
                            live_positions_api[deal_id] = {
                                "direction": pos.get("direction"),
                                "entry_price": pos.get("level"),
                                "size": pos.get("size"),
                                "last_upl": pos.get("upl"),
                                "leverage": pos.get("leverage"),
                                "timestamp": pos.get("createdDateUTC", ""),
                                "hours_open": _hours_open_from_created(pos.get("createdDateUTC", "")),
                                "epic": mkt.get("epic", ""),
                            }
            elif isinstance(raw_positions, list):
                for item in raw_positions:
                    if isinstance(item, dict):
                        pos = item.get("position", item)
                        mkt = item.get("market", {})
                        deal_id = pos.get("dealId", "")
                        if deal_id:
                            live_positions_api[deal_id] = {
                                "direction": pos.get("direction"),
                                "entry_price": pos.get("level"),
                                "size": pos.get("size"),
                                "last_upl": pos.get("upl"),
                                "leverage": pos.get("leverage"),
                                "timestamp": pos.get("createdDateUTC", ""),
                                "hours_open": _hours_open_from_created(pos.get("createdDateUTC", "")),
                                "epic": mkt.get("epic", ""),
                            }
            print(f"[INFO] ✅ Posiciones live API: {len(live_positions_api)}")
        except Exception as e:
            print(f"[DEBUG] Error al obtener posiciones live: {e}")

    # 🔹 COMBINAR: API live como base, enriquecer con datos locales (snapshots)
    # API live tiene TODAS las posiciones reales de Capital.com
    # Datos locales (last_seen_positions.json) pueden tener info extra como open_reason
    if live_positions_api:
        positions_to_return = {}
        for deal_id, api_data in live_positions_api.items():
            merged = dict(api_data)
            # Enriquecer con datos locales si existen
            local = positions_local.get(deal_id, {}) if isinstance(positions_local, dict) else {}
            for key in ("open_indicators", "open_reason", "open_datetime"):
                if local.get(key):
                    merged[key] = local[key]
            # También buscar en entry_snapshots
            snap = entry_snapshots.get(deal_id, {})
            if snap:
                if not merged.get("open_indicators"):
                    merged["open_indicators"] = snap.get("indicators", {})
                if not merged.get("open_reason"):
                    merged["open_reason"] = snap.get("reason", "")
                if not merged.get("open_datetime"):
                    merged["open_datetime"] = snap.get("open_datetime", "")
            positions_to_return[deal_id] = merged
    else:
        # Fallback a datos locales si la API no está disponible
        positions_to_return = positions_local if positions_local else {}
    print(f"[DEBUG] Posiciones a mostrar: {len(positions_to_return)}")

    # Guardar snapshot de balance si está disponible desde CapitalOP
    balance = None
    if ethsession_account:
        balance = ethsession_account.get("balance")
    elif capital and isinstance(capital, dict):
        balance = capital.get("balance_total") or capital.get("balance") or capital.get("available")
    if balance:
        save_balance_snapshot(float(balance))

    return {
        "capital": capital,
        "ethsession": ethsession_account,
        "positions": positions_to_return,
        "positions_live": positions_to_return,
        "tick": tick,
        "last_decision": last_decision,
        "history": history,
        "closed_positions": closed_positions,
        "debt_rate_per_hour": DEBT_RATE_PER_HOUR,
        "server_time": datetime.now().isoformat(),
    }


def save_balance_snapshot(balance: float):
    """Guarda un snapshot del balance actual en balance_history.json (máx 1 por minuto)."""
    path = os.path.join(BASE_DIR, "balance_history.json")
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        try:
            with open(path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

        # Solo guardar si han pasado al menos 60 segundos desde el último snapshot
        if history:
            last_ts = history[-1].get("timestamp", "")
            try:
                last_dt = datetime.fromisoformat(last_ts)
                now_dt = datetime.now(timezone.utc)
                if hasattr(last_dt, "tzinfo") and last_dt.tzinfo is None:
                    from datetime import timezone as tz
                    last_dt = last_dt.replace(tzinfo=tz.utc)
                elapsed = (now_dt - last_dt).total_seconds()
                if elapsed < 60:
                    return
            except Exception:
                pass

        history.append({"timestamp": now_iso, "balance": balance})
        # Mantener los últimos 10,000 puntos (~1 semana a 1/min)
        history = history[-10000:]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f)
    except Exception:
        pass


def find_latest_funds_csv():
    """Devuelve la ruta del funds_history CSV más reciente (statems/ o BASE_DIR)."""
    for _d in [os.path.join(BASE_DIR, "..", "statems"), DEMOS_DIR, BASE_DIR]:
        _p = os.path.join(_d, "funds_history*.csv")
        _f = sorted(glob.glob(_p))
        if _f:
            return _f[-1]
    return None


def parse_funds_csv():
    """
    Parsea el CSV exportado desde Capital.com (funds_history*.csv).
    Columnas: Id, Balance, Amount, Currency, Type, Status, Modified,
              Trade Id, Instrument Symbol, Instrument Name, Commission, Account type

    Retorna:
        balance_curve : [{"timestamp": ..., "balance": float}, ...]  ascendente
        pnl_curve     : [{"timestamp", "cumulative_pnl", "trade_pnl", "pct"}, ...]
        stats         : dict
    El CSV viene ordenado descendente (más nuevo primero); lo invertimos.
    """
    csv_path = find_latest_funds_csv()
    if not csv_path:
        return None

    rows = []
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception:
        return None

    # El CSV viene de más nuevo a más viejo → invertir para orden ascendente
    rows.reverse()

    balance_curve = []
    wins = 0
    best_pct = 0.0
    worst_pct = 0.0
    trade_count = 0

    for row in rows:
        try:
            ts_raw = row.get("Modified (UTC)", "").strip()
            balance = float(row.get("Balance", 0))
            amount = float(row.get("Amount", 0))
            rtype = row.get("Type", "").strip().upper()
            status = row.get("Status", "").strip().upper()

            if status != "PROCESSED":
                continue

            # Normalizar timestamp
            try:
                ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S").isoformat()
            except Exception:
                ts = ts_raw

            balance_curve.append({"timestamp": ts, "balance": balance})

            # Trade stats (win rate, best/worst)
            if rtype == "TRADE" and amount != 0:
                trade_count += 1
                pct = (amount / (balance - amount)) * 100 if (balance - amount) != 0 else 0
                if amount > 0:
                    wins += 1
                if pct > best_pct:
                    best_pct = pct
                if pct < worst_pct:
                    worst_pct = pct
        except Exception:
            continue

    initial_balance = balance_curve[0]["balance"] if balance_curve else 0
    final_balance = balance_curve[-1]["balance"] if balance_curve else 0
    total_pnl_real = final_balance - initial_balance

    # P&L curve: derivada del balance curve
    pnl_curve = []
    prev_bal = initial_balance
    for pt in balance_curve:
        bal = pt["balance"]
        cum_pnl = bal - initial_balance
        trade_pnl = round(bal - prev_bal, 4)
        pct = round((bal - prev_bal) / prev_bal * 100, 2) if prev_bal else 0.0
        prev_bal = bal
        pnl_curve.append({
            "timestamp": pt["timestamp"],
            "cumulative_pnl": round(cum_pnl, 4),
            "trade_pnl": trade_pnl,
            "pct": pct,
            "direction": "WIN" if trade_pnl >= 0 else "LOSS",
        })

    total_trades = trade_count
    win_rate = round(wins / total_trades * 100, 1) if total_trades > 0 else 0.0

    # Max drawdown sobre balance curve
    max_drawdown = 0.0
    peak_bal = 0.0
    for pt in balance_curve:
        b = pt["balance"]
        if b > peak_bal:
            peak_bal = b
        dd = peak_bal - b
        if dd > max_drawdown:
            max_drawdown = dd

    total_pnl_pct = round((total_pnl_real / initial_balance * 100), 1) if initial_balance else 0.0

    return {
        "balance_curve": balance_curve,
        "pnl_curve": pnl_curve,
        "stats": {
            "total_pnl_usd": round(total_pnl_real, 2),
            "total_pnl_pct": total_pnl_pct,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "best_trade_pct": round(best_pct, 2),
            "worst_trade_pct": round(worst_pct, 2),
            "max_drawdown_usd": round(max_drawdown, 2),
            "initial_balance": round(initial_balance, 2),
            "final_balance": round(final_balance, 2),
            "csv_file": os.path.basename(csv_path),
        }
    }


def build_capital_protection():
    """Construye el estado del sistema de protección de capital."""
    capital = read_json("capital_state.json")
    cooldown = read_json("eth_trade_cooldown.json")
    positions = read_json("last_seen_positions.json")
    mctx = read_json("market_context.json")

    # Datos de capital
    balance_total = 0
    balance_available = 0
    balance_deposit = 0
    balance_pnl = 0
    capital_pct = 0
    max_positions = 2

    if capital and isinstance(capital, dict):
        balance_total = capital.get("balance_total", 0)
        balance_available = capital.get("balance_available", 0)
        balance_deposit = capital.get("balance_deposit", 0)
        balance_pnl = capital.get("balance_pnl", 0)
        capital_pct = capital.get("capital_pct", 0)
        max_positions = capital.get("max_positions", 2)

    # Capital protection active?
    capital_shield = capital_pct < 70.0 if capital_pct else False

    # Cooldown
    cooldown_active = False
    cooldown_remaining = 0
    cooldown_last_direction = None
    if cooldown and isinstance(cooldown, dict):
        last_trade_time = cooldown.get("last_trade_time", 0)
        cooldown_last_direction = cooldown.get("last_direction")
        if last_trade_time:
            import time as _time
            elapsed = _time.time() - last_trade_time
            cooldown_minutes = 1  # Matches EthBoy cooldown_minutes
            if elapsed < cooldown_minutes * 60:
                cooldown_active = True
                cooldown_remaining = round(cooldown_minutes * 60 - elapsed)

    # Posiciones — separar legacy (≥24h) vs activas
    LEGACY_HOURS = 24
    pos_list = list(positions.values()) if isinstance(positions, dict) else []
    active_list = [p for p in pos_list if p.get("hours_open", 0) < LEGACY_HOURS]
    legacy_list = [p for p in pos_list if p.get("hours_open", 0) >= LEGACY_HOURS]

    # Conteos activos (sin legacy) — estos son los que cuentan para límites
    num_buy_active = sum(1 for p in active_list if p.get("direction") == "BUY")
    num_sell_active = sum(1 for p in active_list if p.get("direction") == "SELL")
    total_active = num_buy_active + num_sell_active

    # Conteos legacy
    num_buy_legacy = sum(1 for p in legacy_list if p.get("direction") == "BUY")
    num_sell_legacy = sum(1 for p in legacy_list if p.get("direction") == "SELL")
    total_legacy = num_buy_legacy + num_sell_legacy

    # Conteos totales (raw)
    num_buy_total = num_buy_active + num_buy_legacy
    num_sell_total = num_sell_active + num_sell_legacy
    total_pos = total_active + total_legacy

    # Límites se evalúan solo sobre activas
    pos_limit_hit = total_active >= max_positions
    buy_limit_hit = num_buy_active >= 1  # max_buy_positions = 1
    sell_limit_hit = num_sell_active >= 1  # max_sell_positions = 1

    # Market context blockers
    mctx_state = mctx.get("state", "unknown") if mctx else "unknown"
    mctx_bias = mctx.get("bias") if mctx else None
    breakout_block_buy = mctx_state == "breakout_down"
    breakout_block_sell = mctx_state == "breakout_up"

    # Overall risk level
    risk_flags = []
    if capital_shield:
        risk_flags.append("CAPITAL < 70%")
    if pos_limit_hit:
        risk_flags.append(f"POS LIMIT {total_active}/{max_positions}")
    if breakout_block_buy or breakout_block_sell:
        risk_flags.append(f"BREAKOUT BLOCK")
    if mctx_bias == "CHOPPY":
        risk_flags.append("CHOPPY MARKET")

    risk_level = "HIGH" if capital_shield else ("MEDIUM" if risk_flags else "LOW")

    return {
        "balance_total": balance_total,
        "balance_available": balance_available,
        "balance_deposit": balance_deposit,
        "balance_pnl": balance_pnl,
        "capital_pct": round(capital_pct, 1),
        "capital_shield": capital_shield,
        "capital_threshold": 70.0,
        "cooldown_active": cooldown_active,
        "cooldown_remaining_s": cooldown_remaining,
        "cooldown_last_direction": cooldown_last_direction,
        "num_buy_active": num_buy_active,
        "num_sell_active": num_sell_active,
        "total_active": total_active,
        "num_buy_legacy": num_buy_legacy,
        "num_sell_legacy": num_sell_legacy,
        "total_legacy": total_legacy,
        "num_buy_total": num_buy_total,
        "num_sell_total": num_sell_total,
        "total_positions": total_pos,
        "max_positions": max_positions,
        "pos_limit_hit": pos_limit_hit,
        "buy_limit_hit": buy_limit_hit,
        "sell_limit_hit": sell_limit_hit,
        "mctx_state": mctx_state,
        "mctx_bias": mctx_bias,
        "breakout_block_buy": breakout_block_buy,
        "breakout_block_sell": breakout_block_sell,
        "risk_level": risk_level,
        "risk_flags": risk_flags,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _merge_balance_curves(csv_curve, live_curve):
    """Fusiona CSV (histórico) + balance_history (live) sin duplicar."""
    if not csv_curve:
        return live_curve or []
    if not live_curve:
        return csv_curve
    csv_last_ts = csv_curve[-1].get("timestamp", "")
    for i, pt in enumerate(live_curve):
        if pt.get("timestamp", "") > csv_last_ts:
            return csv_curve + live_curve[i:]
    return csv_curve


def build_growth_data():
    """
    Construye la curva de crecimiento REAL de la cuenta.
    Fuente primaria: funds_history*.csv (histórico completo de Capital.com)
    Fusionado con: balance_history.json (snapshots live del bot)
    Métricas de trades: CSV (conteo total) + web_closed_positions (detalle)
    """
    # ── CSV: curva histórica + stats base ───────────────────────
    csv_data = parse_funds_csv()
    if csv_data and isinstance(csv_data, dict):
        csv_curve = csv_data.get("balance_curve", [])
        csv_stats = csv_data.get("stats", {})
        csv_initial = csv_stats.get("initial_balance", 0)
        csv_final = csv_stats.get("final_balance", 0)
        csv_trade_n = csv_stats.get("total_trades", 0)
        csv_best = csv_stats.get("best_trade_pct", 0)
        csv_worst = csv_stats.get("worst_trade_pct", 0)
        csv_winrate = csv_stats.get("win_rate", 0)
        csv_file = csv_stats.get("csv_file", None)
    else:
        csv_curve = []
        csv_initial = csv_final = csv_trade_n = csv_best = csv_worst = csv_winrate = 0
        csv_file = None

    # ── Live balance curve ──────────────────────────────────────
    live_curve = []
    for _p in [DEMOS_DIR, BASE_DIR]:
        _bh = os.path.join(_p, "balance_history.json")
        if os.path.exists(_bh):
            try:
                with open(_bh, "r", encoding="utf-8") as f:
                    live_curve = json.load(f)
                break
            except Exception:
                pass

    # ── Fusionar curvas ─────────────────────────────────────────
    balance_curve = _merge_balance_curves(csv_curve, live_curve)
    if not balance_curve:
        return {
            "balance_curve": [], "pnl_curve": [],
            "stats": {"total_pnl_usd": 0, "total_pnl_pct": 0,
                       "total_trades": 0, "win_rate": 0,
                       "best_trade_pct": 0, "worst_trade_pct": 0,
                       "max_drawdown_usd": 0, "initial_balance": 0,
                       "final_balance": 0, "csv_file": None},
        }

    initial_balance = float(balance_curve[0]["balance"])
    final_balance = float(balance_curve[-1]["balance"])
    total_pnl_real = final_balance - initial_balance
    total_pnl_pct = round((total_pnl_real / initial_balance * 100), 1) if initial_balance else 0.0

    # ── P&L curve: derivada del balance curve ───────────────────
    pnl_curve = []
    prev_bal = initial_balance
    for pt in balance_curve:
        bal = float(pt["balance"])
        cum_pnl = bal - initial_balance
        trade_pnl = round(bal - prev_bal, 4)
        pct = round((bal - prev_bal) / prev_bal * 100, 2) if prev_bal else 0.0
        prev_bal = bal
        pnl_curve.append({
            "timestamp": pt["timestamp"],
            "cumulative_pnl": round(cum_pnl, 4),
            "trade_pnl": trade_pnl,
            "pct": pct,
            "direction": "WIN" if trade_pnl >= 0 else "LOSS",
        })

    # ── Max drawdown ────────────────────────────────────────────
    max_drawdown = 0.0
    peak_bal = 0.0
    for pt in balance_curve:
        b = float(pt["balance"])
        if b > peak_bal:
            peak_bal = b
        dd = peak_bal - b
        if dd > max_drawdown:
            max_drawdown = dd

    # ── Stats: CSV es fuente base; web_closed_positions complementa extremos (best/worst) ───
    closed = read_last_closed_positions(500)
    best_pct = csv_best
    worst_pct = csv_worst
    for trade in closed:
        try:
            pnl_pct_raw = trade.get("last_upl_pct", 0)
            if isinstance(pnl_pct_raw, str):
                pnl_pct = float(pnl_pct_raw.replace("%", ""))
            else:
                pnl_pct = float(pnl_pct_raw or 0)
            if pnl_pct > best_pct:
                best_pct = pnl_pct
            if pnl_pct < worst_pct:
                worst_pct = pnl_pct
        except Exception:
            continue

    total_trades = csv_trade_n
    win_rate = csv_winrate

    return {
        "balance_curve": balance_curve,
        "pnl_curve": pnl_curve,
        "stats": {
            "total_pnl_usd": round(total_pnl_real, 2),
            "total_pnl_pct": total_pnl_pct,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "best_trade_pct": round(best_pct, 2),
            "worst_trade_pct": round(worst_pct, 2),
            "max_drawdown_usd": round(max_drawdown, 2),
            "initial_balance": round(initial_balance, 2),
            "final_balance": round(final_balance, 2),
            "csv_file": csv_file,
        }
    }


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silenciar logs del servidor

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_file(DASHBOARD_HTML, "text/html")
        elif self.path == "/api/state":
            data = get_state()
            self._json_response(data)
        elif self.path == "/api/growth":
            data = build_growth_data()
            self._json_response(data)
        elif self.path == "/api/market_context":
            data = read_json("market_context.json")
            self._json_response(data or {})
        elif self.path == "/api/capital_protection":
            data = build_capital_protection()
            self._json_response(data)
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, data):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path, mime):
        try:
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", f"{mime}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    print(f"[Dashboard] Inicializando...")

    # 🔹 Inicializar CapitalOP una sola vez (patrón como EthBoy)
    if ETHSESSION_AVAILABLE:
        initialize_capital_ops()
        if CAPITAL_OPS is not None:
            print(f"[Dashboard] CapitalOP conectado ✅")
        else:
            print(f"[Dashboard] ⚠️ No se pudo conectar CapitalOP (será fallback a datos locales)")
    else:
        print(f"[Dashboard] ⚠️ EthSession no disponible (fallback a datos locales del bot)")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"[Dashboard] Servidor en {url}")
    print(f"[Dashboard] Ctrl+C para detener")
    # Abrir navegador después de 0.5s
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Dashboard] Detenido.")
