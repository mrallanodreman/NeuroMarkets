from EthSession import CapitalOP
from PositionValidator import PositionValidator
from EthConfig import FIXED_POSITION_SIZE, POSITION_SIZE_TIERS, SUPPORT_TOLERANCE, RECENT_RALLY_WINDOW_MIN, RECENT_RALLY_PCT, ADX_TREND_THRESHOLD, VOLUME_NEG_THRESHOLD, STOP_LOSS, STOP_LOSS_PCT
import pickle
from datetime import datetime, timezone
import json
import os
import time
import pandas as pd
import re


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
        self.market_bias = None
        self.market_regime = None
        self.bias_age = 0
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

            # ✅ Acceder correctamente a "ltf_data" (Low Time Frame)
            if "historical_data" not in json_data or "ltf_data" not in json_data:
                print("[ERROR] ❌ El archivo JSON no contiene las claves esperadas ('historical_data' y 'ltf_data').")
                return pd.DataFrame(), pd.DataFrame()

            historical_data = pd.DataFrame(json_data["historical_data"])
            data = pd.DataFrame(json_data["ltf_data"])  # 🔥 Usar ltf_data

            # ✅ Convertir timestamp a formato datetime y establecer como índice
            for df in [historical_data, data]:
                # Buscar columna de timestamp (puede ser 'timestamp', 'Datetime', 'snapshotTime', etc.)
                ts_col = None
                for col in ['timestamp', 'Datetime', 'snapshotTime', 'Open_time']:
                    if col in df.columns:
                        ts_col = col
                        break

                if ts_col:
                    # Si es timestamp ISO string, parsearlo directamente
                    df['Datetime'] = pd.to_datetime(df[ts_col], utc=True, errors='coerce')
                    df.dropna(subset=["Datetime"], inplace=True)
                    df.set_index("Datetime", inplace=True)
                    if ts_col != 'Datetime':
                        df.drop(columns=[ts_col], inplace=True, errors='ignore')
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
            return {"trend": "[⚠️] Datos insuficientes HTF", "reason": "Historial HTF insuficiente para análisis", "signal": "HOLD ⚠️"}

        if data.empty or len(data) < 2:
            return {"trend": "[⚠️] Datos insuficientes LTF", "reason": "Se requieren al menos 2 velas LTF para análisis", "signal": "HOLD ⚠️"}

        # Asegurar que los precios no sean diccionarios
        for col in ["Low", "High", "Open", "Close"]:
            if isinstance(historical_data[col].iloc[0], dict):
                historical_data[col] = historical_data[col].apply(lambda x: (x["bid"] + x["ask"]) / 2 if isinstance(x, dict) else x)

        # Separar claramente timeframe mayor (historical_data) y menor (data - 1m)
        l_latest = data.iloc[-1]
        l_prev = data.iloc[-2]

        h_latest = historical_data.iloc[-1]
        h_prev = historical_data.iloc[-2] if len(historical_data) >= 2 else h_latest

        # Nombres antiguos para compatibilidad con el código existente
        latest_data = l_latest
        previous_data = l_prev

        # Precalcular medias/rollings por timeframe para evitar mezclas
        try:
            l_volume_mean = data["Volume"].mean()
        except Exception:
            l_volume_mean = 0
        try:
            l_volume_rolling10 = data["Volume"].rolling(10).mean().iloc[-1] if len(data) >= 10 else l_volume_mean
        except Exception:
            l_volume_rolling10 = l_volume_mean

        try:
            h_volume_mean = historical_data["Volume"].mean()
        except Exception:
            h_volume_mean = 0
        try:
            h_volume_rolling10 = historical_data["Volume"].rolling(10).mean().iloc[-1] if len(historical_data) >= 10 else h_volume_mean
        except Exception:
            h_volume_rolling10 = h_volume_mean

        trend = "[🔍] Sin tendencia clara"
        trend_confirmed = "[🔍] Tendencia no confirmada"
        signal = "HOLD ⚠️"
        reason = "No hay suficiente información para determinar una señal clara."

        ## 🎯 **CÁLCULO DE SOPORTES Y RESISTENCIAS**
        support_level = min(historical_data["Low"].tail(75))  # 75 velas HTF
        resistance_level = max(historical_data["High"].tail(75))
        current_price = latest_data["Close"]

        # Calcular distancias porcentuales
        dist_to_support_pct = ((current_price - support_level) / support_level) * 100
        dist_to_resistance_pct = ((resistance_level - current_price) / current_price) * 100

        # 🎯 ZONAS DE SOPORTE (3 niveles de riesgo) - Definidas ANTES de usarse
        zona_soporte_critica = dist_to_support_pct <= 0.5   # ≤0.5% - ALTO riesgo SELL
        zona_soporte_cercana = 0.5 < dist_to_support_pct <= 1.5  # 0.5-1.5% - Precaución
        zona_rebote_probable = dist_to_support_pct <= 2.0   # ≤2% - Zona de rebote

        # 🎯 ZONAS DE RESISTENCIA
        zona_resistencia_critica = dist_to_resistance_pct <= 0.5
        zona_resistencia_cercana = 0.5 < dist_to_resistance_pct <= 1.5

        # 🚨 DETECCIÓN DE SOPORTE ROTO (precio debajo del mínimo de 75H)
        soporte_roto = current_price < support_level

        # --- Debug: volcado detallado de indicadores clave para diagnóstico ---
        try:
            debug_values = {
                "Datetime": str(latest_data.name) if hasattr(latest_data, 'name') else str(latest_data.get('Datetime', '')),
                "L_Close": float(latest_data.get("Close", float('nan'))),
                "L_RSI": float(latest_data.get("RSI", float('nan'))),
                "L_RSI_7": float(latest_data.get("RSI_7", float('nan'))),
                "L_EMA_3": float(latest_data.get("EMA_3", float('nan'))),
                "L_EMA_9": float(latest_data.get("EMA_9", float('nan'))),
                "L_EMA_20": float(latest_data.get("EMA_20", float('nan'))),
                "L_EMA_50": float(latest_data.get("EMA_50", float('nan'))),
                "L_MACD": float(latest_data.get("MACD", float('nan'))),
                "L_MACD_Hist": float(latest_data.get("MACD_Histogram", float('nan'))),
                "L_Volume": float(latest_data.get("Volume", 0)),
                "L_Volume_Roll10": float(l_volume_rolling10 if l_volume_rolling10 is not None else 0),
                "H_EMA_20": float(h_latest.get("EMA_20", float('nan'))),
                "H_EMA_50": float(h_latest.get("EMA_50", float('nan'))),
                "H_RSI": float(h_latest.get("RSI", float('nan'))),
                "H_Volume": float(h_latest.get("Volume", 0)),
                "Support": float(support_level),
                "Resistance": float(resistance_level),
                "Dist_Support_%": round(dist_to_support_pct, 2),
                "Dist_Resistance_%": round(dist_to_resistance_pct, 2)
            }
        except Exception:
            debug_values = {"error": "no se pudo construir debug_values"}

        try:
            print(f"[DEBUG_VALUES] {json.dumps(debug_values, default=str)}")
        except Exception:
            print(f"[DEBUG_VALUES] {str(debug_values)}")
        # --------------------------------------------------------------------

        # Inicializar variables de confianza y candidatos
        confianza = 0
        confianza_score = 0  # Score final para retornar
        detalles = []
        candidato_signal = None  # "BUY" | "SELL" | None
        candidato_reason = ""

        ## 📉 **MICROTENDENCIA BAJISTA**
        if latest_data["Close"] < previous_data["Close"]:
            trend = "[📉] Microtendencia bajista"
            reason = "El cierre actual es menor que el anterior."

            # 🔹 Impulso con MACD Histograma
            if latest_data["MACD_Histogram"] < 0 and latest_data["MACD_Histogram"] < previous_data["MACD_Histogram"]:
                trend += " ➜ Impulso bajista fuerte"
                reason += " MACD Histogram muestra una aceleración bajista."

            # 🔹 Cruce de EMAs ultrarrápidas (3 vs 9)
            if latest_data["EMA_3"] < latest_data["EMA_9"] and previous_data["EMA_3"] >= previous_data["EMA_9"]:
                trend += " ⚠️ Aceleración bajista"
                reason += " La EMA de 3 períodos cruzó por debajo de la EMA de 9 períodos."

            # 🔹 Confirmación con volumen alto (usar LTF vs LTF promedio)
            if l_latest["Volume"] > l_volume_mean:
                trend += " 📉 Volumen alto confirma tendencia"
                reason += " El volumen es superior al promedio, validando la tendencia bajista."

        ## 📈 **MICROTENDENCIA ALCISTA**
        elif latest_data["Close"] > previous_data["Close"]:
            trend = "[📈] Microtendencia alcista"
            reason = "El cierre actual es mayor que el anterior."

            # 🔹 Impulso con MACD Histograma
            if latest_data["MACD_Histogram"] > 0 and latest_data["MACD_Histogram"] > previous_data["MACD_Histogram"]:
                trend += " ➜ Impulso alcista fuerte"
                reason += " MACD Histogram muestra una aceleración alcista."

            # 🔹 Cruce de EMAs ultrarrápidas (3 vs 9)
            if latest_data["EMA_3"] > latest_data["EMA_9"] and previous_data["EMA_3"] <= previous_data["EMA_9"]:
                trend += " ⚠️ Aceleración alcista"
                reason += " La EMA de 3 períodos cruzó por encima de la EMA de 9 períodos."

            # 🔹 Confirmación con volumen alto (usar LTF vs LTF promedio)
            if l_latest["Volume"] > l_volume_mean:
                trend += " 📈 Volumen alto confirma tendencia"
                reason += " El volumen es superior al promedio, validando la tendencia alcista."

            # 🎯 BONUS: Rebote desde zona de soporte confirmado
            if zona_rebote_probable and h_latest["RSI_7"] < 50:
                trend += " 🚀 REBOTE DESDE SOPORTE detectado"
                reason += f" Precio rebotando desde soporte en ${support_level:.2f} ({dist_to_support_pct:.2f}% distancia). Oportunidad de compra."

        ## 🚀 TENDENCIA CONFIRMADA
        # Para confirmar una tendencia usamos el timeframe mayor (historical_data)
        if (
            h_latest["EMA_20"] > h_latest["EMA_50"] and
            h_latest["Close"] > h_latest["EMA_50"] and
            h_latest["EMA_20"] > h_prev["EMA_20"] and
            h_latest["Volume"] > h_volume_rolling10 and
            h_latest["RSI"] > 50
        ):
            trend_confirmed = "[🚀] Tendencia alcista confirmada"
            reason += " Confirmación de tendencia alcista: EMA 20 > EMA 50, precio sobre EMA 50, volumen alto y RSI > 50."
        elif (
            h_latest["EMA_20"] < h_latest["EMA_50"] and
            h_latest["Close"] < h_latest["EMA_50"] and
            h_latest["EMA_20"] < h_prev["EMA_20"] and
            h_latest["Volume"] > h_volume_rolling10 and
            h_latest["RSI"] < 50
        ):
            trend_confirmed = "[📉] Tendencia bajista confirmada"
            reason += " Confirmación de tendencia bajista: EMA 20 < EMA 50, precio bajo EMA 50, volumen alto y RSI < 50."


        ## 🚀 **ANÁLISIS AVANZADO DE SOPORTES Y RESISTENCIAS**
        # Ya calculados arriba: support_level, resistance_level, current_price, zonas

        # 📌 **REBOTE DESDE SOPORTE - Detección temprana**
        if zona_rebote_probable and h_latest["RSI_7"] < 45:
            # Logging según zona
            if zona_soporte_critica:
                trend += f" 🚨 ZONA CRÍTICA: Soporte en ${support_level:.2f} (distancia {dist_to_support_pct:.2f}%)"
                reason += f" ⚠️ ALTO riesgo de rebote - precio a solo {dist_to_support_pct:.2f}% del soporte."
            elif zona_soporte_cercana:
                trend += f" ⚠️ Cerca de soporte en ${support_level:.2f} (distancia {dist_to_support_pct:.2f}%)"
                reason += f" Precio aproximándose al soporte - precaución."
            else:
                trend += f" 👀 Zona de rebote probable en ${support_level:.2f} (distancia {dist_to_support_pct:.2f}%)"
                reason += f" Precio en zona de posible rebote."

            # ✅ **REBOTE CONFIRMADO - Fuerte** (3 velas subiendo HTF)
            rebote_confirmado_fuerte = (
                len(historical_data) >= 3 and
                historical_data["Close"].iloc[-3] < historical_data["Close"].iloc[-2] < h_latest["Close"]
                and h_latest["MACD_Histogram"] > 0
                and h_latest["RSI_7"] > h_prev["RSI_7"]
                and h_latest["Volume"] > h_volume_mean * 1.2
            )

            # ✅ **REBOTE TEMPRANO - Alcista** (señal anticipada)
            rebote_temprano = (
                zona_soporte_critica and  # Muy cerca del soporte
                h_latest["RSI_7"] < 35 and  # Sobreventa
                l_latest["Close"] > l_prev["Close"] and  # Vela alcista en LTF
                l_latest["MACD_Histogram"] > l_prev["MACD_Histogram"] and  # MACD mejorando
                l_latest["Volume"] > l_volume_mean * 0.8  # Volumen presente
            )

            if rebote_confirmado_fuerte:
                trend += f" [✔️ REBOTE CONFIRMADO FUERTE] 🎯 3 velas alcistas consecutivas desde soporte"
                reason += " MACD alcista + RSI rebotando + Volumen muy alto (>1.2x)."
                candidato_signal = "BUY"
                candidato_reason = "Rebote confirmado fuerte"
            elif rebote_temprano:
                trend += f" [⚡ REBOTE TEMPRANO] 🎯 Señal anticipada en soporte crítico"
                reason += f" RSI sobreventa ({h_latest['RSI_7']:.1f}) + vela alcista + MACD mejorando."
                candidato_signal = "BUY"
                candidato_reason = "Rebote temprano en soporte crítico"

        # 📌 **REVERSIÓN EN RESISTENCIA**
        elif zona_resistencia_critica and latest_data["RSI_7"] > 60:
            if zona_resistencia_critica:
                trend += f" 🚨 ZONA CRÍTICA: Resistencia en ${resistance_level:.2f} (distancia {dist_to_resistance_pct:.2f}%)"
                reason += f" ⚠️ ALTO riesgo de rechazo - precio a solo {dist_to_resistance_pct:.2f}% de resistencia."
            else:
                trend += f" ⚠️ Cerca de resistencia en ${resistance_level:.2f} (distancia {dist_to_resistance_pct:.2f}%)"
                reason += f" Precio aproximándose a resistencia."

            # ✅ **Confirmación de reversión bajista**
            if (
                historical_data["Close"].iloc[-3] > historical_data["Close"].iloc[-2] > latest_data["Close"]
                and latest_data["MACD_Histogram"] < 0
                and latest_data["RSI_7"] < previous_data["RSI_7"]
                and latest_data["Volume"] > historical_data["Volume"].mean()
            ):
                trend += f" [✔️ REVERSIÓN CONFIRMADA] 📉 Precio rechazado en resistencia con fuerza"
                reason += " Confirmación con MACD negativo, RSI bajando y volumen alto."
                candidato_signal = "SELL"
                candidato_reason = "Reversión confirmada en resistencia"

        # Asegurar que trend_confirmed y trend siempre tengan valores
        # Asegurar que trend_confirmed y trend siempre tengan valores
        trend_confirmed = trend_confirmed if trend_confirmed else "[🔍] Tendencia no confirmada"
        trend = trend if trend else "[🔍] Sin tendencia clara"

        ## 🔥 **DECISIÓN FINAL CON VALIDACIÓN MULTI-NIVEL**

        # 🎯 REGLA 1: Tendencia bajista confirmada
        if "Tendencia bajista confirmada" in trend_confirmed:

            # 🔍 Detectar confirmación de piso: 3 velas consecutivas subiendo
            tres_velas_subiendo = False
            if len(historical_data) >= 3:
                vela_1 = historical_data.iloc[-3]["Close"]
                vela_2 = historical_data.iloc[-2]["Close"]
                vela_3 = historical_data.iloc[-1]["Close"]
                tres_velas_subiendo = (vela_1 < vela_2 < vela_3)

            # 🔧 NUEVO: DRENADO / CONTINUACIÓN BAJISTA (captura pullbacks débiles en tendencia)
            # Si la HTF confirma bajista y el ADX indica tendencia fuerte, cada pullback rechazado es SELL
            try:
                pullback_rechazado = (
                    h_latest["EMA_20"] < h_latest["EMA_50"] and
                    h_latest.get("ADX", 0) > 25 and
                    l_latest["Close"] < l_prev["Close"] and
                    l_latest["High"] < l_prev["High"] and
                    l_latest.get("RSI_7", 0) > 30
                )
            except Exception:
                pullback_rechazado = False

            if pullback_rechazado:
                candidato_signal = "SELL"
                candidato_reason = "Continuación bajista (drenado)"
                reason += " 📉 Continuación bajista limpia (drenado): estructura descendente + ADX alto."
                # Priorizar continuación bajista; calcular score inmediatamente
                confianza = 0
                detalles = []

                # Calcular score para SELL
                if latest_data["EMA_20"] < latest_data["EMA_50"]:
                    confianza += 2
                    detalles.append("EMA bajista")
                if 30 < latest_data["RSI_7"] < 70:
                    confianza += 2
                    detalles.append("RSI OK")
                if latest_data["MACD_Histogram"] < 0:
                    confianza += 1
                    detalles.append("MACD-")
                if h_latest.get("ADX", 0) > 25:
                    confianza += 2
                    detalles.append("ADX alto (trending)")
                if dist_to_support_pct > 2.0:
                    confianza += 1
                    detalles.append("Lejos soporte")

                # Aplicar threshold ADX ESCALONADO por score (ANTICIPACIÓN TEMPRANA)
                adx_value = float(h_latest.get("ADX", 0))
                if confianza >= 7:      # 7-8/8: Señal casi perfecta
                    adx_threshold = 12  # Ultra agresivo - captura inicio movimientos
                elif confianza >= 6:    # 6/8: Señal fuerte
                    adx_threshold = 15  # Balance (actual)
                elif confianza >= 5:    # 5/8: Señal media
                    adx_threshold = 18  # Intermedio
                else:                    # 4/8: Señal baja
                    adx_threshold = 20  # Conservador

                if confianza >= 4 and adx_value >= adx_threshold:
                    signal = "SELL ❌"
                    reason += f" ({confianza}/8 pts: {', '.join(detalles)})"
                else:
                    signal = "HOLD ⚠️"
                    if confianza < 4:
                        reason = f"⚠️ SELL bloqueado: Confianza insuficiente ({confianza}/8 pts, mínimo 4/8). " + reason
                    else:
                        reason = f"🚫 ADX bajo ({adx_value:.1f} < {adx_threshold}) para SELL (score {confianza}/8). " + reason

                return {
                    "trend": f"{trend_confirmed} | {trend}",
                    "reason": reason,
                    "signal": signal,
                    "support_price": float(support_level),
                    "market_bias": "SELL",
                    "market_regime": market_regime,
                    "confianza_score": confianza
                }

            # ✅ ESCENARIO ÓPTIMO: Rebote confirmado en soporte con todas las validaciones
            if ("REBOTE CONFIRMADO" in trend and
                latest_data["RSI_7"] < 40 and
                latest_data["MACD_Histogram"] > previous_data["MACD_Histogram"] and
                latest_data["Volume"] > historical_data["Volume"].mean() * 1.3):
                candidato_signal = "BUY"
                candidato_reason = "Rebote confirmado óptimo"
                reason += " 🚀 REBOTE CONFIRMADO en soporte con validación multi-nivel: RSI sobreventa + MACD alcista + Volumen alto."

            # ✅ ESCENARIO AGRESIVO: RSI cerca de sobreventa + MACD alcista + Volumen confirmado
            elif (latest_data["RSI"] < 38 and
                  latest_data["MACD"] > latest_data["MACD_Signal"] and
                  latest_data["MACD_Histogram"] > previous_data["MACD_Histogram"] and
                  latest_data["Volume"] > historical_data["Volume"].mean() * 1.3):
                candidato_signal = "BUY"
                candidato_reason = "Entrada agresiva RSI <38"
                reason += " 🎯 Entrada agresiva: RSI <38 con MACD cruzando alcista + Volumen confirmado (>1.3x promedio)."
            # ✅ ESCENARIO PISO CONFIRMADO: 3 velas subiendo + RSI recuperando + Volumen
            elif (tres_velas_subiendo and
                  latest_data["RSI"] < 40 and latest_data["RSI"] > previous_data["RSI"] and
                  latest_data["MACD_Histogram"] > 0 and
                  latest_data["Volume"] > historical_data["Volume"].mean() * 1.0):
                candidato_signal = "BUY"
                candidato_reason = "Piso confirmado 3 velas"
                reason += " 📊 Confirmación de piso: 3 velas consecutivas subiendo + RSI recuperando + Volumen alto."

            # ⚠️ HOLD: Microtendencia alcista sin confirmación suficiente
            elif "Microtendencia alcista" in trend:
                signal = "HOLD ⚠️"
                reason += " ⚠️ Microtendencia alcista detectada en tendencia bajista, pero SIN confirmación suficiente. Esperando volumen >1.3x o RSI <35."

            elif candidato_signal is None:
                candidato_signal = "SELL"
                candidato_reason = "Tendencia bajista sin reversión"
                reason += " 🔻 Tendencia bajista confirmada sin señales de reversión validadas."

        # 🎯 REGLA 2: Tendencia alcista confirmada
        elif "Tendencia alcista confirmada" in trend_confirmed:
            # Solo permitir SELL si hay REVERSIÓN CONFIRMADA en resistencia con múltiples validaciones
            cerca_resistencia = abs(current_price - resistance_level) / resistance_level <= 0.005  # 0.5% de resistencia

            if ("REVERSIÓN CONFIRMADA" in trend and
                cerca_resistencia and  # NUEVO: Debe estar cerca de resistencia
                latest_data["RSI_7"] > 55 and  # RSI debe estar alto (sobrecompra)
                latest_data["MACD_Histogram"] < previous_data["MACD_Histogram"] and  # MACD girando bajista
                latest_data["Volume"] > historical_data["Volume"].mean() * 1.2):  # NUEVO: Volumen más alto (1.2x)
                candidato_signal = "SELL"
                candidato_reason = "Reversión en resistencia"
                reason += " 📉 REVERSIÓN CONFIRMADA en resistencia con validación multi-nivel: Cerca resistencia + RSI sobrecompra + MACD bajista + Volumen muy alto."
            # Si solo hay microtendencia bajista SIN confirmación de reversión → HOLD
            elif "Microtendencia bajista" in trend:
                signal = "HOLD ⚠️"
                reason += " ⚠️ Microtendencia bajista detectada en tendencia alcista, pero SIN confirmación de reversión. Esperando validación."
            elif candidato_signal is None:
                candidato_signal = "BUY"
                candidato_reason = "Tendencia alcista confirmada"
                reason += " 📈 Tendencia alcista confirmada con momentum sostenido."

        # 🎯 REGLA 3: Sin tendencia confirmada - operar microtendencias con validación por niveles
        elif "microtendencia alcista" in trend.lower() and "impulso alcista fuerte" in trend.lower():
            candidato_signal = "BUY"
            candidato_reason = "Microtendencia alcista fuerte"

        elif "microtendencia bajista" in trend.lower() and "impulso bajista fuerte" in trend.lower():
            candidato_signal = "SELL"
            candidato_reason = "Microtendencia bajista fuerte"

        # 🎯 CÁLCULO DE SCORE UNIFICADO
        # Si tenemos un candidato (BUY o SELL), calcular score antes de generar señal
        if candidato_signal in ["BUY", "SELL"]:
            confianza = 0
            detalles = []

            if candidato_signal == "BUY":
                # 📊 Sistema de puntos de confianza para BUY
                # +2 puntos: Contexto alcista general
                if latest_data["EMA_20"] > latest_data["EMA_50"]:
                    confianza += 2
                    detalles.append("EMA alcista")

                # +2 puntos: RSI en zona óptima (30-65)
                if 30 < latest_data["RSI_7"] < 65:
                    confianza += 2
                    detalles.append("RSI óptimo")

                # +1 punto: MACD alcista
                if latest_data["MACD_Histogram"] > 0:
                    confianza += 1
                    detalles.append("MACD+")

                # +2 puntos: Volumen AVANZADO (OBV + Volume_Ratio)
                if latest_data.get("OBV_Trend", 0) == 1 and latest_data.get("Volume_Ratio", 0) > 1.1:
                    confianza += 2
                    detalles.append("Vol fuerte + OBV alcista")
                elif latest_data.get("Volume_Ratio", 0) > 0.8:
                    confianza += 1
                    detalles.append("Vol OK")

                # +1 punto BONUS: Régimen de mercado favorable (TRENDING)
                if latest_data.get("Market_Regime", "CHOPPY") == "TRENDING" and latest_data.get("ADX", 0) > 25:
                    confianza += 1
                    detalles.append("TRENDING confirmado")
                elif latest_data.get("Market_Regime", "CHOPPY") in ["RANGING", "CHOPPY"]:
                    confianza -= 1  # Penalización en mercado lateral o sin tendencia
                    regime = latest_data.get("Market_Regime", "CHOPPY")
                    detalles.append(f"⚠️ {regime}")

                # 🚫 SOPORTE ROTO: Penalización fuerte para BUY si el precio está bajo mínimos 75H
                if soporte_roto:
                    confianza -= 4
                    detalles.append(f"🚫 SOPORTE ROTO ({dist_to_support_pct:.2f}% bajo soporte)")

                # 🚫 CONTRA-TENDENCIA MACRO: Penalizar BUY si tendencia HTF es bajista fuerte
                if "Tendencia bajista confirmada" in trend_confirmed:
                    _htf_adx_buy = float(h_latest.get("ADX", 0))
                    if _htf_adx_buy > 25:
                        confianza -= 6
                        detalles.append(f"🚫 CONTRA MACRO (ADX {_htf_adx_buy:.1f})")

            elif candidato_signal == "SELL":
                # 📉 Sistema de puntos de confianza para SELL
                # +2 puntos: Contexto bajista general
                if latest_data["EMA_20"] < latest_data["EMA_50"]:
                    confianza += 2
                    detalles.append("EMA bajista")

                # +2 puntos: RSI sin sobreventa (>30) pero no muy alto
                if 30 < latest_data["RSI_7"] < 70:
                    confianza += 2
                    detalles.append("RSI OK")
                elif latest_data["RSI_7"] <= 30:
                    confianza -= 1  # Penalización moderada por sobreventa
                    detalles.append("RSI bajo!")

                # +1 punto: MACD bajista
                if latest_data["MACD_Histogram"] < 0:
                    confianza += 1
                    detalles.append("MACD-")

                # +2 puntos: Volumen AVANZADO (OBV + Volume_Ratio)
                if latest_data.get("OBV_Trend", 0) == -1 and latest_data.get("Volume_Ratio", 0) > 1.1:
                    confianza += 2
                    detalles.append("Vol fuerte + OBV bajista")
                elif latest_data.get("Volume_Ratio", 0) > 0.8:
                    confianza += 1
                    detalles.append("Vol OK")

                # Evaluación de cercanía al soporte (ENDURECIDO)
                if dist_to_support_pct <= 1.0:  # ≤1.0% - ZONA CRÍTICA
                    confianza -= 3  # Penalización muy fuerte
                    detalles.append(f"⚠️⚠️ CRÍTICO: {dist_to_support_pct:.2f}% soporte!")
                elif zona_soporte_cercana:  # 1.0-1.5% - Cerca
                    confianza -= 1  # Penalización moderada
                    detalles.append(f"⚠️ Cerca soporte ({dist_to_support_pct:.2f}%)")
                elif not zona_rebote_probable:  # >2% - Lejos
                    confianza += 1
                    detalles.append("Lejos soporte")

                # +1 punto BONUS: Régimen de mercado favorable (TRENDING)
                if latest_data.get("Market_Regime", "CHOPPY") == "TRENDING" and latest_data.get("ADX", 0) > 25:
                    confianza += 1
                    detalles.append("TRENDING confirmado")
                elif latest_data.get("Market_Regime", "CHOPPY") in ["RANGING", "CHOPPY"]:
                    confianza -= 1  # Penalización en mercado lateral o sin tendencia
                    regime = latest_data.get("Market_Regime", "CHOPPY")
                    detalles.append(f"⚠️ {regime}")

                # 🚫 CONTRA-TENDENCIA MACRO: Penalizar SELL si tendencia HTF es alcista fuerte
                if "Tendencia alcista confirmada" in trend_confirmed:
                    _htf_adx_sell = float(h_latest.get("ADX", 0))
                    if _htf_adx_sell > 25:
                        confianza -= 6
                        detalles.append(f"🚫 CONTRA MACRO (ADX {_htf_adx_sell:.1f})")

            # 🛡️ FILTRO ADX INTEGRADO: Aplicar threshold ESCALONADO por score (ANTICIPACIÓN TEMPRANA)
            try:
                adx_value = float(h_latest.get("ADX", 0))
                # ADX threshold escalonado: Score alto = ADX bajo permitido (anticipación)
                if confianza >= 7:      # 7-8/8: Señal casi perfecta
                    adx_threshold = 12  # Ultra agresivo - captura inicio movimientos
                elif confianza >= 6:    # 6/8: Señal fuerte
                    adx_threshold = 15  # Balance (actual)
                elif confianza >= 5:    # 5/8: Señal media
                    adx_threshold = 18  # Intermedio
                else:                    # 4/8: Señal baja
                    adx_threshold = 20  # Conservador

                if adx_value < adx_threshold:
                    # ADX insuficiente: rechazar señal
                    signal = "HOLD ⚠️"
                    reason = f"🚫 ADX demasiado bajo ({adx_value:.1f} < {adx_threshold}) para {candidato_signal} confiable (score: {confianza}/8). Mercado choppy sin tendencia clara. " + reason
                    print(f"[FILTRO ADX] {candidato_signal} rechazado: ADX={adx_value:.1f} < {adx_threshold} (confianza={confianza}/8)")
                    confianza_score = confianza  # Guardar score para retorno
                elif confianza >= 4:
                    # Score suficiente + ADX OK: generar señal
                    signal = f"{candidato_signal} {'✅' if candidato_signal == 'BUY' else '❌'}"
                    reason += f" {candidato_reason}: Score {confianza}/8 ({', '.join(detalles)}). ADX {adx_value:.1f} >= {adx_threshold}."
                    confianza_score = confianza
                    if confianza >= 6 and adx_threshold == 15:
                        print(f"[ADX OVERRIDE] ✅ {candidato_signal} permitido: Score alto ({confianza}/8) + ADX {adx_value:.1f} >= {adx_threshold}")
                else:
                    # Score insuficiente: rechazar señal
                    signal = "HOLD ⚠️"
                    reason = f"⚠️ {candidato_signal} bloqueado: Confianza insuficiente ({confianza}/8 pts, mínimo 4/8 = 50%). " + reason
                    print(f"[FILTRO SCORE] {candidato_signal} rechazado: Score={confianza}/8 < 4 (mínimo requerido)")
                    confianza_score = confianza
            except Exception as e:
                print(f"[ERROR FILTRO ADX] {e}")
                # Fallback: solo aplicar threshold de score
                if confianza >= 4:
                    signal = f"{candidato_signal} {'✅' if candidato_signal == 'BUY' else '❌'}"
                    reason += f" {candidato_reason}: Score {confianza}/8 ({', '.join(detalles)})."
                else:
                    signal = "HOLD ⚠️"
                    reason = f"⚠️ {candidato_signal} bloqueado: Confianza insuficiente ({confianza}/8 pts). " + reason
                confianza_score = confianza

        else:
            signal = "HOLD ⚠️"
            reason += " ⏸️ No hay señales claras con suficiente validación para operar."
            confianza_score = 0

        # Determinar market_bias para que la capa de decisión lo utilice
        market_bias = None
        try:
            if "Tendencia alcista confirmada" in trend_confirmed:
                market_bias = "BUY"
            elif "Tendencia bajista confirmada" in trend_confirmed:
                market_bias = "SELL"
        except Exception:
            market_bias = None

        # ═══════════════════════════════════════════════════════════
        # 🚨 FILTRO DE EXTENSIÓN EXTREMA
        # Detecta cuando el precio se ha alejado demasiado de la EMA20
        # en tendencia alcista → arma bias EXTENSION_ALCISTA y baja BUY a HOLD
        # ═══════════════════════════════════════════════════════════
        try:
            if signal in ("BUY ✅", "BUY 🟢") or market_bias == "BUY":
                _h = historical_data.iloc[-1] if historical_data is not None and len(historical_data) > 0 else None
                _h_prev = historical_data.iloc[-2] if historical_data is not None and len(historical_data) > 1 else None
                if _h is not None:
                    _ema20_h  = float(_h.get("EMA_20", 0))
                    _close_h  = float(_h.get("Close", 0))
                    _rsi_h    = float(_h.get("RSI", 50))
                    _macd_h   = float(_h.get("MACD_Histogram", 0))
                    _macd_prev = float(_h_prev.get("MACD_Histogram", 0)) if _h_prev is not None else _macd_h
                    _ext_pct  = ((_close_h - _ema20_h) / _ema20_h * 100) if _ema20_h > 0 else 0

                    # Condición de extensión extrema:
                    # precio > 3% sobre EMA20 HTF  +  RSI alto (>68)  +  MACD girando a la baja
                    _extension_extrema = (
                        _ext_pct > 3.0
                        and _rsi_h > 68
                        and _macd_h < _macd_prev  # MACD debilitándose
                    )
                    if _extension_extrema:
                        market_bias = "EXTENSION_ALCISTA"
                        _giro_confirmado = _macd_h < 0 and _macd_h < _macd_prev
                        if _giro_confirmado:
                            # Giro real confirmado en HTF → emitir SELL directamente
                            signal = "SELL ❌"
                            reason = (
                                f"🔻 EXTENSIÓN EXTREMA + GIRO CONFIRMADO: precio +{_ext_pct:.1f}% sobre EMA20 HTF "
                                f"(RSI {_rsi_h:.1f}), MACD_H giró negativo ({_macd_h:.4f} < {_macd_prev:.4f}). "
                                f"Señal SELL generada. | "
                            ) + reason
                            print(f"[EXTENSION→SELL] ✅ Giro confirmado: +{_ext_pct:.1f}% EMA20, MACD_H={_macd_h:.4f}<{_macd_prev:.4f}, RSI={_rsi_h:.1f}")
                        elif signal in ("BUY ✅", "BUY 🟢"):
                            # Extensión detectada pero sin giro aún → bloquear BUY, esperar
                            signal = "HOLD ⚠️"
                            reason = (
                                f"🚨 EXTENSIÓN EXTREMA: precio +{_ext_pct:.1f}% sobre EMA20 HTF "
                                f"(RSI {_rsi_h:.1f}, MACD aún positivo). BUY bloqueado. "
                                f"Esperando giro para SELL. | "
                            ) + reason
                            print(f"[EXTENSION] ⏳ Extensión detectada, giro no confirmado aún: +{_ext_pct:.1f}%, MACD_H={_macd_h:.4f} (prev={_macd_prev:.4f})")
                        else:
                            print(f"[EXTENSION] ⚠️ Extensión activa: +{_ext_pct:.1f}% EMA20, RSI={_rsi_h:.1f}, MACD_H={_macd_h:.4f}")
        except Exception as e:
            print(f"[ERROR FILTRO EXTENSION] {e}")

        # Extraer market_regime
        market_regime = None
        try:
            if hasattr(data, 'iloc') and len(data) > 0:
                latest_data = data.iloc[-1]
                market_regime = latest_data.get("Market_Regime", "CHOPPY")
        except Exception:
            market_regime = "CHOPPY"

        # 🚫 FILTRO: Evitar BUY con RSI > 90 (sobrecompra extrema) o RSI < 10 (sobreventa extrema sin rebote confirmado)
        try:
            if signal == "BUY ✅" and hasattr(data, 'iloc') and len(data) > 0:
                latest_data = data.iloc[-1]
                rsi_value = float(latest_data.get("RSI", 50))
                if rsi_value > 90:
                    original_signal = signal
                    signal = "HOLD ⚠️"
                    reason = f"🚫 REJECT BUY: RSI sobrecomprado extremo ({rsi_value:.1f} > 90). Evitando entrada en pico de impulso. | " + reason
                    print(f"[FILTRO RSI] BUY rechazado por RSI={rsi_value:.1f} > 90 (sobrecompra extrema)")
                elif rsi_value < 10:
                    original_signal = signal
                    signal = "HOLD ⚠️"
                    reason = f"🚫 REJECT BUY: RSI sobrevendido extremo ({rsi_value:.1f} < 10). Esperando rebote confirmado. | " + reason
                    print(f"[FILTRO RSI] BUY rechazado por RSI={rsi_value:.1f} < 10 (sobreventa extrema)")
        except Exception as e:
            print(f"[ERROR FILTRO RSI] {e}")
            pass  # Si falla, continuar con signal original

        # 🚫 BLOQUEO DURO: NO SELL en zona de rebote (dinámico por cycle_context)
        # Default: 2.0%. Post-halving: 5.0% (configurable en cycle_context.json)
        # Excepción: si ADX > 28 y score >= 5, el precio está ROMPIENDO el soporte, no rebotando
        _bounce_zone_pct = 2.0  # default
        try:
            cycle_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cycle_context.json")
            if os.path.exists(cycle_path):
                with open(cycle_path, "r") as f:
                    _cyctx = json.load(f)
                _bounce_zone_pct = float(_cyctx.get("bounce_zone_pct", 2.0))
        except Exception:
            pass
        try:
            if signal == "SELL ❌":
                dist_support = float(dist_to_support_pct if 'dist_to_support_pct' in locals() else 999)
                if dist_support <= _bounce_zone_pct:
                    # Comprobar si la tendencia bajista es suficientemente fuerte para ignorar el soporte
                    _override_adx = float(historical_data.iloc[-1].get("ADX", 0)) if historical_data is not None and not historical_data.empty else 0
                    if _override_adx > 28 and confianza_score >= 5:
                        print(f"[ZONA REBOTE OVERRIDE] ✅ SELL permitido: precio a {dist_support:.2f}% del soporte pero ADX {_override_adx:.1f} > 28 + Score {confianza_score}/8 — ruptura bajista")
                    else:
                        original_signal = signal
                        signal = "HOLD ⚠️"
                        support_price = float(support_level if 'support_level' in locals() else 0)
                        reason = f"🚫 REJECT SELL: En zona de rebote ({dist_support:.2f}% del soporte ${support_price:.2f}, umbral {_bounce_zone_pct}%). Alto riesgo de reversión alcista. | " + reason
                        print(f"[BLOQUEO ZONA REBOTE] SELL rechazado: precio a {dist_support:.2f}% de soporte (≤{_bounce_zone_pct}%)")
        except Exception as e:
            print(f"[ERROR FILTRO ZONA REBOTE] {e}")
            pass

        # Persistir en self para que EthBoy pueda leerlo
        # bias_age: si el bias cambió, reset a 0; si se mantiene, incrementar
        if market_bias is not None and market_bias == self.market_bias:
            self.bias_age += 1
        else:
            self.bias_age = 0
        self.market_bias = market_bias
        self.market_regime = market_regime

        return {
            "trend": f"{trend_confirmed} | {trend}",
            "reason": reason,
            "signal": signal,
            "support_price": float(support_level) if 'support_level' in locals() else None,
            "market_bias": market_bias,
            "market_regime": market_regime,
            "confianza_score": confianza_score
        }


    def calculate_dynamic_sl_tp(self, current_price, data, direction="BUY"):
        """
        Calcula SL/TP dinámicos basados en ATR (volatilidad adaptativa).

        Args:
            current_price: Precio actual
            data: Datos actuales con ATR_Pct
            direction: "BUY" o "SELL"

        Returns:
            dict con sl_pct y tp_pct dinámicos
        """
        atr_pct = data.get("ATR_Pct", 2.5)  # Default 2.5%

        # SL dinámico: 1.5x ATR (protección ajustada a volatilidad)
        sl_pct = min(max(atr_pct * 1.5, 1.5), 4.0)  # Entre 1.5% y 4%

        # TP dinámico: 2.5x ATR (objetivo proporcional)
        tp_pct = min(max(atr_pct * 2.5, 3.0), 8.0)  # Entre 3% y 8%

        # Ajuste según régimen de mercado
        market_regime = data.get("Market_Regime", "CHOPPY")
        if market_regime == "TRENDING":
            tp_pct *= 1.2  # +20% en tendencia fuerte
        elif market_regime == "RANGING":
            sl_pct *= 0.8  # SL más ajustado en lateral
            tp_pct *= 0.8  # TP más conservador

        return {
            "sl_pct": round(sl_pct / 100, 4),  # Convertir a decimal
            "tp_pct": round(tp_pct / 100, 4),
            "atr_pct": atr_pct
        }

    def get_sl_tp_levels(self, current_price, data, direction="BUY"):
        """
        Convierte los porcentajes dinámicos de calculate_dynamic_sl_tp() en
        precios ABSOLUTOS de Stop Loss y Take Profit, listos para
        CapitalOP.open_position() (que espera niveles de precio, no porcentajes).

        :param current_price: Precio de entrada estimado (para MARKET, el precio actual).
        :param data: Fila/serie de indicadores (necesita ATR_Pct, Market_Regime).
            Puede ser None; en ese caso se usan los valores por defecto.
        :param direction: "BUY" o "SELL".
        :return: dict con stop_loss y take_profit (precios absolutos redondeados)
            además de los sl_pct/tp_pct usados.
        """
        # calculate_dynamic_sl_tp usa .get(); un dict vacío da los defaults seguros.
        levels = self.calculate_dynamic_sl_tp(current_price, data if data is not None else {}, direction)
        tp_pct = levels["tp_pct"]

        # 🔹 STOP_LOSS flag (env): por defecto desactivado → no se adjunta stop loss.
        # Si STOP_LOSS=true, se fuerza un stop loss al 99% de distancia (STOP_LOSS_PCT).
        if STOP_LOSS:
            sl_pct = STOP_LOSS_PCT
            if direction.upper() == "BUY":
                stop_loss = round(current_price * (1 - sl_pct), 2)
            else:  # SELL
                stop_loss = round(current_price * (1 + sl_pct), 2)
        else:
            sl_pct = None
            stop_loss = None

        if direction.upper() == "BUY":
            take_profit = round(current_price * (1 + tp_pct), 2)
        else:  # SELL
            take_profit = round(current_price * (1 - tp_pct), 2)

        return {
            "stop_loss": stop_loss,
            "take_profit": round(take_profit, 2),
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
        }

    def calculate_position_size(self, balance, current_price, market_id="ETHUSD", min_size=0.001, max_size=0.15, open_positions=None):
        """
        Calcula tamaño de posición basado en balance real disponible.
        Soporta: FIXED_POSITION_SIZE (fijo), POSITION_SIZE_TIERS (dinámico por saldo), o cálculo automático.
        """
        # Obtener apalancamiento real desde la API de Capital.com
        try:
            leverage = self.capital_ops.get_leverage_for_market(market_id)
        except Exception:
            leverage = 20  # fallback
        print(f"[INFO] 🔧 Usando leverage {leverage}x para {market_id}")

        # 1) Sistema de tiers dinámico (si FIXED_POSITION_SIZE es None y hay tiers configurados)
        if FIXED_POSITION_SIZE is None and POSITION_SIZE_TIERS:
            # Seleccionar tiers según el apalancamiento real de la cuenta
            tiers_list = POSITION_SIZE_TIERS.get(leverage)
            if not tiers_list:
                # Fallback: usar el primer conjunto disponible
                tiers_list = next(iter(POSITION_SIZE_TIERS.values()))
            selected_size = None
            selected_tier_balance = 0
            for tier_balance, tier_size in sorted(tiers_list, key=lambda x: x[0]):
                margin_needed = (tier_size * current_price) / leverage
                if balance >= tier_balance and balance >= margin_needed:
                    selected_size = tier_size
                    selected_tier_balance = tier_balance

            if selected_size is not None:
                margin_req = (selected_size * current_price) / leverage
                print(f"[INFO] 🎯 TIER ${selected_tier_balance:.2f}+ → {selected_size} ETH (margen: ${margin_req:.2f} | balance: ${balance:.2f})")
                return selected_size
            else:
                print(f"[WARNING] ⚠️ Balance ${balance:.2f} no alcanza para ningún tier. Mín requerido: ${tiers_list[0][0]:.2f}")
                return 0

        # 2) Si se configuró un tamaño fijo en EthConfig, usarlo (pero validar margen)
        if FIXED_POSITION_SIZE is not None and FIXED_POSITION_SIZE > 0:
            fixed = float(FIXED_POSITION_SIZE)
            if fixed < min_size:
                print(f"[WARNING] FIXED_POSITION_SIZE ({fixed}) < min_size ({min_size}). Usando min_size en su lugar.")
                fixed = min_size
            margin_required_fixed = (fixed * current_price) / leverage
            if balance < margin_required_fixed:
                # Fallback: intentar con el máximo que el balance permita
                max_affordable = (balance * 0.90 * leverage) / current_price
                if max_affordable >= min_size:
                    fixed = max(min_size, max_affordable)
                    margin_required_fixed = (fixed * current_price) / leverage
                    print(f"[WARNING] ⚠️ FIXED_POSITION_SIZE no cabe (${balance:.2f}). Fallback a {fixed:.4f} ETH (margen: ${margin_required_fixed:.2f})")
                else:
                    print(f"[WARNING] ⚠️ Balance insuficiente (${balance:.2f}) incluso para min_size {min_size} ETH.")
                    return 0
            else:
                print(f"[INFO] 🔒 Usando FIXED_POSITION_SIZE = {fixed} ETH (margen: ${margin_required_fixed:.2f})")
            return fixed

        # Validar mínimo absoluto de Capital.com
        min_margin_for_min_size = (min_size * current_price) / leverage

        if balance < min_margin_for_min_size:
            print(f"[WARNING] ⚠️ Balance insuficiente (${balance:.2f}). Se requiere mínimo ${min_margin_for_min_size:.2f} para 0.001 ETH con {leverage}x leverage.")
            return 0

        # Calcular tamaño basado en el balance disponible (30% para mayor seguridad con múltiples posiciones)
        usable_balance = balance * 0.30
        max_affordable_size = (usable_balance * leverage) / current_price

        # Usar el mayor entre min_size y lo que podemos pagar
        position_size = max(min_size, max_affordable_size)

        # Aplicar tope por exposición máxima (`max_size` = % del balance -> por ejemplo 0.15 para 15%)
        try:
            max_by_cap = (balance * float(max_size)) / current_price
            if position_size > max_by_cap:
                print(f"[INFO] ⚖️ Aplicando tope de exposición: max_size={float(max_size):.2f} -> Ajustando {position_size:.6f} -> {max_by_cap:.6f} ETH")
                position_size = max_by_cap
            # Asegurar que no caiga por debajo del mínimo
            if position_size < min_size:
                print(f"[WARNING] ⚠️ Tamaño ajustado por tope es menor al mínimo. Usando min_size={min_size}")
                position_size = min_size
        except Exception:
            # En caso de error en el cálculo del tope, continuar con el tamaño calculado
            pass

        # Validar que no exceda balance
        margin_required = (position_size * current_price) / leverage

        print(f"[INFO] 💰 Balance: ${balance:.2f} | Usable (30%): ${usable_balance:.2f}")
        print(f"[INFO] 📊 Tamaño: {position_size:.6f} ETH (~${position_size * current_price:.2f} exposición)")
        print(f"[INFO] 💵 Margen requerido: ${margin_required:.2f} (leverage {leverage}x)")

        if margin_required > balance:
            print(f"[ERROR] ❌ Margen (${margin_required:.2f}) > Balance (${balance:.2f}) - reduciendo a mínimo viable")
            # Calcular el máximo size que podemos pagar
            max_payable_size = (balance * 0.90 * leverage) / current_price  # 90% del balance como último recurso
            if max_payable_size >= min_size:
                position_size = max_payable_size
                margin_required = (position_size * current_price) / leverage
                print(f"[INFO] ✅ Ajustado a: {position_size:.6f} ETH (margen: ${margin_required:.2f})")
            else:
                print(f"[ERROR] ❌ Imposible operar con balance actual")
                return 0

        return position_size



    def decide(self, current_price, data, balance, features, market_id, historical_data, open_positions=None):
        print(f"[DEBUG] Decidiendo para precio={current_price} y balance={balance}")

        # Validación inicial
        if current_price <= 0 or balance <= 0:
            return {"action": "hold", "size": 0, "reason": "Precio o balance inválido"}

        # 🌍 FILTRO MARKET CONTEXT: Leer market_context.json y bloquear operaciones contra breakout
        mctx_state = None
        mctx_bias = None
        mctx_adx = None
        try:
            mctx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_context.json")
            if os.path.exists(mctx_path):
                # TTL: ignorar si el archivo tiene más de 15 minutos
                _age = time.time() - os.path.getmtime(mctx_path)
                if _age < 900:
                    with open(mctx_path, "r") as f:
                        mctx = json.load(f)
                    mctx_state = mctx.get("state", "ranging")
                    mctx_bias = mctx.get("bias")
                    mctx_adx = mctx.get("adx")
                    bb_lower = mctx.get("bb_lower", 0)
                    bb_upper = mctx.get("bb_upper", 0)
                    ema200 = mctx.get("ema200", 0)
                    squeeze_pct = mctx.get("squeeze_pct", 100)
                    _adx_str = f"ADX {mctx_adx}" if mctx_adx else ""
                    _bias_str = f"Bias: {mctx_bias}" if mctx_bias else ""
                    print(f"[MCTX] 🌍 {mctx_state.upper()} | BB ${bb_lower}-${bb_upper} | EMA200 ${ema200} | {_adx_str} | Squeeze {squeeze_pct}% | {_bias_str}")
                else:
                    print(f"[MCTX] ⚠️ market_context.json expirado ({_age:.0f}s > 900s)")
        except Exception as e:
            print(f"[MCTX] ⚠️ No se pudo leer market_context.json: {e}")

        # � FILTRO CYCLE CONTEXT: Leer cycle_context.json para ajustar umbrales post-halving
        cycle_phase = None
        cycle_sell_min = 5          # default: score mínimo SELL = 5/8
        cycle_bounce_zone = 2.0     # default: zona de rebote 2%
        try:
            cycle_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cycle_context.json")
            if os.path.exists(cycle_path):
                with open(cycle_path, "r") as f:
                    cyctx = json.load(f)
                cycle_phase = cyctx.get("phase")
                cycle_sell_min = int(cyctx.get("sell_score_minimum", 5))
                cycle_bounce_zone = float(cyctx.get("bounce_zone_pct", 2.0))
                print(f"[CYCLE] 🔄 Fase: {cycle_phase} | SELL mínimo: {cycle_sell_min}/8 | Zona rebote: {cycle_bounce_zone}%")
        except Exception as e:
            print(f"[CYCLE] ⚠️ No se pudo leer cycle_context.json: {e}")

        # 📊 FILTRO EMA200 DAILY: Derivar EMA200 diaria desde datos HTF (HOUR)
        ema200d_bull = False
        try:
            if historical_data is not None and len(historical_data) >= 200:
                # Resamplear HOUR → DAILY usando el Close de cada día
                htf_close = historical_data[["Close"]].copy()
                htf_close.index = pd.to_datetime(htf_close.index, errors="coerce") if not isinstance(htf_close.index, pd.DatetimeIndex) else htf_close.index
                daily_close = htf_close["Close"].resample("1D").last().dropna()
                if len(daily_close) >= 200:
                    ema200d = daily_close.ewm(span=200, adjust=False).mean().iloc[-1]
                    latest_close = daily_close.iloc[-1]
                    ema200d_bull = latest_close > ema200d
                    _pct_above = ((latest_close - ema200d) / ema200d) * 100
                    print(f"[EMA200D] 📊 EMA200 DAILY: ${ema200d:.2f} | Precio: ${latest_close:.2f} | {'🟢 POR ENCIMA' if ema200d_bull else '🔴 POR DEBAJO'} ({_pct_above:+.2f}%)")
                else:
                    print(f"[EMA200D] ⚠️ Solo {len(daily_close)} velas diarias — insuficiente para EMA200D")
        except Exception as e:
            print(f"[EMA200D] ⚠️ No se pudo calcular EMA200 DAILY: {e}")

        # �📌 Obtener la información de tendencias y señal desde detect_trend()
        trend_analysis = self.detect_trend(historical_data, data)
        trend_detected = trend_analysis["trend"]
        reason_detected = trend_analysis["reason"]
        signal = trend_analysis["signal"]

        # 📌 NO forzar cambio de señales - permitir SELLs en tendencias bajistas aunque haya soporte
        # Los soportes se rompen en 40-50% de casos, especialmente en tendencias fuertes

        print(f"[INFO] 🔍 Análisis de tendencia: {trend_detected}")
        print(f"[INFO] 📋 Razón de la señal: {reason_detected}")
        print(f"[INFO] 🏁 Señal generada: {signal}")

        # 📌 Procesar las posiciones abiertas
        if open_positions and isinstance(open_positions, (tuple, list)) and len(open_positions) == 2:
            buy_positions, sell_positions = open_positions
        else:
            buy_positions, sell_positions = ([], [])

        num_buy_positions = sum(
            1 for p in buy_positions
            if isinstance(p, dict) and p.get("position", {}).get("direction", "").upper() == "BUY"
        )
        num_sell_positions = sum(
            1 for p in sell_positions
            if isinstance(p, dict) and p.get("position", {}).get("direction", "").upper() == "SELL"
        )

        # 📌 NOTA: Las validaciones de límites (BUY/SELL y TOTAL) se hacen en EthBoy.process_data()
        # ANTES de llamar a decide(). Aquí solo validamos cruces de posiciones.

        reason_decide = reason_detected

        # 🌍 FILTRO BREAKOUT + BIAS: No operar contra la dirección del mercado
        if mctx_state == "breakout_up" and signal == "SELL 📉":
            rej = f"[MCTX] ⛔ SELL bloqueado: breakout_up activo (no luchar contra el breakout alcista)"
            print(f"[REJECT] {rej}")
            return {"action": "hold", "size": 0, "reason": rej}
        if mctx_state == "breakout_down" and signal == "BUY 📈":
            rej = f"[MCTX] ⛔ BUY bloqueado: breakout_down activo (no luchar contra el breakout bajista)"
            print(f"[REJECT] {rej}")
            return {"action": "hold", "size": 0, "reason": rej}
        if mctx_state == "squeeze":
            print(f"[MCTX] ⚠️ Squeeze activo — esperando dirección del breakout")
        if mctx_state == "choppy":
            print(f"[MCTX] ⚠️ Mercado CHOPPY (ADX {mctx_adx}) — señales poco fiables")

        # 📌 Si la señal es HOLD, no se opera
        if signal == "HOLD ⚠️":
            print(f"[INFO] ⏳ Manteniendo posición: {reason_detected}")
            return {"action": "hold", "size": 0, "reason": reason_detected}

        # 📌 Calcular el tamaño de la posición con Regla del 1%
        position_size = self.calculate_position_size(balance, current_price, market_id=market_id, open_positions=open_positions)

        # Validar que el tamaño sea válido
        if position_size <= 0:
            return {
                "action": "hold",
                "size": 0,
                "reason": f"Balance insuficiente (${balance:.2f}) para abrir posición. {reason_decide}"
            }

        # � VALIDACIÓN DE CRUCE DE POSICIONES
        # Convertir formato de posiciones para el validador
        positions_dict = {
            "BUY": buy_positions,
            "SELL": sell_positions
        }

        # 📌 Ejecutar la orden según la señal final
        # Garantizar que latest_data esté siempre definido (puede no haberse asignado en rutas condicionales anteriores)
        latest_data = data.iloc[-1] if (data is not None and not data.empty) else None
        _trend_info = {
            "ADX": float(latest_data.get("ADX", 0) if latest_data is not None else 0),
            "strength": float(latest_data.get("ADX", 0) if latest_data is not None else 0) / 20.0
        }
        if signal == "BUY ✅":
            # 🚫 BLOQUEO POR SOPORTE ROTO: No comprar si precio bajo mínimo 75H
            _support_price = trend_analysis.get("support_price")
            if _support_price and current_price < _support_price:
                _dist_below = ((current_price - _support_price) / _support_price) * 100
                rej = f"🚫 REJECT BUY: Soporte roto (precio ${current_price:.2f} {_dist_below:.2f}% BAJO soporte ${_support_price:.2f}). Esperar reconfirmación sobre soporte."
                print(f"[REJECT] {rej}")
                return {"action": "hold", "size": 0, "reason": rej + " | " + reason_decide}

            # Validar que BUY esté por debajo de todas las SELL
            validation = PositionValidator.validate_new_position(
                current_price, "BUY", positions_dict, tolerance_pct=0.5, trend_info=_trend_info
            )

            if not validation["allowed"]:
                print(f"[BLOCK] 🚫 {validation['reason']}")
                # 🔹 AGREGAR CONTEO DE POSICIONES AL MENSAJE DE BLOQUEO
                total_positions = num_buy_positions + num_sell_positions
                full_reason = f"📊 Tengo {total_positions} posiciones (BUY={num_buy_positions}, SELL={num_sell_positions}). {validation['reason']}"
                return {
                    "action": "hold",
                    "size": 0,
                    "reason": full_reason
                }

            print(f"[TRADE] 🟢 Orden de COMPRA detectada. Ejecutando trade.")
            print(f"[VALID] ✅ {validation['reason']}")
            sl_tp = self.get_sl_tp_levels(current_price, latest_data, "BUY")
            _sl_str = f"${sl_tp['stop_loss']} ({sl_tp['sl_pct']*100:.2f}%)" if sl_tp['stop_loss'] is not None else "desactivado (STOP_LOSS=false)"
            print(f"[SL/TP] 🛡️ SL {_sl_str} | 🎯 TP ${sl_tp['take_profit']} ({sl_tp['tp_pct']*100:.2f}%)")
            return {
                "action": "BUY",
                "direction": "BUY",
                "size": position_size,
                "market_id": market_id,
                "stop_loss": sl_tp["stop_loss"],
                "take_profit": sl_tp["take_profit"],
                "reason": reason_decide
            }

        elif signal == "SELL ❌":
            # --- REFINAMIENTOS ANTI-REBOTE: Filtros más estrictos para evitar SELLs prematuros ---
            support_price = trend_analysis.get("support_price")
            market_bias = trend_analysis.get("market_bias")
            market_regime = trend_analysis.get("market_regime", "CHOPPY")
            confianza_score = trend_analysis.get("confianza_score", 0)

            # 📊 EMA200D PENALTY: Si precio > EMA200 DAILY, penalizar SELL con -2 puntos
            # Esta es la ÚNICA penalización de score — el cycle_context solo sube el umbral mínimo
            if ema200d_bull:
                original_score_ema = confianza_score
                confianza_score = max(0, confianza_score - 2)
                print(f"[EMA200D] 📊 SELL penalizado: precio encima de EMA200 DAILY → Score {original_score_ema}/8 → {confianza_score}/8 (-2 pts)")

            # 🔴 Bloquear SELL si score < umbral (dinámico por cycle_context)
            # Default: 5/8. Post-halving: 6/8 (configurable en cycle_context.json)
            # Ejemplo con EMA200D bull: score 8/8 → 6/8 → pasa (convicción perfecta)
            #                           score 7/8 → 5/8 → bloqueado (duda razonable)
            _sell_min = cycle_sell_min
            if confianza_score < _sell_min:
                rej = f"🚫 REJECT SELL: Score insuficiente ({confianza_score}/8 pts, mínimo {_sell_min}/8 = {_sell_min*100/8:.0f}%)"
                if cycle_phase:
                    rej += f" [Ciclo: {cycle_phase}]"
                if ema200d_bull:
                    rej += " [EMA200D: 🟢 bull, -2 pts aplicados]"
                print(f"[REJECT] {rej}")
                return {
                    "action": "hold",
                    "size": 0,
                    "reason": rej + " | " + reason_decide
                }

            # 🔴 Bloquear SELL en mercado LTF RANGING, EXCEPTO si HTF ADX > 25
            # (LTF RANGING dentro de HTF TRENDING = consolidación en tendencia bajista → SELL válido)
            if market_regime == "RANGING":
                try:
                    htf_adx = float(historical_data.iloc[-1].get("ADX", 0))
                except Exception:
                    htf_adx = 0
                if htf_adx > 25:
                    print(f"[RANGING OVERRIDE] ✅ SELL permitido pese a LTF RANGING: HTF ADX {htf_adx:.1f} > 25 — tendencia macro bajista domina")
                else:
                    rej = f"🚫 REJECT SELL: Mercado en RANGING y HTF ADX {htf_adx:.1f} <= 25 (sin tendencia clara)"
                    print(f"[REJECT] {rej}")
                    return {
                        "action": "hold",
                        "size": 0,
                        "reason": rej + " | " + reason_decide
                    }

            # 🔴 Bloquear SELL con RSI < 30 (sobreventa extrema, zona de rebote)
            # Excepción: si la tendencia bajista es fuerte (ADX > 28 + score >= 5) el RSI bajo
            # indica CONTINUACIÓN de la caída, no rebote inminente.
            try:
                rsi_ltf = float(features.get("RSI", 100))
                if rsi_ltf < 30:
                    try:
                        adx_rsi_check = float(historical_data.iloc[-1].get("ADX", 0))
                    except Exception:
                        adx_rsi_check = 0
                    if adx_rsi_check > 28 and confianza_score >= 5:
                        print(f"[RSI OVERRIDE] ✅ SELL permitido pese a RSI bajo ({rsi_ltf:.1f}): ADX {adx_rsi_check:.1f} > 28 + Score {confianza_score}/8 — caída bajista dominante")
                    else:
                        rej = f"🚫 REJECT SELL: RSI en sobreventa extrema ({rsi_ltf:.1f} < 30, zona de rebote)"
                        print(f"[REJECT] {rej}")
                        return {
                            "action": "hold",
                            "size": 0,
                            "reason": rej + " | " + reason_decide
                        }
            except Exception:
                pass

            # 1) Reject SELL if HTF bias is BUY
            if market_bias == "BUY":
                rej = f"🚫 REJECT SELL: HTF bias=BUY"
                print(f"[REJECT] {rej}")
                return {
                    "action": "hold",
                    "size": 0,
                    "reason": rej + " | " + reason_decide
                }

            # 2) If price is significantly above support, require strong confirmation (MACD<0, RSI<50, VolumeChange < V)
            try:
                macd_f = float(features.get("MACD", 0))
            except Exception:
                macd_f = 0
            try:
                rsi_f = float(features.get("RSI", 100))
            except Exception:
                rsi_f = 100
            try:
                vol_change = float(features.get("VolumeChange", 0))
            except Exception:
                vol_change = 0

            if support_price is not None and current_price > support_price * (1 + SUPPORT_TOLERANCE):
                full_confirmation = (macd_f < 0 and rsi_f < 50 and vol_change < VOLUME_NEG_THRESHOLD)

                # Override de momentum bajista temprano:
                # EMA cruzada bajista (EMA3 < EMA9) + ADX fuerte + score alto
                # Captura bajadas reales donde el MACD aún es ligeramente positivo pero claramente declinando
                momentum_override = False
                try:
                    ema3 = float(data.iloc[-1].get("EMA_3", 0) or 0)
                    ema6 = float(data.iloc[-1].get("EMA_6", 0) or 0)
                    ema9 = float(data.iloc[-1].get("EMA_9", 0) or 0)
                    adx_supp = float(historical_data.iloc[-1].get("ADX", 0))

                    # EMA cross bajista: preferir EMA3<EMA9; si EMA9 ausente usar EMA6;
                    # si ninguna disponible, el score 8/8 ya la evalúa → asumir True con score alto
                    if ema3 > 0 and ema9 > 0:
                        ema_bearish_cross = ema3 < ema9
                    elif ema3 > 0 and ema6 > 0:
                        ema_bearish_cross = ema3 < ema6
                    else:
                        # Sin datos de EMA en buffer: confiar en el score (ya incluye EMA cross)
                        ema_bearish_cross = confianza_score >= 7

                    momentum_override = (
                        confianza_score >= 6
                        and adx_supp >= 25
                        and ema_bearish_cross
                        and macd_f < 2.0   # MACD no explosivamente alcista (lag tolerable)
                        and rsi_f < 65     # RSI no en zona de sobrecompra
                    )
                    if momentum_override:
                        print(f"[MOMENTUM OVERRIDE] ✅ SELL por momentum bajista temprano: Score {confianza_score}/8, ADX {adx_supp:.1f}, EMA_cross={ema_bearish_cross}, MACD={macd_f:.3f}, RSI={rsi_f:.1f}")
                except Exception:
                    pass

                if not full_confirmation and not momentum_override:
                    rej = (f"REJECT SELL: price {current_price:.2f} > support {support_price:.2f}*(1+{SUPPORT_TOLERANCE}) "
                           f"and no strong confirmation (MACD={macd_f:.3f}, RSI={rsi_f:.1f}, VolChange={vol_change:.3f})")
                    print(f"[REJECT] {rej}")
                    return {
                        "action": "hold",
                        "size": 0,
                        "reason": rej + " | " + reason_decide
                    }

            # 3) Recent rally filter: if price rallied recently > RECENT_RALLY_PCT, require EMA_short < EMA_mid AND MACD < 0
            try:
                recent_window = int(RECENT_RALLY_WINDOW_MIN)
                if hasattr(data, 'shape') and len(data) >= 2:
                    recent_close_series = data["Close"].tail(recent_window)
                    if len(recent_close_series) > 0:
                        recent_min = recent_close_series.min()
                        recent_rally_pct = (current_price - recent_min) / recent_min if recent_min and recent_min > 0 else 0
                    else:
                        recent_rally_pct = 0
                else:
                    recent_rally_pct = 0
            except Exception:
                recent_rally_pct = 0

            if recent_rally_pct > RECENT_RALLY_PCT:
                # try to obtain EMA short/mid from latest ltf row
                try:
                    ema_short = float(data.iloc[-1].get("EMA_3", 0))
                    ema_mid = float(data.iloc[-1].get("EMA_9", 0))
                except Exception:
                    ema_short = None
                    ema_mid = None

                if not (ema_short is not None and ema_mid is not None and ema_short < ema_mid and macd_f < 0):
                    rej = (f"REJECT SELL: recent_rally={recent_rally_pct*100:.2f}% > {RECENT_RALLY_PCT*100:.2f}% "
                           f"and missing EMA_short<EMA_mid or MACD<0 (EMA3={ema_short}, EMA9={ema_mid}, MACD={macd_f:.3f})")
                    print(f"[REJECT] {rej}")
                    return {
                        "action": "hold",
                        "size": 0,
                        "reason": rej + " | " + reason_decide
                    }

            # 4) ADX filter on HTF: avoid SELLs in choppy markets (ADX ESCALONADO por score)
            try:
                adx_htf = float(historical_data.iloc[-1].get("ADX", 0))
                confianza_score = trend_analysis.get("confianza_score", 0)

                # ADX threshold ESCALONADO: Score alto = ADX bajo permitido (anticipación temprana)
                if confianza_score >= 7:      # 7-8/8: Señal casi perfecta
                    adx_threshold = 12  # Ultra agresivo - captura inicio movimientos
                elif confianza_score >= 6:    # 6/8: Señal fuerte
                    adx_threshold = 15  # Balance (actual)
                elif confianza_score >= 5:    # 5/8: Señal media
                    adx_threshold = 18  # Intermedio
                else:                          # 4/8: Señal baja
                    adx_threshold = 20  # Conservador (fallback a ADX_TREND_THRESHOLD)

                if adx_htf < adx_threshold:
                    rej = f"REJECT SELL: ADX_HTF {adx_htf:.1f} < {adx_threshold} (market not trending, score={confianza_score}/8)"
                    print(f"[REJECT] {rej}")
                    return {"action": "hold", "size": 0, "reason": rej + " | " + reason_decide}
                elif confianza_score >= 6:
                    print(f"[ADX OVERRIDE] ✅ SELL permitido: Score alto ({confianza_score}/8) + ADX {adx_htf:.1f} >= {adx_threshold}")
            except Exception:
                pass

            # Validar que SELL esté por encima de todas las BUY
            validation = PositionValidator.validate_new_position(
                current_price, "SELL", positions_dict, tolerance_pct=0.5, trend_info=_trend_info
            )

            if not validation["allowed"]:
                print(f"[BLOCK] 🚫 {validation['reason']}")
                # 🔹 AGREGAR CONTEO DE POSICIONES AL MENSAJE DE BLOQUEO
                total_positions = num_buy_positions + num_sell_positions
                full_reason = f"📊 Tengo {total_positions} posiciones (BUY={num_buy_positions}, SELL={num_sell_positions}). {validation['reason']}"
                return {
                    "action": "hold",
                    "size": 0,
                    "reason": full_reason
                }

            print(f"[TRADE] 🔴 Orden de VENTA detectada. Ejecutando trade.")
            print(f"[VALID] ✅ {validation['reason']}")
            sl_tp = self.get_sl_tp_levels(current_price, latest_data, "SELL")
            _sl_str = f"${sl_tp['stop_loss']} ({sl_tp['sl_pct']*100:.2f}%)" if sl_tp['stop_loss'] is not None else "desactivado (STOP_LOSS=false)"
            print(f"[SL/TP] 🛡️ SL {_sl_str} | 🎯 TP ${sl_tp['take_profit']} ({sl_tp['tp_pct']*100:.2f}%)")
            return {
                "action": "SELL",
                "direction": "SELL",
                "size": position_size,
                "market_id": market_id,
                "stop_loss": sl_tp["stop_loss"],
                "take_profit": sl_tp["take_profit"],
                "reason": reason_decide
            }

        print(f"[INFO] ⏳ No se cumple ninguna condición clara de trading.")
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
        minimum_profit_threshold = 0.01  # Se requiere al menos $0.03 de ganancia para considerar cierre
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
                msg = f"ganancia negativa ({upl * 100:.2f}%)."
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