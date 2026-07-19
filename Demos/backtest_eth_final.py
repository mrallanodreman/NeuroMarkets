#!/usr/bin/env python3
"""
📊 BACKTEST ETH FINAL - PRODUCCIÓN CONSISTENTE
===============================================
Arquitectura idéntica a EthBoy.py:
- EthStrategy.decide() para señales BUY/SELL
- Evaluador.evaluate_positions() para cierres (locked_floor system)
- Bidireccional: BUY abre LONG, SELL abre SHORT
- Leverage 20:1 | Comisiones 0.15% | Slippage 0.05%
- Estado de cuenta final con UPL (sin forced closes)
"""

import pandas as pd
import json
import os
from datetime import datetime
from EthStrategy import Strategia
from EthSession import CapitalOP
from Evaluador import evaluate_positions

# ============================================================================
# CONFIGURACIÓN DEL BACKTEST - SEMANA COMPLETA
# ============================================================================
DATA_FILE = "Reports/ethusd_ltf_7d.parquet"  # 🔄 CAMBIO: Datos de 7 días completos
CAPITAL_INICIAL = 1000.0
LEVERAGE = 20
COMISION = 0.0015  # 0.15%
SLIPPAGE = 0.0005  # 0.05%

# Features para EthStrategy (mismo que producción)
features = [
    "EMA_3", "EMA_9", "EMA_20", "EMA_50", "EMA_200",
    "RSI_7", "RSI_14",
    "MACD", "MACD_Signal", "MACD_Histogram",
    "ATR", "BB_Upper", "BB_Middle", "BB_Lower",
    "Stochastic_%K", "Stochastic_%D",
    "OBV", "OBV_Trend", "Volume_Ratio", "Market_Regime", "ADX"
]

# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================
def calculate_commission_and_slippage(price, size, direction):
    """Calcula comisión + slippage para una operación."""
    trade_value = price * size
    commission = trade_value * COMISION

    # Slippage: BUY paga más, SELL recibe menos
    slippage_cost = trade_value * SLIPPAGE

    return commission + slippage_cost


def execute_trade(balance, positions, signal, precio, size, idx, candle_time):
    """
    Ejecuta una operación y actualiza balance y posiciones.

    BUY: Abre posición LONG (profit si precio sube)
    SELL: Abre posición SHORT (profit si precio baja)
    """
    direction = signal["direction"]

    # Calcular costos
    costs = calculate_commission_and_slippage(precio, size, direction)

    # Calcular margen requerido (leverage 20x)
    margin_required = (precio * size) / LEVERAGE

    # Verificar que hay suficiente balance
    if balance < margin_required:
        print(f"[SKIP] Balance insuficiente: ${balance:.2f} < ${margin_required:.2f}")
        return balance, positions

    # Descontar costos del balance
    new_balance = balance - costs

    # Crear posición
    position = {
        "dealId": f"{direction}_{idx}_{int(candle_time.timestamp())}",
        "direction": direction,
        "size": size,
        "entry_price": precio,
        "entry_idx": idx,
        "entry_time": candle_time,
        "margin": margin_required,
        "costs": costs,
        "max_profit": 0,
        "position": {"direction": direction}  # Para compatibilidad con Evaluador
    }

    # Agregar a lista de posiciones según dirección
    if direction == "BUY":
        positions["BUY"].append(position)
    else:
        positions["SELL"].append(position)

    print(f"\n{'='*80}")
    print(f"🟢 {direction} EJECUTADO @ ${precio:.2f}")
    print(f"   Tamaño: {size:.6f} ETH")
    print(f"   Margen: ${margin_required:.2f} | Costos: ${costs:.4f}")
    print(f"   Balance: ${balance:.2f} → ${new_balance:.2f}")
    print(f"   Posiciones abiertas: BUY={len(positions['BUY'])}, SELL={len(positions['SELL'])}")
    print(f"{'='*80}\n")

    return new_balance, positions


def update_unrealized_pnl(positions, precio_actual):
    """
    Actualiza el UPL de todas las posiciones abiertas.

    LONG (BUY): UPL = (precio_actual - entry_price) * size
    SHORT (SELL): UPL = (entry_price - precio_actual) * size
    """
    total_upl = 0

    for pos_list in [positions["BUY"], positions["SELL"]]:
        for pos in pos_list:
            direction = pos["direction"]
            entry_price = pos["entry_price"]
            size = pos["size"]

            if direction == "BUY":
                # LONG: gana si precio sube
                upl_dollars = (precio_actual - entry_price) * size
            else:
                # SHORT: gana si precio baja
                upl_dollars = (entry_price - precio_actual) * size

            upl_pct = upl_dollars / (entry_price * size)
            pos["upl"] = upl_pct
            pos["upl_dollars"] = upl_dollars
            total_upl += upl_dollars

            # Actualizar max_profit para Evaluador
            if upl_pct > pos["max_profit"]:
                pos["max_profit"] = upl_pct

    return total_upl


def close_position(balance, positions, pos, precio_actual, reason):
    """Cierra una posición y actualiza el balance."""
    direction = pos["direction"]
    entry_price = pos["entry_price"]
    size = pos["size"]
    margin = pos["margin"]
    entry_costs = pos["costs"]

    # Calcular PnL
    if direction == "BUY":
        pnl_dollars = (precio_actual - entry_price) * size
    else:
        pnl_dollars = (entry_price - precio_actual) * size

    # Costos de salida
    exit_costs = calculate_commission_and_slippage(precio_actual, size, direction)

    # PnL neto
    net_pnl = pnl_dollars - exit_costs

    # Recuperar margen + PnL
    new_balance = balance + margin + net_pnl

    # Calcular horas abierta
    from datetime import timezone
    hours_open = (datetime.now(timezone.utc) - pos["entry_time"]).total_seconds() / 3600

    print(f"\n{'─'*80}")
    print(f"🔴 CERRANDO {direction} @ ${precio_actual:.2f}")
    print(f"   Entrada: ${entry_price:.2f} | Tamaño: {size:.6f} ETH")
    print(f"   PnL: ${net_pnl:.4f} ({pos['upl']*100:.2f}%)")
    print(f"   Costos totales: ${entry_costs + exit_costs:.4f}")
    print(f"   Razón: {reason}")
    print(f"   Balance: ${balance:.2f} → ${new_balance:.2f}")
    print(f"{'─'*80}\n")

    # Remover de posiciones abiertas
    positions[direction].remove(pos)

    # Registrar trade cerrado
    return new_balance, {
        "dealId": pos["dealId"],
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": precio_actual,
        "size": size,
        "pnl_dollars": net_pnl,
        "pnl_pct": pos["upl"],
        "hours_open": hours_open,
        "entry_time": pos["entry_time"],
        "exit_time": datetime.now(timezone.utc),
        "reason": reason
    }


# ============================================================================
# MAIN BACKTEST
# ============================================================================
def run_backtest():
    print("\n" + "="*80)
    print(" 📊 BACKTEST ETH FINAL - PRODUCCIÓN CONSISTENTE")
    print("="*80)

    # Cargar datos (formato parquet para 7 días completos)
    print(f"\n📂 Cargando datos desde {DATA_FILE}...")

    if DATA_FILE.endswith('.parquet'):
        # 🔄 NUEVO: Cargar datos parquet de 7 días
        df = pd.read_parquet(DATA_FILE)

        # El índice es timestamp, resetear para tener columna Datetime
        df.reset_index(inplace=True)
        df.rename(columns={'index': 'Datetime'}, inplace=True)

        # Asegurar que Datetime es timezone-aware
        if df['Datetime'].dt.tz is None:
            df['Datetime'] = df['Datetime'].dt.tz_localize('UTC')

        df = df.sort_values("Datetime").reset_index(drop=True)

        # Para compatibilidad, usar el mismo DF para historical y data
        historical_df = df.copy()

        print(f"✅ Formato parquet detectado: {len(df)} candles")
        print(f"   Período: {df['Datetime'].min()} → {df['Datetime'].max()}")
        duration = (df['Datetime'].max() - df['Datetime'].min()).total_seconds() / 86400
        print(f"   Duración: {duration:.2f} días")

    else:
        # 🔄 LEGACY: Formato JSON original
        with open(DATA_FILE, "r") as f:
            json_data = json.load(f)

        # Verificar estructura
        if isinstance(json_data, dict) and "data" in json_data:
            # Formato DataEth.py
            df = pd.DataFrame(json_data["data"])
            historical_df = pd.DataFrame(json_data.get("historical_data", []))
            print(f"✅ Formato DataEth.py detectado")
            print(f"   HTF (historical): {len(historical_df)} candles")
            print(f"   LTF (data): {len(df)} candles")
        else:
            # Formato legacy (lista plana)
            df = pd.DataFrame(json_data)
            historical_df = df  # Usar el mismo
            print(f"✅ Formato legacy detectado: {len(df)} candles")

        # Procesar timestamps para JSON
        if 'snapshotTime' in df.columns:
            df["snapshotTime"] = pd.to_datetime(df["snapshotTime"])
            df = df.sort_values("snapshotTime").reset_index(drop=True)
            periodo = f"{df['snapshotTime'].min()} → {df['snapshotTime'].max()}"
            # Crear columna Datetime uniforme
            df["Datetime"] = df["snapshotTime"]
        elif 'Datetime' in df.columns:
            # Convertir milisegundos a datetime
            df["Datetime"] = pd.to_datetime(df["Datetime"], unit='ms', utc=True)
            df = df.sort_values("Datetime").reset_index(drop=True)
            periodo = f"{df['Datetime'].min()} → {df['Datetime'].max()}"
        else:
            periodo = "N/A"

        print(f"   Período: {periodo}")

    # Inicializar Strategy
    capital_ops = CapitalOP()
    strategy = Strategia(
        capital_ops=capital_ops,
        threshold_buy=(1, 2),
        threshold_sell=(0, 2, 3),
        risk_factor=0.01,
        margin_protection=0.9,
        profit_threshold=0.03,
        stop_loss=0.1,
        retracement_threshold=0.01
    )

    # Estado del backtest
    balance = CAPITAL_INICIAL
    positions = {"BUY": [], "SELL": []}
    closed_trades = []

    # Límites de posiciones (igual que EthBoy.py)
    MAX_BUY_POSITIONS = 1
    MAX_SELL_POSITIONS = 1
    MAX_TOTAL_POSITIONS = 2

    print(f"\n💰 Capital inicial: ${balance:.2f}")
    print(f"🎯 Leverage: {LEVERAGE}x | Comisión: {COMISION*100:.2f}% | Slippage: {SLIPPAGE*100:.2f}%")
    print(f"📊 Límites: BUY={MAX_BUY_POSITIONS}, SELL={MAX_SELL_POSITIONS}, TOTAL={MAX_TOTAL_POSITIONS}")
    print("\n" + "="*80)
    print(" INICIANDO BACKTEST")
    print("="*80 + "\n")

    # Iterar por cada candle
    for idx in range(100, len(df)):  # Empezar en 100 para tener historial
        row = df.iloc[idx]

        # Detectar nombre de columna de precio
        if 'Close' in df.columns:
            precio_actual = row["Close"]
            time_col = "Datetime" if "Datetime" in df.columns else "snapshotTime"
        elif 'closePrice' in df.columns:
            precio_actual = row["closePrice"]
            time_col = "snapshotTime"
        else:
            raise ValueError("No se encontró columna de precio (Close o closePrice)")

        candle_time = row[time_col]
        if not isinstance(candle_time, pd.Timestamp):
            candle_time = pd.to_datetime(candle_time)

        # Actualizar UPL de posiciones abiertas
        update_unrealized_pnl(positions, precio_actual)

        # Evaluar cierres con Evaluador (locked_floor system)
        all_positions = positions["BUY"] + positions["SELL"]

        if all_positions:
            # Agregar hours_open a cada posición
            for pos in all_positions:
                pos["hours_open"] = (candle_time - pos["entry_time"]).total_seconds() / 3600

            # Preparar features dict con valores actuales
            features_dict = {
                "RSI": row.get("RSI_7", row.get("RSI", 50)),
                "MACD": row.get("MACD_Histogram", row.get("MACD", 0)),
                "ATR": row.get("ATR", 0),
                "VolumeChange": row.get("Volume_Ratio", 1.0)
            }

            # 🔹 USAR EVALUADOR REAL (con nueva lógica 0-10% y deterioro)
            profittracker = {}  # Diccionario para tracking (simplificado para backtest)

            # Convertir posiciones al formato esperado por Evaluador
            evaluador_positions = []
            for pos in all_positions:
                eval_pos = {
                    "position": {
                        "dealId": pos["dealId"],
                        "direction": pos["direction"],
                        "size": pos["size"],
                        "level": pos["entry_price"],
                        "upl": pos["upl_dollars"],
                        "createdDateUTC": pos.get("entry_time", datetime.utcnow().isoformat())
                    },
                    "market": {"epic": "ETHUSD"}
                }
                evaluador_positions.append(eval_pos)

            # Datos históricos hasta el punto actual (para análisis técnico)
            historical_data = df.iloc[max(0, idx-50):idx+1]  # Últimas 50 velas como contexto

            # Evaluar con Evaluador.evaluate_positions() (con nueva lógica)
            to_close = evaluate_positions(
                positions=evaluador_positions,
                features=features_dict,
                profittracker=profittracker,
                account_balance=balance,
                historical_data=historical_data
            )

            # Ejecutar cierres (evitar duplicaciones)
            closed_deal_ids = set()  # Rastrear IDs ya cerrados

            for close_order in to_close:
                deal_id = close_order["dealId"]

                # Evitar cerrar la misma posición dos veces
                if deal_id in closed_deal_ids:
                    continue

                reason = close_order.get("reason", "Evaluador")

                # Buscar posición en listas actuales (no en all_positions que puede estar desactualizada)
                pos_to_close = None
                for pos in positions["BUY"] + positions["SELL"]:
                    if pos["dealId"] == deal_id:
                        pos_to_close = pos
                        break

                if pos_to_close:
                    balance, closed_trade = close_position(
                        balance, positions, pos_to_close, precio_actual, reason
                    )
                    closed_trades.append(closed_trade)
                    closed_deal_ids.add(deal_id)  # Marcar como cerrado

        # ============================================================================
        # VERIFICACIÓN DE LÍMITES (igual que EthBoy.py)
        # ============================================================================
        num_buy_positions = len(positions["BUY"])
        num_sell_positions = len(positions["SELL"])
        total_positions = num_buy_positions + num_sell_positions

        # BLOQUE 1: Verificar límite TOTAL
        if total_positions >= MAX_TOTAL_POSITIONS:
            # SKIP evaluación completa
            continue

        # BLOQUE 2: Verificar límites por DIRECCIÓN
        buy_at_limit = num_buy_positions >= MAX_BUY_POSITIONS
        sell_at_limit = num_sell_positions >= MAX_SELL_POSITIONS

        if buy_at_limit and sell_at_limit:
            # Ambos límites alcanzados, SKIP
            continue

        # ============================================================================
        # DECIDIR NUEVA OPERACIÓN (con límites aplicados)
        # ============================================================================
        row = df.iloc[idx]

        # Convertir posiciones al formato esperado por decide()
        open_positions = (
            [{"position": {"direction": "BUY"}} for _ in positions["BUY"]],
            [{"position": {"direction": "SELL"}} for _ in positions["SELL"]]
        )

        # Pasar DataFrames completos (como en EthBoy.py)
        # historical_data = HTF, data = LTF
        decision = strategy.decide(
            current_price=precio_actual,
            data=df.iloc[:idx+1],  # DataFrame LTF hasta la candle actual
            balance=balance,
            features=features,
            market_id="ETHUSD",
            historical_data=historical_df if len(historical_df) > 0 else df.iloc[:idx+1],  # DataFrame HTF
            open_positions=open_positions
        )

        # Ejecutar decisión (respetando límites)
        if decision["action"] in ["BUY", "SELL"]:
            action = decision["action"]

            # Verificar límites por dirección
            if action == "BUY" and buy_at_limit:
                # print(f"[BLOCK] BUY bloqueado: límite alcanzado ({num_buy_positions}/{MAX_BUY_POSITIONS})")
                continue  # SKIP esta operación

            if action == "SELL" and sell_at_limit:
                # print(f"[BLOCK] SELL bloqueado: límite alcanzado ({num_sell_positions}/{MAX_SELL_POSITIONS})")
                continue  # SKIP esta operación

            size = decision["size"]
            if size > 0:
                balance, positions = execute_trade(
                    balance, positions, decision, precio_actual, size, idx, candle_time
                )

        # Progress cada 1000 candles
        if idx % 1000 == 0:
            total_pos = len(positions["BUY"]) + len(positions["SELL"])
            print(f"⏳ [{idx}/{len(df)}] | Balance: ${balance:.2f} | Posiciones: {total_pos} | Cerrados: {len(closed_trades)}")

    # ============================================================================
    # ESTADO DE CUENTA FINAL (SIN FORCED CLOSES)
    # ============================================================================
    print("\n" + "="*80)
    print(" 📋 ESTADO DE CUENTA FINAL")
    print("="*80)

    # Actualizar UPL final
    price_col = 'Close' if 'Close' in df.columns else 'closePrice'
    final_price = df.iloc[-1][price_col]
    total_upl = update_unrealized_pnl(positions, final_price)

    # Balance total = balance líquido + UPL de abiertas
    equity_total = balance + total_upl

    print(f"\n💰 Balance líquido: ${balance:.2f}")
    print(f"📊 UPL posiciones abiertas: ${total_upl:.4f}")
    print(f"💵 Equity total: ${equity_total:.2f}")
    print(f"📈 Retorno: {((equity_total - CAPITAL_INICIAL) / CAPITAL_INICIAL) * 100:.2f}%")

    print(f"\n📦 Posiciones abiertas (SIN CERRAR):")
    print(f"   BUY (LONG): {len(positions['BUY'])}")
    print(f"   SELL (SHORT): {len(positions['SELL'])}")

    if positions["BUY"] or positions["SELL"]:
        print("\n   Detalles:")
        for pos in positions["BUY"] + positions["SELL"]:
            print(f"   - {pos['direction']} ${pos['entry_price']:.2f} | "
                  f"Size: {pos['size']:.6f} ETH | "
                  f"UPL: {pos['upl']*100:.2f}% (${pos['upl_dollars']:.4f})")

    # ============================================================================
    # ANÁLISIS DE TRADES CERRADOS
    # ============================================================================
    if closed_trades:
        print("\n" + "="*80)
        print(" 📊 ANÁLISIS DE TRADES CERRADOS")
        print("="*80)

        df_trades = pd.DataFrame(closed_trades)

        # Métricas generales
        total_trades = len(df_trades)
        winners = df_trades[df_trades["pnl_dollars"] > 0]
        losers = df_trades[df_trades["pnl_dollars"] < 0]

        win_rate = (len(winners) / total_trades) * 100 if total_trades > 0 else 0

        avg_win = winners["pnl_dollars"].mean() if len(winners) > 0 else 0
        avg_loss = losers["pnl_dollars"].mean() if len(losers) > 0 else 0

        expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss) if total_trades > 0 else 0

        print(f"\n📈 Trades cerrados: {total_trades}")
        print(f"   ✅ Ganadores: {len(winners)} ({win_rate:.1f}%)")
        print(f"   ❌ Perdedores: {len(losers)} ({100-win_rate:.1f}%)")

        print(f"\n💵 PnL:")
        print(f"   Promedio ganador: ${avg_win:.4f}")
        print(f"   Promedio perdedor: ${avg_loss:.4f}")
        print(f"   Expectancy: ${expectancy:.4f}")

        # Desglose por dirección
        print(f"\n🔍 Por dirección:")
        for direction in ["BUY", "SELL"]:
            dir_trades = df_trades[df_trades["direction"] == direction]
            if len(dir_trades) > 0:
                dir_winners = dir_trades[dir_trades["pnl_dollars"] > 0]
                dir_wr = (len(dir_winners) / len(dir_trades)) * 100
                dir_pnl = dir_trades["pnl_dollars"].sum()

                print(f"   {direction}: {len(dir_trades)} trades | "
                      f"WR: {dir_wr:.1f}% | "
                      f"PnL: ${dir_pnl:.4f}")

        # Guardar CSV
        csv_file = "backtest_eth_trades.csv"
        df_trades.to_csv(csv_file, index=False)
        print(f"\n💾 Trades guardados en: {csv_file}")
    else:
        print("\n⚠️ No se ejecutaron trades.")

    print("\n" + "="*80)
    print(" ✅ BACKTEST COMPLETADO")
    print("="*80 + "\n")


if __name__ == "__main__":
    run_backtest()
