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
            reason = f"Límite de posiciones SELL alcanzado ({max_sell_positions}). Manteniendo posición."
            print(f"[INFO] 🚨 {reason}")

            # ✅ Registrar en el historial de decisiones
            self.history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "market_id": market_id,
                "action": "hold",
                "size": 0,
                "reason": reason
            })

            return {"action": "hold", "size": 0, "reason": reason}

        # 🚀 Si aún hay espacio, procedemos con la lógica de trading
        rsi = features.get("RSI", 0)
        macd = features.get("MACD", 0)
        atr = features.get("ATR", 0)
        volume_change = features.get("VolumeChange", 0)


        # 🔹 Evitar short si llevamos 5 velas consecutivas de caída
        consecutive_red_candles = sum(1 for i in range(1, 6) if self.price_history[-i]["Close"] < self.price_history[-i]["Open"])
        if consecutive_red_candles >= 5:
            return {"action": "hold", "size": 0, "reason": "Demasiadas velas rojas consecutivas, posible rebote"}

        # 🔹 Confirmar tendencia bajista con RSI en 14 y 50 periodos
        rsi_14 = features.get("RSI_14", 0)
        rsi_50 = features.get("RSI_50", 0)
        if rsi_14 >= 45 or rsi_50 >= 45:
            return {"action": "hold", "size": 0, "reason": "RSI no confirma tendencia bajista en múltiples periodos"}

        # 🔹 Obtener historial de ATR
        atr_history = [entry["ATR"] for entry in self.price_history[-100:] if "ATR" in entry and entry["ATR"] is not None]
        avg_atr = sum(atr_history) / len(atr_history) if atr_history else 50

        # 🔹 Evitar operar si el ATR es menor al 50% de su promedio
        if atr < avg_atr * 0.5:
            return {"action": "hold", "size": 0, "reason": "ATR extremadamente bajo, posible mercado lateral"}


        def calculate_position_size(balance, leverage, current_price, risk_factor, min_deal_size, max_deal_size, margin_protection=0.9):
            margin_to_use = balance * risk_factor * margin_protection
            position_size = (margin_to_use * leverage) / current_price
            position_size = max(min(position_size, max_deal_size), min_deal_size)
            margin_required = (position_size * abs(current_price)) / leverage
            if margin_required > margin_to_use:
                position_size = (margin_to_use * leverage) / current_price
            return round(position_size, 4)

        # **Condición de Debilidad Base : RSI bajo y MACD negativo (Mercado bajista claro)**
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

        # Asegurar que tenemos suficiente historial de ATR
        atr_history = [entry["ATR"] for entry in self.price_history[-100:] if "ATR" in entry and entry["ATR"] is not None]

        # Calcular la media del ATR en las últimas 100 velas (o usar un valor por defecto si hay pocos datos)
        avg_atr = sum(atr_history) / len(atr_history) if atr_history else 50  # Default a 50 si no hay suficientes datos

        # Condición de debilidad 1: Volumen decreciente y ATR bajo (Falta de volatilidad)
        if volume_change < 0 and atr < avg_atr * 0.7:  # Nuevo umbral basado en el 70% del ATR promedio
            size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
            margin_required = (size * abs(current_price)) / leverage
            if balance >= margin_required:
                print(f"[INFO] 📉 Oportunidad de debilidad por volumen decreciente y ATR bajo. Abriendo posición corta: {size:.6f} unidades a precio {current_price}")
                return {
                    "action": "Short",
                    "size": size,
                    "market_id": market_id,
                    "margin_required": margin_required,
                    "reason": f"Volumen bajo y ATR ({atr:.2f}) por debajo del 70% del promedio ({avg_atr:.2f})"
                }
            else:
                return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}
    #COndicion 2

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


    #Condicion 3 
       # Definir ventana de análisis para detectar picos
        lookback_window = 50  # Número de velas para detectar el pico reciente

        # Obtener el máximo reciente en las últimas `lookback_window` velas
        if len(self.price_history) >= lookback_window:
            recent_high = max(entry["Close"] for entry in self.price_history[-lookback_window:])
        else:
            recent_high = current_price  # Si no hay suficientes datos, tomamos el precio actual como referencia

        # Definir el porcentaje de caída desde el pico
        retracement_threshold = 0.03  # 3% de retroceso desde el máximo reciente

        # 📉 **Condición de Retroceso desde un Pico sin el Modelo**
        if (current_price <= recent_high * (1 - retracement_threshold)) and rsi < 45:
            size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
            margin_required = (size * abs(current_price)) / leverage
            
            if balance >= margin_required:
                print(f"[INFO] 🔻 Retroceso detectado desde un pico reciente ({recent_high:.2f}). "
                      f"Precio actual: {current_price:.2f} | RSI: {rsi:.2f}. Abriendo posición corta: {size:.6f} unidades")
                return {
                    "action": "Short",
                    "size": size,
                    "market_id": market_id,
                    "margin_required": margin_required,
                    "reason": f"Retroceso del {retracement_threshold*100:.1f}% desde el máximo reciente ({recent_high:.2f}), con RSI {rsi:.2f}"
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

            # Obtener valores actuales de medias móviles
            ema_12 = features.get("EMA_12", 0)
            ema_50 = features.get("EMA_50", 0)
            prev_ema_12 = self.price_history[-2]["EMA_12"] if len(self.price_history) > 1 else ema_12
            prev_ema_50 = self.price_history[-2]["EMA_50"] if len(self.price_history) > 1 else ema_50

            # Confirmar transición bajista: EMA_12 cruzando EMA_50 hacia abajo
            ema_crossover_down = prev_ema_12 > prev_ema_50 and ema_12 < ema_50

            # **Condición de Debilidad: Transición a Calma con RSI Bajo**
            if ema_crossover_down and rsi < 45 and volume_change < 0:
                size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
                margin_required = (size * abs(current_price)) / leverage
                
                if balance >= margin_required:
                    print(f"[INFO] 📉 Movimiento bajista detectado: EMA_12 cruzó debajo de EMA_50. "
                          f"RSI={rsi:.2f}, VolumeChange={volume_change:.2f}. Abriendo posición corta: {size:.6f} unidades")
                    return {
                        "action": "Short",
                        "size": size,
                        "market_id": market_id,
                        "margin_required": margin_required,
                        "reason": f"EMA_12 ({ema_12:.2f}) cruzó por debajo de EMA_50 ({ema_50:.2f}), RSI={rsi:.2f} y volumen decreciente"
                    }
                else:
                    return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}

        # **Default: Mantener posición**
        return {"action": "hold", "size": 0, "reason": "No se cumple ninguna condicion para abrir posición"}

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
            upl = position.get("upl", 0)

            if upl <= 0:
                reason = f"Manteniendo posición debido a ganancia negativa. Profit: {upl * 100:.2f}%"
                print(f"[DEBUG] {reason}")

                # ✅ Asegurar que todas las acciones contienen 'reason'
                to_close.append({
                    "action": "Hold",
                    "dealId": deal_id,  # Opcional: agregar el ID de la posición
                    "size": position.get("size", 0),
                    "reason": reason  # 🔹 Asegurar que 'reason' siempre está presente
                })
                continue

            hours_open = position.get("hours_open")
            if hours_open is None:
                print(f"[WARNING] No se encontró `hours_open` en la posición {deal_id}. Revisar `process_open_positions`.")
                continue

            position["hours_open"] = hours_open
            print(f"[INFO] Evaluando posición {deal_id} - Abierta hace {float(hours_open):.1f} horas - UPL: {float(upl):.5f}")

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
                    reason = f"Manteniendo posición debido a ganancia negativa. Profit: {current_profit * 100:.2f}%"
                    print(f"[DEBUG] {reason}")

                    # ✅ Agregar "Hold" al log para que aparezca en `process_open_positions()`
                    to_close.append({
                        "action": "Hold",
                        "reason": reason
                    })
                    continue  # ✅ No cerrar la posición, pero registrar la acción en el log


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