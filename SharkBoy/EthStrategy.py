from EthSession import CapitalOP 
import pickle
from datetime import datetime, timezone

capital_ops = CapitalOP()  

class Strategia:
    def __init__(self, capital_ops ,threshold_buy=(1,2), threshold_sell=(0, 2, 3), risk_factor=0.01, 
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

        if num_buy_positions >= max_buy_positions and num_sell_positions >= max_sell_positions:
            print(f"[INFO] Límite de posiciones alcanzado (BUY: {max_buy_positions}, SELL: {max_sell_positions}).")
            return {"action": "hold", "size": 0, "reason": "Límite de posiciones abiertas alcanzado"}


        # Indicadores
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
                    "action": "Short",  # Operación de venta (short)
                    "size": size,
                    "market_id": market_id,
                    "margin_required": margin_required,
                    "reason": "Volumen bajo y ATR bajo, señal de debilidad"
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
                    "action": "Short",  # Operación de venta (short)
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
                    "action": "Short",  # Operación de venta (short)
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
                    "action": "Short",  # Operación de venta (short)
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
        now_time = datetime.now(timezone.utc)  # Obtener la hora actual en UTC


        for position in positions:
            deal_id = position.get("dealId")
            direction = position.get("direction")
            entry_price = position.get("price")
            size = position.get("size")
            upl = position.get("upl", 0)  # Usar el UPL directamente
            created_date_utc = position.get("createdDateUTC", "")


            # Verificar que todos los datos esenciales estén presentes
            if not deal_id or not direction or not entry_price or not size or not created_date_utc:
                print(f"[WARNING] Posición incompleta. dealId: {deal_id}, direction: {direction}, price: {entry_price}, createdDateUTC: {created_date_utc}. Manteniendo posición.")
                continue

            # Convertir createdDateUTC a datetime en UTC
            try:
                created_time = datetime.strptime(created_date_utc, "%Y-%m-%dT%H:%M:%S.%f")
                created_time = created_time.replace(tzinfo=timezone.utc)  # Asegurar que es UTC

                # Calcular el tiempo abierto en horas
                hours_open = (now_time - created_time).total_seconds() / 3600

            except Exception as e:
                print(f"[ERROR] No se pudo calcular la antigüedad de la posición {deal_id}: {e}")
                continue

            # 📌 Incluir `hours_open` en la posición
            position["hours_open"] = hours_open  # Guardar en la posición para `print_log`

            print(f"[INFO] Evaluando posición {deal_id} - Abierta hace {float(hours_open):.1f} horas - UPL: {float(upl):.5f}")


            # Usar upl como current_profit
            current_profit = upl

            # Nunca cerrar posiciones con ganancia negativa
            if current_profit <= 0:
                print(f"[DEBUG] Manteniendo posición debido a ganancia negativa. Profit: {current_profit * 100:.2f}%")
                continue

            # Obtener el max_profit previo desde el tracker
            max_profit_prev = position.get("max_profit", 0)

            # Actualizar el máximo alcanzado solo si current_profit es positivo
            if current_profit > 0:
                updated_max_profit = max(max_profit_prev, current_profit)
                position["max_profit"] = updated_max_profit
                print(f"[INFO] Max Profit actualizado: {updated_max_profit * 100:.2f}%")
            else:
                print(f"[DEBUG] Current Profit es negativo o cero ({current_profit * 100:.2f}%). No se actualiza Max Profit.")


            # ✅ Emergency Exit: Solo para posiciones con 15 a 24 horas de antigüedad
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

            # Regla para transiciones 0 → 3
            if current_profit > 0:
                if previous_state == 0 and state == 3:
                    print(f"[INFO] Cierre inmediato por transición 0 → 3 con ganancia: {current_profit * 100:.2f}%")
                    to_close.append({
                        "action": "Close",
                        "dealId": deal_id,
                        "size": size,
                        "reason": "state_0_to_3"
                    })
                    continue

            # Regla para estados consecutivos 3 → 3
            if current_profit > 0:
                if previous_state == 3 and state == 3:
                    print(f"[INFO] Cierre inmediato por estado consecutivo 3 → 3 con ganancia: {current_profit * 100:.2f}%")
                    to_close.append({
                        "action": "Close",
                        "dealId": deal_id,
                        "size": size,
                        "reason": "state_3_consecutive"
                    })
                    continue

            # Retroceso basado en el máximo alcanzado
            retracement_allowed = updated_max_profit * self.retracement_threshold
            if updated_max_profit > 0 and (updated_max_profit - current_profit) > retracement_allowed:
                # Verificar que current_profit es positivo antes de proceder
                if current_profit <= 0.01:
                    print(f"[DEBUG] Manteniendo posición por ganancia negativa durante evaluación de retroceso. Profit: {current_profit * 100:.2f}%")
                    continue

                # Condiciones adicionales para evitar cierre si indicadores son positivos
                rsi = features.get("RSI", 0)
                macd = features.get("MACD", 0)
                volume_change = features.get("VolumeChange", 0)
                if rsi > 50 and macd > 0 and volume_change > 0:
                    print(f"[INFO] Sosteniendo posición: Indicadores positivos detectados.")
                    continue

                # Cierre si todas las condiciones están cumplidas
                print(f"[INFO] Cierre por retroceso positivo detectado: {current_profit * 100:.2f}%")
                to_close.append({
                    "action": "Close",
                    "dealId": deal_id,
                    "size": size,
                    "reason": "retracement_positive"
                })

            # Cierre por ganancia alcanzada
            if current_profit >= self.profit_threshold:
                print(f"[INFO] Cierre por ganancia alcanzada: {current_profit * 100:.2f}%")
                to_close.append({
                    "action": "Close",
                    "dealId": deal_id,
                    "size": size,
                    "reason": "profit_threshold"
                })

            if current_profit > 0:
                # Cierre por estados decrecientes (solo si current_profit > 0)
                if (previous_state, state) in [(3, 2), (2, 0), (3, 0)]:
                    print(f"[INFO] Cierre por cambio de estados con ganancia: {previous_state} → {state}")
                    to_close.append({
                        "action": "Close",
                        "dealId": deal_id,
                        "size": size,
                        "reason": "state_decrease_positive"
                    })

        return to_close



    def get_history(self):
        """
        Devuelve el historial de decisiones tomadas.
        """
        return self.history
