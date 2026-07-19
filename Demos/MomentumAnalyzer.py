"""
MomentumAnalyzer - Sistema de análisis de momentum tick-a-tick
Captura aceleración de precio en tiempo real para detectar movimientos fuertes
"""
from collections import deque
from datetime import datetime, timezone
import time
import numpy as np


class MomentumAnalyzer:
    """
    Analiza el momentum instantáneo del precio capturando ticks cada segundo.

    Métricas calculadas:
    - Velocidad: Cambio de precio por segundo ($/s)
    - Aceleración: Cambio de velocidad por segundo ($/s²)
    - Momentum Score: Intensidad del movimiento (0-100)
    """

    def __init__(self, tick_window=30, velocity_threshold=0.05, accel_threshold=0.02):
        """
        Args:
            tick_window: Número de ticks a mantener en memoria (30 = 30 segundos)
            velocity_threshold: Velocidad mínima para considerar movimiento significativo ($/s) — 0.05 $/s = ~$3/min
            accel_threshold: Aceleración mínima para detectar impulso fuerte ($/s²)
        """
        self.tick_window = tick_window
        self.velocity_threshold = velocity_threshold
        self.accel_threshold = accel_threshold

        # Deques para almacenar ticks recientes
        self.prices = deque(maxlen=tick_window)
        self.timestamps = deque(maxlen=tick_window)
        self.velocities = deque(maxlen=tick_window - 1)
        self.accelerations = deque(maxlen=tick_window - 2)

        # Estado actual
        self.current_price = None
        self.current_velocity = 0.0
        self.current_acceleration = 0.0
        self.momentum_score = 0.0
        self.direction = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL

    def add_tick(self, price, timestamp=None):
        """
        Añade un tick de precio y recalcula métricas.

        Args:
            price: Precio actual
            timestamp: Timestamp (default: now)

        Returns:
            dict: Métricas calculadas
        """
        if timestamp is None:
            timestamp = time.time()

        self.current_price = price
        self.prices.append(price)
        self.timestamps.append(timestamp)

        # Calcular velocidad si hay al menos 2 ticks
        if len(self.prices) >= 2:
            price_change = self.prices[-1] - self.prices[-2]
            time_delta = self.timestamps[-1] - self.timestamps[-2]

            if time_delta > 0:
                velocity = price_change / time_delta  # $/segundo
                self.current_velocity = velocity
                self.velocities.append(velocity)

        # Calcular aceleración si hay al menos 2 velocidades
        if len(self.velocities) >= 2:
            velocity_change = self.velocities[-1] - self.velocities[-2]
            time_delta = self.timestamps[-1] - self.timestamps[-2]

            if time_delta > 0:
                acceleration = velocity_change / time_delta  # $/segundo²
                self.current_acceleration = acceleration
                self.accelerations.append(acceleration)

        # Actualizar dirección y momentum score
        self._update_direction()
        self._calculate_momentum_score()

        return self.get_metrics()

    def _update_direction(self):
        """Actualiza la dirección del momentum basado en velocidad y aceleración."""
        velocity = self.current_velocity
        acceleration = self.current_acceleration

        # Dirección basada en velocity + acceleration
        if velocity >= self.velocity_threshold:
            if acceleration >= 0:
                self.direction = "BULLISH_STRONG"  # Subiendo y acelerando
            else:
                self.direction = "BULLISH_WEAK"    # Subiendo pero desacelerando
        elif velocity <= -self.velocity_threshold:
            if acceleration <= 0:
                self.direction = "BEARISH_STRONG"  # Bajando y acelerando
            else:
                self.direction = "BEARISH_WEAK"    # Bajando pero desacelerando
        else:
            self.direction = "NEUTRAL"

    def _calculate_momentum_score(self):
        """
        Calcula un score de momentum (0-100) basado en:
        - Velocidad absoluta
        - Aceleración absoluta
        - Consistencia de dirección
        """
        if len(self.velocities) < 5:
            self.momentum_score = 0.0
            return

        # Componente 1: Velocidad promedio reciente (últimos 5 ticks)
        recent_velocities = list(self.velocities)[-5:]
        avg_velocity = np.mean(np.abs(recent_velocities))
        velocity_component = min(avg_velocity / self.velocity_threshold * 30, 30)

        # Componente 2: Aceleración absoluta
        if len(self.accelerations) > 0:
            recent_accels = list(self.accelerations)[-5:]
            avg_accel = np.mean(np.abs(recent_accels))
            accel_component = min(avg_accel / self.accel_threshold * 30, 30)
        else:
            accel_component = 0

        # Componente 3: Consistencia de dirección (misma dirección = más fuerte)
        if len(recent_velocities) >= 5:
            positive_count = sum(1 for v in recent_velocities if v > 0)
            negative_count = sum(1 for v in recent_velocities if v < 0)
            consistency = max(positive_count, negative_count) / len(recent_velocities)
            consistency_component = consistency * 40
        else:
            consistency_component = 0

        # Score total (0-100)
        self.momentum_score = min(velocity_component + accel_component + consistency_component, 100)

    def get_metrics(self):
        """
        Retorna métricas actuales del momentum.

        Returns:
            dict: Todas las métricas calculadas
        """
        return {
            "price": self.current_price,
            "velocity": self.current_velocity,  # $/segundo
            "acceleration": self.current_acceleration,  # $/segundo²
            "momentum_score": self.momentum_score,  # 0-100
            "direction": self.direction,
            "is_strong_move": self.momentum_score >= 60,  # Threshold para movimiento fuerte
            "is_bullish": "BULLISH" in self.direction,
            "is_bearish": "BEARISH" in self.direction,
            "tick_count": len(self.prices)
        }

    def get_signal_strength(self):
        """
        Retorna la fuerza de la señal actual para integración con estrategia.

        Returns:
            float: -1.0 (bearish fuerte) a +1.0 (bullish fuerte)
        """
        if self.direction == "NEUTRAL":
            return 0.0

        strength = self.momentum_score / 100.0  # Normalizar 0-1

        if "BEARISH" in self.direction:
            return -strength
        elif "BULLISH" in self.direction:
            return strength

        return 0.0

    def should_boost_signal(self, signal_type):
        """
        Determina si el momentum actual debería potenciar una señal BUY/SELL.

        Args:
            signal_type: "BUY" o "SELL"

        Returns:
            tuple: (should_boost: bool, bonus_points: int)
        """
        if self.momentum_score < 50:  # Momentum insuficiente
            return False, 0

        # BUY + momentum alcista fuerte = boost
        if signal_type == "BUY" and self.direction == "BULLISH_STRONG":
            bonus = 2 if self.momentum_score >= 80 else 1
            return True, bonus

        # SELL + momentum bajista fuerte = boost
        if signal_type == "SELL" and self.direction == "BEARISH_STRONG":
            bonus = 2 if self.momentum_score >= 80 else 1
            return True, bonus

        return False, 0

    def should_reject_signal(self, signal_type):
        """
        Determina si el momentum actual debería rechazar una señal BUY/SELL.

        Args:
            signal_type: "BUY" o "SELL"

        Returns:
            tuple: (should_reject: bool, penalty_points: int)
        """
        if self.momentum_score < 50:  # Momentum bajo, no penalizar
            return False, 0

        # BUY contra momentum bajista fuerte = penalizar
        if signal_type == "BUY" and self.direction == "BEARISH_STRONG":
            penalty = -2 if self.momentum_score >= 80 else -1
            return True, penalty

        # SELL contra momentum alcista fuerte = penalizar
        if signal_type == "SELL" and self.direction == "BULLISH_STRONG":
            penalty = -2 if self.momentum_score >= 80 else -1
            return True, penalty

        return False, 0

    def reset(self):
        """Resetea el analyzer (útil para testing o reinicios)."""
        self.prices.clear()
        self.timestamps.clear()
        self.velocities.clear()
        self.accelerations.clear()
        self.current_price = None
        self.current_velocity = 0.0
        self.current_acceleration = 0.0
        self.momentum_score = 0.0
        self.direction = "NEUTRAL"

    def get_debug_info(self):
        """Información de debug para logging."""
        return {
            "ticks_collected": len(self.prices),
            "last_10_velocities": list(self.velocities)[-10:] if len(self.velocities) > 0 else [],
            "last_5_accelerations": list(self.accelerations)[-5:] if len(self.accelerations) > 0 else [],
            "current_metrics": self.get_metrics()
        }
