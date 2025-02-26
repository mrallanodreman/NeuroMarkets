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



    def detect_trend(self, historical_data): 
        """
        Detecta la tendencia actual del mercado utilizando MACD, EMAs y análisis de mínimos correctamente.
        Se basa exclusivamente en `historical_data`.
        """
        historical_data, _ = self.load_historical_data()  # Usamos solo historical_data

        if historical_data.empty or len(historical_data) < 6:
            return "⚠️ Datos insuficientes para determinar tendencia"

        # Convertir posibles valores de diccionario en "Low"
        if isinstance(historical_data["Low"].iloc[0], dict):
            historical_data["Low"] = historical_data["Low"].apply(lambda x: (x["bid"] + x["ask"]) / 2 if isinstance(x, dict) else x)

        latest_data = historical_data.iloc[-1]
        previous_data = historical_data.iloc[-2]

        trend = "Sin tendencia clara"

        # ✅ Comparar precio reciente con el anterior
        if latest_data["Close"] > previous_data["Close"]:
            trend = "📈 Posible tendencia alcista"
        elif latest_data["Close"] < previous_data["Close"]:
            trend = "📉 Posible tendencia bajista"

        # ✅ Confirmación de MACD
        if latest_data["MACD"] > latest_data["MACD_Signal"] and latest_data["MACD"] > previous_data["MACD"]:
            trend = "Tendencia alcista con impulso positivo"
        elif latest_data["MACD"] < latest_data["MACD_Signal"] and latest_data["MACD"] < previous_data["MACD"]:
            trend = "Tendencia bajista con impulso negativo"

        # ✅ Confirmación con EMAs (Cambios rápidos)
        if latest_data["EMA_6"] > latest_data["EMA_14"] and previous_data["EMA_6"] <= previous_data["EMA_14"]:
            trend = "🚀 Cambio a tendencia alcista"
        elif latest_data["EMA_6"] < latest_data["EMA_14"] and previous_data["EMA_6"] >= previous_data["EMA_14"]:
            trend = "⚠️ Cambio a tendencia bajista"

        # ✅ Confirmación con EMA de 20 períodos (Medio Plazo)
        if latest_data["Close"] > latest_data["EMA_20"]:
            trend += " (Confirmado en marco medio plazo)"
        elif latest_data["Close"] < latest_data["EMA_20"]:
            trend += " (Debilidad en marco medio plazo)"

        # ✅ Confirmación con EMA de 50 períodos (Largo Plazo)
        if latest_data["Close"] > latest_data["EMA_50"]:
            trend += " (Confirmado en marco largo plazo)"
        elif latest_data["Close"] < latest_data["EMA_50"]:
            trend += " (Tendencia bajista en marco largo plazo)"

        # ✅ Volatilidad con ATR (Usando historical_data en lugar de data)
        if latest_data["ATR"] > historical_data["ATR"].mean():
            trend += " con alta volatilidad"

        # ✅ Impulso confirmado con RSI
        if latest_data["RSI"] > 70:
            trend += " 🚀 Posible sobrecompra"
        elif latest_data["RSI"] < 30:
            trend += " 🔄 Posible sobreventa"

        # 🚀 **Análisis de los últimos 6 Low**
        last_lows = historical_data["Low"].tail(6).values
        up_count = sum(last_lows[i] < last_lows[i + 1] for i in range(len(last_lows) - 1))
        down_count = sum(last_lows[i] > last_lows[i + 1] for i in range(len(last_lows) - 1))

        if up_count >= 4:
            trend = "📈 Tendencia alcista (Mínimos ascendentes)"
        elif down_count >= 4:
            trend = "📉 Tendencia bajista (Mínimos descendentes)"

        # 🚩 Bandas de Bollinger - Detección dinámica
        upper_band = latest_data["EMA_20"] + (2 * latest_data["BB_width"])
        lower_band = latest_data["EMA_20"] - (2 * latest_data["BB_width"])
        current_price = latest_data["Close"]

        if current_price <= lower_band:
            trend += " | 🔄 Cerca de Banda Inferior (Posible rebote)"
        elif current_price >= upper_band:
            trend += " | 🔻 Cerca de Banda Superior (Posible rechazo)"

        # 🚩 Soporte y Resistencia (Últimos 50 registros en historical_data)
        support_level = min(historical_data["Low"].tail(50))
        resistance_level = max(historical_data["High"].tail(50))

        # ✅ Rebotes en soportes y resistencias
        if abs(current_price - support_level) / support_level <= 0.03:
            if latest_data["RSI"] < 35 and latest_data["MACD"] > latest_data["MACD_Signal"]:
                trend += f" | 🔄 Rebote confirmado en soporte ({support_level:.2f})"

        if abs(current_price - resistance_level) / resistance_level <= 0.03:
            if latest_data["RSI"] > 65 and latest_data["MACD"] < latest_data["MACD_Signal"]:
                trend += f" | 🔻 Rechazo confirmado en resistencia ({resistance_level:.2f})"

        return trend




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
        volume_change = features.get("VolumeChange", 0)
        obv = features.get("OBV", 0)  # Confirmación de tendencia con volumen

        # Calcular el volumen reciente y el volumen promedio (si hay suficientes datos)
        if len(self.price_history) >= 10:
            recent_volume = sum(entry.get("Volume", 0) for entry in self.price_history[-10:]) / 10
        else:
            recent_volume = 0

        if len(self.price_history) >= 50:
            avg_volume = sum(entry.get("Volume", 0) for entry in self.price_history[-50:]) / 50
        else:
            avg_volume = recent_volume


        # 📌 Función para calcular el tamaño de posición
        def calculate_position_size(balance, leverage, current_price, risk_factor, min_size=0.009, max_size=0.009):
            margin_to_use = balance * risk_factor * margin_protection
            position_size = (margin_to_use * leverage) / current_price
            position_size = max(min(position_size, max_size), min_size)
            margin_required = (position_size * abs(current_price)) / leverage
            return round(position_size, 4), margin_required

        
        # 🚨 **Evitar operar en sesiones de bajo volumen**
        if recent_volume < avg_volume * 0.5:
            return {"action": "hold", "size": 0, "reason": "Volumen actual bajo, posible falta de movimiento"}

        # Detectar rebote abrupto basado en el cambio porcentual del precio
        if len(self.price_history) > 1:
            prev_close = self.price_history[-2].get("Close", current_price)
            price_change_pct = (current_price - prev_close) / prev_close
            # Si el precio sube abruptamente (por ejemplo, más del 0.5%) en la última barra,
            # se podría interpretar como un rebote y, por lo tanto, evitar abrir una posición Short.
            if price_change_pct > 0.005:
                return {"action": "hold", "size": 0, "reason": "Rebote abrupto detectado (cambio > 0.5%), evitando Short"}

        if not (rsi < 40 and macd < -1):
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

        # ✅ Condición alternativa sin usar avg_atr
        if volume_change < -0.3 and atr > 5 and balance >= margin_required:
            return {
                "action": "Short",
                "size": position_size,
                "market_id": market_id,
                "margin_required": margin_required,
                "reason": "Volumen en descenso y alta volatilidad detectada por ATR elevado"
            }

        # 🔻 **Condiciones alternativas para Short: Volumen de venta y ATR alto**
        if volume_change < -0.3 and atr > 5 and balance >= margin_required:
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