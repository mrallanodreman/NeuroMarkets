"""
TimingHelper.py - Herramienta para timing preciso de entrada/salida usando datos 1M
Autor: Sistema de Trading EthBoy
Fecha: 29 de diciembre de 2025

Propósito:
- Usar historical_data (HOUR) para decisiones estratégicas
- Usar data (1M) SOLO para timing preciso de ejecución
- Evitar calcular indicadores largos en timeframe corto
"""

import pandas as pd
import numpy as np


class TimingOptimizer:
    """
    Optimiza el timing de entrada/salida usando datos de 1 minuto.
    NO calcula indicadores de largo plazo, solo momentum inmediato.
    """

    def __init__(self):
        self.min_data_points = 10  # Mínimo 10 minutos para análisis

    def get_immediate_momentum(self, data_1m):
        """
        Calcula momentum inmediato usando solo datos recientes de 1M.

        Args:
            data_1m: DataFrame con datos de 1 minuto (últimas 2 horas)

        Returns:
            dict con métricas de timing inmediato
        """
        if len(data_1m) < self.min_data_points:
            return {
                "momentum": "NEUTRAL",
                "strength": 0,
                "ready": False,
                "reason": "Datos insuficientes"
            }

        # Usar solo últimos 30 minutos
        recent = data_1m.iloc[-30:]

        # 1️⃣ Momentum de precio (últimos 10 minutos)
        price_change_10m = (recent["Close"].iloc[-1] - recent["Close"].iloc[-10]) / recent["Close"].iloc[-10]

        # 2️⃣ Aceleración (cambio del cambio)
        price_change_5m = (recent["Close"].iloc[-1] - recent["Close"].iloc[-5]) / recent["Close"].iloc[-5]
        acceleration = price_change_5m - price_change_10m

        # 3️⃣ Volumen relativo (últimos 5 min vs promedio 30 min)
        volume_recent = recent["Volume"].iloc[-5:].mean()
        volume_avg = recent["Volume"].mean()
        volume_ratio = volume_recent / volume_avg if volume_avg > 0 else 1

        # 4️⃣ Volatilidad (rango alto-bajo reciente)
        volatility = (recent["High"].max() - recent["Low"].min()) / recent["Close"].iloc[-1]

        # Determinar momentum con umbrales ajustados para BTC
        # BTC puede moverse 0.05-0.1% en 10 minutos sin ser una señal fuerte
        # Usamos combinación de precio + volumen para confirmar
        if price_change_10m > 0.0005 and volume_ratio > 1.1:  # 0.05% con volumen
            if acceleration > 0 or volume_ratio > 1.3:  # Confirmación adicional
                momentum = "BULLISH"
                strength = min(abs(price_change_10m) * volume_ratio * 100, 100)
            else:
                momentum = "NEUTRAL"
                strength = 0
        elif price_change_10m < -0.0005 and volume_ratio > 1.1:  # -0.05% con volumen
            if acceleration < 0 or volume_ratio > 1.3:  # Confirmación adicional
                momentum = "BEARISH"
                strength = min(abs(price_change_10m) * volume_ratio * 100, 100)
            else:
                momentum = "NEUTRAL"
                strength = 0
        else:
            momentum = "NEUTRAL"
            strength = 0

        return {
            "momentum": momentum,
            "strength": strength,
            "price_change_10m": price_change_10m * 100,  # En %
            "acceleration": acceleration * 100,
            "volume_ratio": volume_ratio,
            "volatility": volatility * 100,
            "ready": strength > 0.1,  # Umbral bajo: si hay momentum detectado (>0.1%), está listo
            "reason": f"Momentum {momentum.lower()} con fuerza {strength:.1f}%"
        }

    def should_enter_now(self, signal_from_hour, data_1m, buy_positions=None):
        """
        Decide si ejecutar la señal AHORA basado en timing de 1M.

        Args:
            signal_from_hour: Señal estratégica desde HOUR (BUY/SELL/HOLD)
            data_1m: Datos de 1 minuto para timing

        Returns:
            dict con decisión de ejecución
        """
        if signal_from_hour == "HOLD ⚠️":
            return {
                "execute": False,
                "reason": "Sin señal estratégica desde HOUR"
            }

        timing = self.get_immediate_momentum(data_1m)

        # 🔍 DEBUG: Mostrar análisis de momentum
        print(f"[DEBUG] 📊 Análisis de Momentum 1M:")
        print(f"[DEBUG]    - Momentum: {timing['momentum']}")
        print(f"[DEBUG]    - Strength: {timing['strength']:.2f}%")
        print(f"[DEBUG]    - Ready: {timing['ready']}")
        print(f"[DEBUG]    - Price change 10m: {timing['price_change_10m']:.4f}%")
        print(f"[DEBUG]    - Volume ratio: {timing['volume_ratio']:.2f}")

        # Solo ejecutar BUY si momentum 1M también es alcista
        # Soportar ambos formatos: "BUY ✅" y "BUY 🟢"
        if signal_from_hour in ["BUY ✅", "BUY 🟢"]:
            # No se bloquea nunca el BUY por posiciones SELL aquí (la lógica de bloqueo por SELL se maneja en otro lado)
            if timing["momentum"] == "BULLISH" and timing["ready"]:
                return {
                    "execute": True,
                    "confidence": timing["strength"],
                    "reason": f"BUY confirmado con momentum 1M alcista ({timing['strength']:.1f}%)"
                }
            elif timing["momentum"] == "BEARISH" and timing["strength"] > 0.5:
                return {
                    "execute": False,
                    "reason": f"BUY RETRASADO: Momentum 1M bajista fuerte ({timing['strength']:.2f}%), esperar mejor entrada"
                }
            else:
                # NO ejecutar BUY si el momentum 1M es NEUTRAL o no confirma claramente.
                return {
                    "execute": False,
                    "confidence": timing.get('strength', 0),
                    "reason": f"BUY bloqueado: momentum 1M {timing['momentum'].lower()} no confirma entrada"
                }

        # Solo ejecutar SELL si momentum 1M también es bajista
        # Soportar ambos formatos: "SELL ❌" y "SELL 🔴"
        if signal_from_hour in ["SELL ❌", "SELL 🔴"]:
            # Si hay un BUY activo, solo bloquear si el precio de venta es menor al nivel del BUY activo
            if buy_positions and len(buy_positions) > 0:
                # Tomar el BUY activo más reciente (puedes ajustar si prefieres otro criterio)
                buy_level = float(buy_positions[-1].get("level", 0))
                # El precio de venta debe ser pasado como parte de la lógica de ejecución real,
                # aquí solo se muestra la lógica de bloqueo conceptual
                # Suponiendo que el precio de venta propuesto es el último Close de data_1m
                sell_price = float(data_1m["Close"].iloc[-1])
                if sell_price < buy_level:
                    return {
                        "execute": False,
                        "reason": f"SELL bloqueado: No puedes vender por debajo de tu BUY activo ({sell_price:.2f} < {buy_level:.2f})"
                    }
            if timing["momentum"] == "BEARISH" and timing["ready"]:
                return {
                    "execute": True,
                    "confidence": timing["strength"],
                    "reason": f"SELL confirmado con momentum 1M bajista ({timing['strength']:.1f}%)"
                }
            elif timing["momentum"] == "BULLISH" and timing["strength"] > 0.5:
                return {
                    "execute": False,
                    "reason": f"SELL RETRASADO: Momentum 1M alcista fuerte ({timing['strength']:.2f}%), esperar mejor entrada"
                }
            else:
                return {
                    "execute": True,
                    "confidence": 50,
                    "reason": f"SELL con momentum {timing['momentum'].lower()} (ejecutar con cautela)"
                }

        return {
            "execute": False,
            "reason": "Señal no reconocida"
        }

    def optimize_exit_price(self, current_position, data_1m):
        """
        Optimiza el precio de salida usando datos de 1M.
        Evita salir en momentos desfavorables de liquidez.

        Args:
            current_position: dict con info de la posición actual
            data_1m: Datos de 1 minuto

        Returns:
            dict con recomendación de salida
        """
        if len(data_1m) < 5:
            return {
                "exit_now": True,
                "reason": "Datos insuficientes, salir inmediatamente"
            }

        recent = data_1m.iloc[-5:]

        # Detectar spread amplio (baja liquidez)
        avg_spread = ((recent["High"] - recent["Low"]) / recent["Close"]).mean()

        # Detectar movimiento brusco (puede revertir)
        price_change_1m = (recent["Close"].iloc[-1] - recent["Close"].iloc[-2]) / recent["Close"].iloc[-2]

        # Si el spread es > 0.2% o hay movimiento brusco > 0.5%, esperar
        if avg_spread > 0.002 or abs(price_change_1m) > 0.005:
            return {
                "exit_now": False,
                "wait_seconds": 60,  # Esperar 1 minuto
                "reason": f"Spread amplio ({avg_spread*100:.2f}%) o movimiento brusco, esperar mejores condiciones"
            }

        return {
            "exit_now": True,
            "reason": "Condiciones óptimas para salida"
        }


# Ejemplo de uso
if __name__ == "__main__":
    import json

    # Cargar datos de ejemplo
    with open("Reports/ETHUSD_CapitalData.json", "r") as f:
        data = json.load(f)

    data_1m = pd.DataFrame(data["data"])
    historical_data = pd.DataFrame(data["historical_data"])

    # Inicializar optimizer
    optimizer = TimingOptimizer()

    # Ejemplo 1: Verificar momentum actual
    momentum = optimizer.get_immediate_momentum(data_1m)
    print(f"\n📊 Momentum actual: {momentum}")

    # Ejemplo 2: Decidir si entrar con señal BUY
    decision = optimizer.should_enter_now("BUY 🟢", data_1m)
    print(f"\n🎯 Decisión de entrada: {decision}")

    # Ejemplo 3: Optimizar salida
    position = {"dealId": "123", "direction": "BUY"}
    exit_decision = optimizer.optimize_exit_price(position, data_1m)
    print(f"\n🚪 Decisión de salida: {exit_decision}")


def obtener_precio_sell():
    """
    Placeholder para obtener el precio de venta actual.
    Devuelve un valor predeterminado o simula un precio de venta.
    """
    # Simulación de un precio de venta (puede ser reemplazado con lógica real)
    return 1000.0
