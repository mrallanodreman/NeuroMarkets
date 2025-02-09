from EthSession import CapitalOP
import pickle
from datetime import datetime, timezone
import json

capital_ops = CapitalOP()

class Strategia:
    def __init__(self, capital_ops, threshold_buy=(1, 2), threshold_sell=(0, 2, 3), risk_factor=0.01,
                 margin_protection=0.9, profit_threshold=0.03, stop_loss=0.1,
                 retracement_threshold=0.01):
        """
        Estrategia de trading mejorada.
        """
        self.capital_ops = capital_ops
        self.threshold_buy = threshold_buy
        self.threshold_sell = threshold_sell
        self.risk_factor = risk_factor
        self.margin_protection = margin_protection
        self.profit_threshold = profit_threshold
        self.stop_loss = stop_loss
        self.retracement_threshold = retracement_threshold
        self.history = []
        self.balance = None
        self.price_history = []  # 🔹 Historial de precios para evaluar si el precio es barato
        self.position_tracker = {}
        # 📌 Intentar cargar `position_tracker.json` si existe
        try:
            with open("position_tracker.json", "r") as file:
                self.position_tracker = json.load(file)
            print("[INFO] `position_tracker.json` cargado correctamente.")
        except (FileNotFoundError, json.JSONDecodeError):
            print("[WARNING] `position_tracker.json` no encontrado o corrupto. Se inicia vacío.")
            self.position_tracker = {}

    def decide(self, state, current_price, balance, features, market_id, previous_state=None, open_positions=None):
        leverage = 20  # Apalancamiento
        margin_percentage = 1  # Usamos el 1% del balance disponible como margen
        max_deal_size = 0.009  # Tamaño máximo permitido por el mercado
        min_deal_size = 0.009  # Tamaño mínimo permitido

        print(f"[DEBUG] Decidiendo con state={state}, previous_state={previous_state}, precio={current_price}")

        if current_price <= 0 or balance <= 0:
            return {"action": "hold", "size": 0, "reason": "Precio o balance inválido"}

        # Obtener la cantidad de posiciones abiertas por dirección
        num_buy_positions = sum(1 for p in open_positions if p["direction"] == "BUY") if open_positions else 0
        num_sell_positions = sum(1 for p in open_positions if p["direction"] == "SELL") if open_positions else 0

        # Obtener los límites desde CapitalOP
        max_buy_positions = self.capital_ops.max_buy_positions  # Límite para BUY
        max_sell_positions = self.capital_ops.max_sell_positions  # Límite para SELL

        # 🔴 🚨 Si ya hay demasiados SELL, salir inmediatamente
        if num_sell_positions >= max_sell_positions:
            print(f"[INFO] 🚨 Límite de posiciones SELL alcanzado ({max_sell_positions}). Manteniendo posición.")
            return {"action": "hold", "size": 0, "reason": "Límite de posiciones SELL alcanzado"}

        # 🚀 Si aún hay espacio, procedemos con la lógica de trading
        rsi = features.get("RSI", 0)
        macd = features.get("MACD", 0)
        atr = features.get("ATR", 0)
        volume_change = features.get("VolumeChange", 0)

        def calculate_position_size(balance, leverage, current_price, risk_factor, min_deal_size, max_deal_size, margin_protection=0.9):
            margin_to_use = balance * risk_factor * margin_protection
            position_size = (margin_to_use * leverage) / current_price
            position_size = max(min(position_size, max_deal_size), min_deal_size)
            margin_required = (position_size * abs(current_price)) / leverage
            if margin_required > margin_to_use:
                position_size = (margin_to_use * leverage) / current_price
            return round(position_size, 4)

        # **Condición de Debilidad 1: RSI bajo y MACD negativo (Mercado bajista claro)**
        if rsi < 30 and macd < 0:
            size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
            margin_required = (size * abs(current_price)) / leverage
            if balance >= margin_required:
                print(f"[INFO] Oportunidad de debilidad detectada (RSI: {rsi}, MACD: {macd}). Abriendo posición corta: {size:.6f} unidades a precio {current_price}")
                return {
                    "action": "Short",  # Operación de venta (short)
                    "size": size,
                    "market_id": market_id,
                    "margin_required": margin_required,
                    "reason": "RSI bajo y MACD negativo, indicando debilidad"
                }
            else:
                return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}

        # **Condición de Debilidad 2: Volumen decreciente y ATR bajo (Falta de volatilidad)**
        if volume_change < 0 and atr < 0.02:
            size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
            margin_required = (size * abs(current_price)) / leverage
            if balance >= margin_required:
                print(f"[INFO] Oportunidad de debilidad por volumen decreciente y ATR bajo. Abriendo posición corta: {size:.6f} unidades a precio {current_price}")
                return {
                    "action": "Short",
                    "size": size,
                    "market_id": market_id,
                    "margin_required": margin_required,
                    "reason": "Volumen bajo y ATR bajo, señal de debilidad"
                }
            else:
                return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}

        if (rsi < 50 and macd < 10) or (volume_change > 0 and atr > 50):
            size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
            margin_required = (size * abs(current_price)) / leverage

            if balance >= margin_required:
                print(f"[INFO] Condición de venta activada: RSI={rsi}, MACD={macd}, VolumeChange={volume_change}, ATR={atr}. Abriendo posición SELL: {size:.6f} unidades a precio {current_price}")
                return {
                    "action": "Short",
                    "size": size,
                    "market_id": market_id,
                    "margin_required": margin_required,
                    "reason": "Señales de debilidad en RSI/MACD o alta volatilidad con volumen creciente"
                }
            else:
                return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}


        # **Condición de Debilidad 3: Retroceso desde un pico (Mercado debilitado después de un repunte)**
        if state == 3 and previous_state in [2, 1] and rsi < 45:
            size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
            margin_required = (size * abs(current_price)) / leverage
            if balance >= margin_required:
                print(f"[INFO] Retroceso detectado desde un pico (RSI: {rsi}), oportunidad de vender. Abriendo posición corta: {size:.6f} unidades a precio {current_price}")
                return {
                    "action": "Short",
                    "size": size,
                    "market_id": market_id,
                    "margin_required": margin_required,
                    "reason": "Retroceso desde un pico detectado, indicativo de debilidad"
                }
            else:
                return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}

        # Condición de debilidad más relajada para permitir la apertura de posiciones cortas en un rango más amplio de RSI
        if rsi < 50 and macd < 0:
            size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
            margin_required = (size * abs(current_price)) / leverage
            if balance >= margin_required:
                print(f"[INFO] Oportunidad de debilidad detectada (RSI: {rsi}, MACD: {macd}). Abriendo posición corta: {size:.6f} unidades a precio {current_price}")
                return {
                    "action": "Short",
                    "size": size,
                    "market_id": market_id,
                    "margin_required": margin_required,
                    "reason": "RSI bajo y MACD negativo, indicando debilidad"
                }
            else:
                return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}

        # **Condición de Debilidad 4: Movimiento bajista con señales de debilidad del mercado (Transición a estado 0 con RSI bajo)**
        if state == 0 and previous_state in [1, 2] and rsi < 45:
            size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
            margin_required = (size * abs(current_price)) / leverage
            if balance >= margin_required:
                print(f"[INFO] Señal de debilidad con transición a calma (RSI: {rsi}), abriendo posición corta: {size:.6f} unidades a precio {current_price}")
                return {
                    "action": "Short",
                    "size": size,
                    "market_id": market_id,
                    "margin_required": margin_required,
                    "reason": "Transición a calma con RSI bajo, indicando debilidad"
                }
            else:
                return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}

        # **Default: Mantener posición**
        return {"action": "hold", "size": 0, "reason": "No se cumplieron condiciones para abrir posición"}

    def evaluate_positions(self, positions, current_price, state, features, previous_state=None):
        """
        Evalúa posiciones abiertas para decidir si cerrarlas.
        Nunca cierra posiciones en negativo, incluye Emergency Exit.
        Retorna una lista de acciones a tomar.
        """
        to_close = []
        now_time = datetime.now(timezone.utc)

        # 📌 Asegurar que `self.position_tracker` está disponible
        if not hasattr(self, "position_tracker"):
            print("[WARNING] `position_tracker` no estaba definido en `Strategia`. Se inicializa vacío.")
            self.position_tracker = {}

        # 📌 Intentar cargar `position_tracker.json` si existe para no perder datos previos
        try:
            with open("position_tracker.json", "r") as file:
                self.position_tracker = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            print("[WARNING] No se encontró `position_tracker.json` o estaba corrupto. Se usará un nuevo tracker.")
            self.position_tracker = {}

        for position in positions:
            deal_id = position.get("dealId")
            direction = position.get("direction")
            entry_price = position.get("price")
            size = position.get("size")
            upl = position.get("upl", 0)

            hours_open = position.get("hours_open")
            if hours_open is None:
                print(f"[WARNING] No se encontró `hours_open` en la posición {deal_id}. Revisar `process_open_positions`.")
                continue

            position["hours_open"] = hours_open
            print(f"[INFO] Evaluando posición {deal_id} - Abierta hace {float(hours_open):.1f} horas - UPL: {float(upl):.5f}")

            current_profit = upl
            if current_profit <= 0:
                print(f"[DEBUG] Manteniendo posición debido a ganancia negativa. Profit: {current_profit * 100:.2f}%")
                continue

            if deal_id not in self.position_tracker:
                self.position_tracker[deal_id] = {"max_profit": 0}

            previous_max_profit = self.position_tracker[deal_id].get("max_profit", 0)
            updated_max_profit = max(previous_max_profit, current_profit)
            self.position_tracker[deal_id]["max_profit"] = updated_max_profit
            position["max_profit"] = updated_max_profit
            print(f"[INFO] Max Profit actualizado correctamente en el tracker: {updated_max_profit * 100:.2f}%")

            if 15 <= hours_open <= 24 and 0.5 <= upl <= 2.0:
                rsi = features.get("RSI", 0)
                macd = features.get("MACD", 0)
                volume_change = features.get("VolumeChange", 0)
                if state in [0, 1] and (rsi < 50 or macd < 0 or volume_change <= 0):
                    print(f"[INFO] Emergency Exit: Cierre por ganancia ({upl * 100:.2f}%) en posición {deal_id} (Abierta hace {hours_open:.1f} horas)")
                    to_close.append({
                        "action": "Close",
                        "dealId": deal_id,
                        "size": size,
                        "reason": "emergency_exit"
                    })

            if current_profit > 0 and previous_state == 0 and state == 3:
                print(f"[INFO] Cierre inmediato por transición 0 → 3 con ganancia: {current_profit * 100:.2f}%")
                to_close.append({
                    "action": "Close",
                    "dealId": deal_id,
                    "size": size,
                    "reason": "state_0_to_3"
                })
                continue

            retracement_allowed = updated_max_profit * self.retracement_threshold
            if updated_max_profit > 0 and (updated_max_profit - current_profit) > retracement_allowed:
                if current_profit <= 0.01:
                    print(f"[DEBUG] Manteniendo posición por ganancia negativa durante evaluación de retroceso. Profit: {current_profit * 100:.2f}%")
                    continue

                rsi = features.get("RSI", 0)
                macd = features.get("MACD", 0)
                volume_change = features.get("VolumeChange", 0)
                if rsi > 50 and macd > 0 and volume_change > 0:
                    print(f"[INFO] Sosteniendo posición: Indicadores positivos detectados.")
                    continue

                print(f"[INFO] Cierre por retroceso positivo detectado: {current_profit * 100:.2f}%")
                to_close.append({
                    "action": "Close",
                    "dealId": deal_id,
                    "size": size,
                    "reason": "retracement_positive"
                })

        try:
            with open("position_tracker.json", "w") as file:
                json.dump(self.position_tracker, file, indent=4)
            print("[INFO] `position_tracker.json` actualizado y guardado correctamente.")
        except Exception as e:
            print(f"[ERROR] No se pudo guardar `position_tracker.json`: {e}")

        return to_close

    def get_history(self):
        """
        Devuelve el historial de decisiones tomadas.
        """
        return self.history