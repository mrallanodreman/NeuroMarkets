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

    def decide(self, current_price, balance, features, market_id, open_positions=None):
        leverage = 20  # Apalancamiento
        balance_base = 8.0  # Balance base de referencia
        tamaño_base = 0.009  # Tamaño de posición base con balance_base
        multiplicador = 2.1  # Factor para aumentar el tamaño proporcionalmente al balance
        margin_protection = 0.9  # Usar solo el 90% del balance disponible

        print(f"[DEBUG] Decidiendo para precio={current_price} y balance={balance}")

        if current_price <= 0 or balance <= 0:
            return {"action": "hold", "size": 0, "reason": "Precio o balance inválido"}

        # 📌 Obtener la cantidad de posiciones abiertas por dirección
        num_buy_positions = sum(1 for p in open_positions if p["direction"] == "BUY") if open_positions else 0
        num_sell_positions = sum(1 for p in open_positions if p["direction"] == "SELL") if open_positions else 0

        # 📌 Límites de posiciones desde CapitalOP
        max_buy_positions = self.capital_ops.max_buy_positions
        max_sell_positions = self.capital_ops.max_sell_positions

        if num_sell_positions >= max_sell_positions:
            reason = f"Límite de posiciones SELL alcanzado ({max_sell_positions}). Manteniendo posición."
            print(f"[INFO] 🚨 {reason}")
            return {"action": "hold", "size": 0, "reason": reason}

        # 📌 Indicadores técnicos y volumen
        rsi = features.get("RSI", 0)
        macd = features.get("MACD", 0)
        atr = features.get("ATR", 0)
        adx = features.get("ADX", 0)  # Fuerza de la tendencia
        volume_change = features.get("VolumeChange", 0)
        obv = features.get("OBV", 0)  # Confirmación de tendencia con volumen

        # 📌 Evaluación del volumen de la sesión actual frente al histórico
        recent_volume = sum(entry.get("Volume", 0) for entry in self.price_history[-10:]) / 10
        avg_volume = sum(entry.get("Volume", 0) for entry in self.price_history[-50:]) / 50 if len(self.price_history) >= 50 else recent_volume

        # 📌 Función para calcular el tamaño de posición
        def calculate_position_size(balance, leverage, current_price, risk_factor, min_size=0.009, max_size=0.009):
            margin_to_use = balance * risk_factor * margin_protection
            position_size = (margin_to_use * leverage) / current_price
            position_size = max(min(position_size, max_size), min_size)
            margin_required = (position_size * abs(current_price)) / leverage
            return round(position_size, 4), margin_required

        # 🚨 **Evitar operar en mercados laterales sin tendencia (ADX < 20)**
        if adx < 20:
            return {"action": "hold", "size": 0, "reason": "ADX bajo, mercado sin tendencia definida"}

        # 🚨 **Evitar operar en sesiones de bajo volumen**
        if recent_volume < avg_volume * 0.5:
            return {"action": "hold", "size": 0, "reason": "Volumen actual bajo, posible falta de movimiento"}

        # 🚨 **Evitar operar en condiciones de posible rebote**
        if volume_change > 0 and (rsi > 45 or obv > 0):
            return {"action": "hold", "size": 0, "reason": "Posible rebote detectado, evitando Short"}

        # 🚨 **Confirmación de debilidad para Short**
        if rsi >= 40 or macd > -1:
            return {"action": "hold", "size": 0, "reason": "Indicadores no confirman suficiente debilidad para Short"}

        # 📌 Evaluación del ATR para evitar mercados laterales
        atr_history = [entry["ATR"] for entry in self.price_history[-50:] if "ATR" in entry and entry["ATR"] is not None]
        avg_atr = sum(atr_history) / len(atr_history) if atr_history else 50
        if atr < avg_atr * 0.6:
            return {"action": "hold", "size": 0, "reason": "ATR bajo, posible mercado lateral"}

        # 🚨 **Evitar short si hay una posible divergencia alcista en RSI o MACD**
        if len(self.price_history) > 2:
            rsi_prev = self.price_history[-2].get("RSI", rsi)
            macd_prev = self.price_history[-2].get("MACD", macd)
            price_prev = self.price_history[-2].get("Close", current_price)
        else:
            rsi_prev, macd_prev, price_prev = rsi, macd, current_price

        if (rsi > rsi_prev and current_price < price_prev) or (macd > macd_prev and current_price < price_prev):
            return {"action": "hold", "size": 0, "reason": "Posible divergencia alcista detectada, evitando Short"}

        # 🚨 **Evitar short si estamos cerca de un soporte fuerte**
        support_level = min(entry["Low"] for entry in self.price_history[-30:])
        if current_price <= support_level * 1.03:
            return {"action": "hold", "size": 0, "reason": "Cerca de soporte fuerte, posible rebote"}

        # 🚨 **Evitar short si el volumen de compra es alto en una caída**
        buying_volume = features.get("BuyingVolume", 0)
        selling_volume = features.get("SellingVolume", 0)

        if buying_volume > selling_volume and rsi < 40:
            return {"action": "hold", "size": 0, "reason": "Aumento de volumen comprador en caída, posible rebote"}

        # 📌 **Condiciones óptimas para Short**
        position_size, margin_required = calculate_position_size(balance, leverage, current_price, 0.01)

        # 🔻 **Confirmación de condiciones bajistas con RSI, MACD y OBV**
        if rsi < 32 and macd < -1 and obv < 0 and balance >= margin_required:
            return {
                "action": "Short",
                "size": position_size,
                "market_id": market_id,
                "margin_required": margin_required,
                "reason": "RSI bajo, MACD negativo y OBV en tendencia bajista, indicando debilidad"
            }

        # 🔻 **Condiciones alternativas para Short: Volumen de venta y ATR alto**
        if volume_change < -0.5 and atr > avg_atr * 0.8 and balance >= margin_required:
            return {
                "action": "Short",
                "size": position_size,
                "market_id": market_id,
                "margin_required": margin_required,
                "reason": "Volumen en descenso y volatilidad en aumento"
            }

        # 🚨 **Si no se cumplen condiciones para Short, mantener posición**
        return {"action": "hold", "size": 0, "reason": "No se cumple ninguna condición para abrir posición"}

    def evaluate_positions(self, positions, current_price, features):
        """
        Evalúa posiciones abiertas para decidir si cerrarlas.
        Nunca cierra posiciones en negativo.
        Mantiene posiciones positivas mientras la tendencia las respalde.
        Si hay un retroceso considerable, se cierran para asegurar ganancia.
        """

        to_close = []
        now_time = datetime.now(timezone.utc)

        # 📌 Asegurar que `self.position_tracker` está disponible
        if not hasattr(self, "position_tracker"):
            print("[WARNING] `position_tracker` no estaba definido en `Strategy`. Se inicializa vacío.")
            self.position_tracker = {}

        # 📌 Intentar cargar `position_tracker.json` si existe para no perder datos previos
        try:
            with open("position_tracker.json", "r") as file:
                self.position_tracker = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            print("[WARNING] No se encontró `position_tracker.json` o estaba corrupto. Se usará un nuevo tracker.")
            self.position_tracker = {}

        # Parámetros para cierre y retrocesos
        minimum_profit_threshold = 0.03  # Mínimo de $0.03 antes de considerar cierre
        retracement_threshold = 0.3  # 30% del máximo profit alcanzado antes de cerrar

        for position in positions:
            deal_id = position.get("dealId")
            direction = position.get("direction")
            entry_price = position.get("price")
            size = position.get("size")
            upl = position.get("upl", 0)  # Ganancia no realizada

            hours_open = position.get("hours_open")
            if hours_open is None:
                print(f"[WARNING] No se encontró `hours_open` en la posición {deal_id}. Revisar `process_open_positions`.")
                continue

            position["hours_open"] = hours_open
            print(f"[INFO] Evaluando posición {deal_id} - Abierta hace {float(hours_open):.1f} horas - UPL: {float(upl):.5f}")

            # 🚨 **MANTENER posiciones en negativo**
            if upl < 0:
                print(f"[DEBUG] Manteniendo posición debido a ganancia negativa. Profit: {upl * 100:.2f}%")
                continue

            # 🚀 **PERSEGUIR tendencia en posiciones ganadoras**
            if deal_id not in self.position_tracker:
                self.position_tracker[deal_id] = {"max_profit": 0}

            previous_max_profit = self.position_tracker[deal_id].get("max_profit", 0)
            updated_max_profit = max(previous_max_profit, upl)
            self.position_tracker[deal_id]["max_profit"] = updated_max_profit
            position["max_profit"] = updated_max_profit
            print(f"[INFO] Max Profit actualizado correctamente en el tracker: {updated_max_profit * 100:.2f}%")

            # 🚨 **Aplicar mecanismo de retroceso**
            retracement_allowed = updated_max_profit * retracement_threshold
            if upl > minimum_profit_threshold and (updated_max_profit - upl) > retracement_allowed:
                rsi = features.get("RSI", 0)
                macd = features.get("MACD", 0)
                volume_change = features.get("VolumeChange", 0)

                # Si los indicadores aún son favorables, continuar manteniendo la posición
                if rsi > 50 and macd > 0 and volume_change > 0:
                    print(f"[INFO] Sosteniendo posición: Indicadores positivos detectados.")
                    continue

                # 🚨 Cierre de posición por retroceso de tendencia
                print(f"[INFO] Cierre por retroceso positivo detectado: {upl * 100:.2f}%")
                to_close.append({
                    "action": "Close",
                    "dealId": deal_id,
                    "size": size,
                    "reason": "retracement_positive"
                })

            # 🚨 **Cierre forzado si la posición ya tiene más de 24h con al menos 0.5% de ganancia**
            if hours_open >= 24 and upl >= 0.5:
                print(f"[INFO] Cierre por tiempo máximo alcanzado con ganancia positiva: {upl * 100:.2f}%")
                to_close.append({
                    "action": "Close",
                    "dealId": deal_id,
                    "size": size,
                    "reason": "time_expired"
                })

        # Guardar actualizaciones en `position_tracker.json`
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