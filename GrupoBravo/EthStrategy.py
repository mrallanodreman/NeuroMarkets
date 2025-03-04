from EthSession import CapitalOP
import pickle
from datetime import datetime, timezone
import json
import os
import json
import pandas as pd


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

    def load_historical_data(self):
        """
        Carga los datos históricos y los datos de 1 minuto desde el archivo JSON generado por DataEth.py.
        """
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Reports", "ETHUSD_CapitalData.json")

        print(f"[DEBUG] 📁 Buscando archivo en: {file_path}")

        if not os.path.exists(file_path):
            print("[ERROR] ❌ No se encontró el archivo de datos históricos:", file_path)
            return pd.DataFrame(), pd.DataFrame()

        try:
            with open(file_path, "r") as file:
                json_data = json.load(file)

            # ✅ Acceder correctamente a "data" en lugar de "data_1m"
            if "historical_data" not in json_data or "data" not in json_data:
                print("[ERROR] ❌ El archivo JSON no contiene las claves esperadas ('historical_data' y 'data').")
                return pd.DataFrame(), pd.DataFrame()

            historical_data = pd.DataFrame(json_data["historical_data"])
            data = pd.DataFrame(json_data["data"])  # 🔥 Ahora accede correctamente

            # ✅ Convertir "Datetime" a formato datetime y establecer como índice
            for df in [historical_data, data]:
                if "Datetime" in df.columns:
                    df["Datetime"] = pd.to_datetime(df["Datetime"], unit="ms", errors="coerce")
                    df.dropna(subset=["Datetime"], inplace=True)
                    df.set_index("Datetime", inplace=True)
                    df.sort_index(inplace=True)

            print(f"[INFO] ✅ Datos cargados correctamente: {len(historical_data)} registros históricos, {len(data)} registros de 1M.")

            return historical_data, data  # ✅ Ahora sí devuelve `data` correctamente

        except Exception as e:
            print("[ERROR] ❌ Error al cargar el archivo de datos históricos:", str(e))
            return pd.DataFrame(), pd.DataFrame()

    def detect_reversal_attempt(self, historical_data, ):
        """
        Detecta intentos de reversión en tiempo real basado en:
        - Cruces del MACD sobre su línea de señal.
        - Rebotes fuertes del RSI desde sobreventa o sobrecompra.
        - Expansión de ATR indicando aumento de volatilidad.
        - Aumento en volumen cerca de zonas de soporte/resistencia.
        """

        if historical_data.empty or len(historical_data) < 10:
            return None  # No hay datos suficientes

        latest_data = historical_data.iloc[-1]
        previous_data = historical_data.iloc[-2]

        # 📊 Calculamos el volumen promedio con un factor de confirmación más alto
        volume_threshold = historical_data["Volume"].rolling(10).mean() * 1.5  # Volumen debe ser 1.5x la media

        # 🚀 **Intento de reversión alcista** (Confirmamos con más validaciones)
        bullish_reversal = (
            latest_data["MACD"] > latest_data["MACD_Signal"] and  # MACD cruza hacia arriba
            previous_data["MACD"] <= previous_data["MACD_Signal"] and
            latest_data["MACD"] > previous_data["MACD"] and  # MACD debe seguir subiendo
            latest_data["RSI"] > 40 and previous_data["RSI"] <= 30 and  # RSI rebota con más fuerza
            latest_data["ATR"] > historical_data["ATR"].rolling(10).mean() and  # Volatilidad en aumento
            latest_data["Volume"] > volume_threshold  # Volumen realmente superior
        )

        # ⚠ **Intento de reversión bajista** (Evitamos falsos negativos)
        bearish_reversal = (
            latest_data["MACD"] < latest_data["MACD_Signal"] and  # MACD cruza hacia abajo
            previous_data["MACD"] >= previous_data["MACD_Signal"] and
            latest_data["MACD"] < previous_data["MACD"] and  # MACD debe seguir bajando
            latest_data["RSI"] < 60 and previous_data["RSI"] >= 70 and  # RSI cae con más confirmación
            latest_data["ATR"] > historical_data["ATR"].rolling(10).mean() and  # Volatilidad en aumento
            latest_data["Volume"] > volume_threshold  # Volumen realmente superior
        )

        # 📢 **Señales de reversión**
        if bullish_reversal:
            return "🟢 Intento de reversión alcista 🚀 (Confirmado con volumen y RSI fuerte)"
        elif bearish_reversal:
            return "🔴 Intento de reversión bajista ⚠ (Confirmado con volumen y RSI cayendo fuerte)"
        else:
            return None


    def detect_trend(self, historical_data, data):
        """
        Detección de tendencias mejorada con señales optimizadas de BUY, SELL y HOLD.
        - Confirma tendencias con EMAs de mayor plazo.
        - Evalúa señales alcistas y bajistas con RSI, MACD, volumen y soportes/resistencias.
        - Mayor precisión en la detección de cambios de tendencia y zonas de sobrecompra/sobreventa.
        - Devuelve una razón clara para cada decisión.
        """

        if historical_data.empty or len(historical_data) < 6:
            return {"trend": "[⚠️] Datos insuficientes", "reason": "Historial insuficiente para análisis", "signal": "HOLD ⚠️"}

        # Asegurar que los precios no sean diccionarios
        for col in ["Low", "High", "Open", "Close"]:
            if isinstance(historical_data[col].iloc[0], dict):
                historical_data[col] = historical_data[col].apply(lambda x: (x["bid"] + x["ask"]) / 2 if isinstance(x, dict) else x)

        latest_data = data.iloc[-1]
        previous_data = data.iloc[-2]

        trend = "[🔍] Sin tendencia clara"
        trend_confirmed = "[🔍] Tendencia no confirmada"
        signal = "HOLD ⚠️"
        reason = "No hay suficiente información para determinar una señal clara."

        ## 📉 **MICROTENDENCIA BAJISTA**
        if latest_data["Close"] < previous_data["Close"]:
            trend = "[📉] Microtendencia bajista"
            reason = "El cierre actual es menor que el anterior."

            # 🔹 Impulso con MACD Histograma
            if latest_data["MACD_Histogram"] < 0 and latest_data["MACD_Histogram"] < previous_data["MACD_Histogram"]:
                trend += " ➜ Impulso bajista fuerte"
                reason += " MACD muestra una aceleración bajista."

            # 🔹 Cruce de EMAs ultrarrápidas (3 vs 9)
            if latest_data["EMA_3"] < latest_data["EMA_9"] and previous_data["EMA_3"] >= previous_data["EMA_9"]:
                trend += " ⚠️ Aceleración bajista"
                reason += " La EMA de 3 períodos cruzó por debajo de la EMA de 9 períodos."

            # 🔹 Confirmación con volumen alto
            if latest_data["Volume"] > historical_data["Volume"].mean():
                trend += " 📉 Volumen alto confirma tendencia"
                reason += " El volumen es superior al promedio, validando la tendencia bajista."

        ## 📈 **MICROTENDENCIA ALCISTA**
        elif latest_data["Close"] > previous_data["Close"]:
            trend = "[📈] Microtendencia alcista"
            reason = "El cierre actual es mayor que el anterior."

            # 🔹 Impulso con MACD Histograma
            if latest_data["MACD_Histogram"] > 0 and latest_data["MACD_Histogram"] > previous_data["MACD_Histogram"]:
                trend += " ➜ Impulso alcista fuerte"
                reason += " MACD muestra una aceleración alcista."

            # 🔹 Cruce de EMAs ultrarrápidas (3 vs 9)
            if latest_data["EMA_3"] > latest_data["EMA_9"] and previous_data["EMA_3"] <= previous_data["EMA_9"]:
                trend += " ⚠️ Aceleración alcista"
                reason += " La EMA de 3 períodos cruzó por encima de la EMA de 9 períodos."

            # 🔹 Confirmación con volumen alto
            if latest_data["Volume"] > historical_data["Volume"].mean():
                trend += " 📈 Volumen alto confirma tendencia"
                reason += " El volumen es superior al promedio, validando la tendencia alcista."

        ## 🚀 **TENDENCIA CONFIRMADA**
        if latest_data["EMA_20"] > latest_data["EMA_50"] and latest_data["Close"] > latest_data["EMA_50"]:
            trend_confirmed = "[🚀] Tendencia alcista confirmada"
            reason += " La EMA de 20 períodos está por encima de la EMA de 50 períodos, y el precio está sobre la EMA de 50."
        elif latest_data["EMA_20"] < latest_data["EMA_50"] and latest_data["Close"] < latest_data["EMA_50"]:
            trend_confirmed = "[📉] Tendencia bajista confirmada"
            reason += " La EMA de 20 períodos está por debajo de la EMA de 50 períodos, y el precio está debajo de la EMA de 50."

        ## 🚀 **SOPORTES Y RESISTENCIAS + REBOTES**
        support_level = min(historical_data["Low"].tail(10))
        resistance_level = max(historical_data["High"].tail(10))
        current_price = latest_data["Close"]

        # 📌 **Posible rebote detectado**
        if abs(current_price - support_level) / support_level <= 0.005 and latest_data["RSI_7"] < 35:
            trend += f" ⚠ Soporte detectado en {support_level:.2f} (posible rebote)"
            reason += f" El precio está cerca del soporte en {support_level:.2f} con RSI bajo."

            # ✅ **Confirmación de rebote**
            if (
                historical_data["Close"].iloc[-3] < historical_data["Close"].iloc[-2] < latest_data["Close"]
                and latest_data["MACD_Histogram"] > 0
                and latest_data["RSI_7"] > previous_data["RSI_7"]
                and latest_data["Volume"] > historical_data["Volume"].mean()
            ):
                trend += f" [✔️ REBOTE CONFIRMADO] 🎯 Precio subió desde soporte con fuerza"
                reason += " Confirmación con MACD positivo, RSI subiendo y volumen alto."
                signal = "BUY ✅"

        # 📌 **Posible reversión en resistencia**
        elif abs(current_price - resistance_level) / resistance_level <= 0.005 and latest_data["RSI_7"] > 65:
            trend += f" ⚠ Resistencia detectada en {resistance_level:.2f} (posible reversión)"
            reason += f" El precio está cerca de la resistencia en {resistance_level:.2f} con RSI alto."

            # ✅ **Confirmación de reversión bajista**
            if (
                historical_data["Close"].iloc[-3] > historical_data["Close"].iloc[-2] > latest_data["Close"]
                and latest_data["MACD_Histogram"] < 0
                and latest_data["RSI_7"] < previous_data["RSI_7"]
                and latest_data["Volume"] > historical_data["Volume"].mean()
            ):
                trend += f" [✔️ REVERSIÓN CONFIRMADA] 📉 Precio rechazado en resistencia con fuerza"
                reason += " Confirmación con MACD negativo, RSI bajando y volumen alto."
                signal = "SELL ❌"

        # Asegurar que trend_confirmed y trend siempre tengan valores
        # Asegurar que trend_confirmed y trend siempre tengan valores
        trend_confirmed = trend_confirmed if trend_confirmed else "[🔍] Tendencia no confirmada"
        trend = trend if trend else "[🔍] Sin tendencia clara"

        ## 🔥 **DECISIÓN FINAL MEJORADA**
        if "Tendencia bajista confirmada" in trend_confirmed:
            if "Microtendencia alcista ➜ Impulso alcista fuerte" in trend:
                signal = "BUY ✅"  # 📌 Ahora permitimos comprar en rebote fuerte dentro de tendencia bajista
                reason += " 🚀 Microtendencia alcista con impulso fuerte dentro de tendencia bajista, posible rebote."
            else:
                signal = "SELL ❌"  # 📉 Mantiene la venta si la microtendencia también es bajista
                reason += " 🔻 Tendencia bajista confirmada sin señales claras de reversión."

        elif "Tendencia alcista confirmada" in trend_confirmed:
            if "Microtendencia bajista ➜ Impulso bajista fuerte" in trend:
                signal = "SELL ❌"  # 📌 Ahora permitimos vender en un posible rechazo dentro de tendencia alcista
                reason += " 📉 Microtendencia bajista con impulso fuerte dentro de tendencia alcista, posible rechazo."
            else:
                signal = "BUY ✅"  # 📈 Mantiene la compra si la microtendencia también es alcista
                reason += " 📈 Tendencia alcista confirmada con microtendencia alcista."

        else:
            signal = "HOLD ⚠️"
            reason += " 🤷 No hay señales claras para operar."

        return {
            "trend": f"{trend_confirmed} | {trend}",
            "reason": reason,
            "signal": signal
        }


    def decide(self, current_price, data , balance, features, market_id, historical_data, open_positions=None):
        """
        Toma una decisión de trading basada en la detección de tendencia `detect_trend()`
        - No se basa en condiciones propias, sino en la salida de `detect_trend()`
        - Calcula tamaño de posición dinámico basado en balance y apalancamiento
        - Evita operar en condiciones de bajo volumen o volatilidad insuficiente
        """

        print(f"[DEBUG] Decidiendo para precio={current_price} y balance={balance}")

        if current_price <= 0 or balance <= 0:
            return {"action": "hold", "size": 0, "reason": "Precio o balance inválido"}

        # 📌 Obtener información de tendencias desde `detect_trend()`
        trend_analysis = self.detect_trend(historical_data, data)
        trend_detected = trend_analysis["trend"]
        reason_detected = trend_analysis["reason"]  
        signal = trend_analysis["signal"]

        print(f"[INFO] 🔍 Análisis de tendencia: {trend_detected}")
        print(f"[INFO] 📋 Razón de la señal: {reason_detected}")
        print(f"[INFO] 🏁 Señal generada: {signal}")

        # 📌 Contar posiciones abiertas
        num_buy_positions = sum(1 for p in open_positions if p.get("direction") == "BUY") if open_positions else 0
        num_sell_positions = sum(1 for p in open_positions if p.get("direction") == "SELL") if open_positions else 0

        # 📌 Límites de posiciones desde CapitalOP
        max_buy_positions = self.capital_ops.max_buy_positions
        max_sell_positions = self.capital_ops.max_sell_positions

        # 📌 Definir reason_decide basado en reason_detected
        reason_decide = reason_detected  

        # 📌 Evitar abrir más posiciones si se alcanzó el límite
        if signal == "BUY ✅" and num_buy_positions >= max_buy_positions:
            reason_decide = f"🚨 Límite de posiciones BUY alcanzado ({max_buy_positions}). Manteniendo posición."
            print(f"[INFO] {reason_decide}")
            return {"action": "hold", "size": 0, "reason": reason_decide}  

        if signal == "SELL ❌" and num_sell_positions >= max_sell_positions:
            reason_decide = f"🚨 Límite de posiciones SELL alcanzado ({max_sell_positions}). Manteniendo posición."
            print(f"[INFO] {reason_decide}")
            return {"action": "hold", "size": 0, "reason": reason_decide}  

        # 📌 Verificar si la señal es "HOLD" (esperar sin operar)
        if signal == "HOLD ⚠️":
            print(f"[INFO] ⏳ Manteniendo posición: {reason_decide}")
            return {"action": "hold", "size": 0, "reason": reason_decide}

        # 📌 Cálculo de tamaño de posición dinámico
        def calculate_position_size(balance, leverage, current_price, risk_factor, min_size=0.009, max_size=0.05):
            margin_to_use = balance * risk_factor * 0.9  
            position_size = (margin_to_use * leverage) / current_price
            position_size = max(min(position_size, max_size), min_size)  
            margin_required = (position_size * abs(current_price)) / leverage
            return round(position_size, 4), margin_required

        # 📌 Determinar riesgo y calcular el tamaño de la posición
        risk_factor = 0.01 if signal == "SELL ❌" else 0.02  
        position_size, margin_required = calculate_position_size(balance, 20, current_price, risk_factor)

        print(f"[INFO] 🔢 Tamaño de posición calculado: {position_size} (Requerimiento de margen: {margin_required})")

        # 📌 Validación de balance disponible
        if balance < margin_required:
            reason_decide = "⚠️ Balance insuficiente para abrir posición"
            print(f"[WARNING] {reason_decide} (Necesario: {margin_required}, Disponible: {balance})")
            return {"action": "hold", "size": 0, "reason": reason_decide}  

        # 📌 Decisión final basada en la señal de `detect_trend()`
        if signal == "BUY ✅":
            print(f"[TRADE] 🟢 Orden de COMPRA detectada. Ejecutando trade.")
            return {
                "action": "BUY",
                "direction": "BUY",
                "size": position_size,
                "market_id": market_id,
                "margin_required": margin_required,
                "reason": reason_decide  # ✅ Usamos reason_decide en lugar de reason_detected
            }

        elif signal == "SELL ❌":
            print(f"[TRADE] 🔴 Orden de VENTA detectada. Ejecutando trade.")
            return {
                "action": "SELL",
                "direction": "SELL",
                "size": position_size,
                "market_id": market_id,
                "margin_required": margin_required,
                "reason": reason_decide  # ✅ Usamos reason_decide en lugar de reason_detected
            }

        # 📌 Si por algún motivo no se toma acción, mantener posición
        print(f"[INFO] ⏳ No se cumple ninguna condición de trading.")
        return {"action": "hold", "size": 0, "reason": reason_decide}  


    def evaluate_positions(self, positions, current_price, features):
        """
        Evalúa posiciones abiertas para decidir si cerrarlas.
        Nunca cierra posiciones en negativo.
        Mantiene posiciones positivas mientras la tendencia las respalde.
        Si hay un retroceso considerable, se cierran para asegurar ganancia.
        Actualiza cada posición con un campo 'reason' que explica la decisión.
        Retorna la lista de acciones a cerrar.
        """
        to_close = []
        now_time = datetime.now(timezone.utc)

        # Asegurar que self.position_tracker esté disponible
        if not hasattr(self, "position_tracker"):
            print("[WARNING] `position_tracker` no estaba definido en Strategy. Se inicializa vacío.")
            self.position_tracker = {}

        # Intentar cargar tracker previo
        try:
            with open("position_tracker.json", "r") as file:
                self.position_tracker = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            print("[WARNING] No se encontró `position_tracker.json` o estaba corrupto. Se usará un nuevo tracker.")
            self.position_tracker = {}

        # Parámetros para cierre
        minimum_profit_threshold = 0.03  # Se requiere al menos $0.03 de ganancia para considerar cierre
        closure_percentage = 0.90          # Cerrar si upl cae por debajo del 90% del máximo alcanzado

        for position in positions:
            deal_id = position.get("dealId")
            size = position.get("size")
            upl = position.get("upl", 0)  # Ganancia no realizada
            hours_open = position.get("hours_open")

            # Inicializar el campo 'reason' en la posición
            position["reason"] = ""

            if hours_open is None:
                msg = f"[WARNING] No se encontró 'hours_open' en la posición {deal_id}."
                print(msg)
                position["reason"] += msg
                continue

            position["hours_open"] = hours_open
            print(f"[INFO] Evaluando posición {deal_id} - Abierta hace {float(hours_open):.1f} horas - UPL: {float(upl):.5f}")

            # No se cierran posiciones en negativo
            if upl < 0:
                msg = f"[DEBUG]  ganancia negativa ({upl * 100:.2f}%)."
                print(msg)
                position["reason"] += msg
                continue

            # Actualizar o inicializar el máximo alcanzado para la posición
            if deal_id not in self.position_tracker:
                self.position_tracker[deal_id] = {"max_profit": 0}
            previous_max_profit = self.position_tracker[deal_id].get("max_profit", 0)
            updated_max_profit = max(previous_max_profit, upl)
            self.position_tracker[deal_id]["max_profit"] = updated_max_profit
            position["max_profit"] = updated_max_profit
            msg_update = f"[INFO] Max Profit para {deal_id} actualizado a {updated_max_profit * 100:.2f}%."
            print(msg_update)
            position["reason"] += msg_update

            # Aplicar mecanismo de retroceso: se cierra si upl cae por debajo del 90% del máximo alcanzado,
            # siempre que upl supere el mínimo para cierre.
            if upl > minimum_profit_threshold and upl < updated_max_profit * closure_percentage:
                rsi = features.get("RSI", 0)
                macd = features.get("MACD", 0)
                volume_change = features.get("VolumeChange", 0)
                if rsi > 50 and macd > 0 and volume_change > 0:
                    msg = f" | Sostener {deal_id}: Indicadores favorables (RSI={rsi}, MACD={macd}, VolChange={volume_change})."
                    print(f"[INFO]{msg}")
                    position["reason"] += msg
                else:
                    msg = (f" | Cerrar {deal_id} por retroceso: upl ({upl * 100:.2f}%) < 90% del Max Profit ({updated_max_profit * 100:.2f}%).")
                    print(f"[INFO]{msg}")
                    position["reason"] += msg
                    to_close.append({
                        "action": "Close",
                        "dealId": deal_id,
                        "size": size,
                        "reason": position["reason"]
                    })
            else:
                msg = f" | No cerrar {deal_id}: upl ({upl * 100:.2f}%) es adecuado (>= 90% del Max Profit: {updated_max_profit * 100:.2f}%)."
                print(f"[INFO]{msg}")
                position["reason"] += msg

            # Cierre forzado por tiempo: si la posición tiene más de 24h y upl es al menos 0.5%
            if hours_open >= 24 and upl >= 0.5:
                msg = f" | Cierre forzado {deal_id} por tiempo: {hours_open:.1f}h con ganancia {upl * 100:.2f}%."
                print(f"[INFO]{msg}")
                position["reason"] += msg
                to_close.append({
                    "action": "Close",
                    "dealId": deal_id,
                    "size": size,
                    "reason": position["reason"]
                })

        # Guardar el tracker actualizado
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