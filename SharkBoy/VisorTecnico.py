from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtCore import Qt
import json
import os
import pandas as pd
import numpy as np
import yfinance as yf
import time
from threading import Thread
import matplotlib.pyplot as plt
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtCore import Qt


class CircleWidget(QWidget):
    def __init__(self, color="white", parent=None):
        super().__init__(parent)
        self.color = QColor(color)

    def set_color(self, color_name):
        """Actualiza el color del círculo."""
        self.color = QColor(color_name)
        self.update()

    def paintEvent(self, event):
        """Dibuja el círculo con el color actual."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self.color)
        painter.setPen(Qt.NoPen)
        size = min(self.width(), self.height())
        painter.drawEllipse(0, 0, size, size)


class TechnicalAnalysis(QObject):
    analysis_signal = pyqtSignal(str)  # Señal para enviar resultados de análisis a la interfaz

    def __init__(self, data_dir, ticker, content_widgets, vumeter_widgets , circle_widgets, interval=1000, output_dir="Reports/indicators"):

        super().__init__()
        self.data_dir = data_dir
        self.ticker = ticker
        self.circle_widgets = circle_widgets
        self.content_widgets = content_widgets
        self.vumeter_widgets = vumeter_widgets  # Almacena la referencia de los vúmetros
        self.interval = interval 
        self.running = False
        self.thread = None
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)  # Asegura que el directorio exista
        
    def log_indicators(self, macd, rsi, volume_change):
        """
        Guarda los indicadores actuales en un archivo JSON, sobrescribiendo los datos previos.
        """
        try:
            file_path = os.path.join(self.output_dir, f"{self.ticker}_indicators.json")

            # Crear la entrada con los indicadores actuales
            data = {
                "ticker": self.ticker,
                "indicators": {  # Sobrescribe en lugar de acumular
                    "MACD": macd,
                    "RSI": rsi,
                    "VolumeChange": volume_change,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
            }

            # Sobrescribir el archivo con los nuevos datos
            with open(file_path, "w") as file:
                json.dump(data, file, indent=4)

            print(f"[INFO] Indicadores actualizados para {self.ticker} en {file_path}.")
        except Exception as e:
            print(f"[ERROR] No se pudieron guardar los indicadores para {self.ticker}: {e}")


    @staticmethod
    def load_json_file(filepath):
        """Carga un archivo JSON y lo devuelve como un dict."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
        with open(filepath, "r") as file:
            return json.load(file)

    @staticmethod
    def calculate_rsi(data, period=5, smooth_factor=3):
        """
        Calcula el RSI ajustado para estrategias intradía.
        
        :param data: DataFrame con columna 'Close'.
        :param period: Período para calcular el RSI (por defecto, 5 para intradía).
        :param smooth_factor: Período para suavizar las oscilaciones del RSI.
        :return: Serie con el RSI suavizado.
        """
        if 'Close' not in data.columns or len(data) < period:
            raise ValueError("Datos insuficientes o columna 'Close' faltante para calcular RSI.")

        # Calcular cambios diarios
        delta = data['Close'].diff()

        # Calcular ganancias y pérdidas
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        # Promedio de ganancias/pérdidas
        avg_gain = gain.rolling(window=period, min_periods=1).mean()
        avg_loss = loss.rolling(window=period, min_periods=1).mean()

        # Cálculo del RSI
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        # Suavizado adicional
        smoothed_rsi = rsi.rolling(window=smooth_factor, min_periods=1).mean()

        return smoothed_rsi


    @staticmethod
    def calculate_macd(data, fast=12, slow=26, signal_period=9):
        """Calcula el MACD y su señal."""
        macd_fast = data['Close'].ewm(span=fast, adjust=False).mean()
        macd_slow = data['Close'].ewm(span=slow, adjust=False).mean()
        macd = macd_fast - macd_slow
        signal = macd.ewm(span=signal_period, adjust=False).mean()
        return macd, signal

    @staticmethod
    def calculate_fibonacci_levels(data):
        """Calcula los niveles de Fibonacci."""
        max_price = data['Close'].max()
        min_price = data['Close'].min()
        diff = max_price - min_price
        levels = {
            "0%": max_price,
            "23.6%": max_price - 0.236 * diff,
            "38.2%": max_price - 0.382 * diff,
            "50%": max_price - 0.5 * diff,
            "61.8%": max_price - 0.618 * diff,
            "100%": min_price,
        }
        return levels

    def analyze_ticker(self):
        """Analyze a ticker using JSON files and calculate technical indicators."""
        try:
            # Cargar datos históricos
            current_path = os.path.join(self.data_dir, f"{self.ticker}_current.json")
            historical_path = os.path.join(self.data_dir, f"{self.ticker}_historical.json")

            current_data = self.load_json_file(current_path)[0]
            historical_data = pd.DataFrame(self.load_json_file(historical_path))

            # Calcular MACD y el histograma
            macd, signal = self.calculate_macd(historical_data)
            histogram = macd - signal
            histogram_value = histogram.iloc[-1]

            # Calcular ATR y escala dinámica
            recent_histogram = histogram[-100:]
            atr = self.calculate_atr(historical_data[-20:], period=3)
            max_histogram = max(abs(recent_histogram.min()), abs(recent_histogram.max()), atr)

            # Normalización dinámica del histograma
            proportional_histogram = histogram_value / max_histogram * 0.8
            normalized_histogram = max(-1.0, min(proportional_histogram, 1.0))

            # Ajuste para valores positivos pequeños
            if histogram_value > 0 and normalized_histogram < 0.1:
                normalized_histogram = 0.1

            # Actualizar el vúmetro dinámicamente
            vumeter = self.vumeter_widgets.get(self.ticker)
            if vumeter:
                vumeter.set_level(normalized_histogram)
            else:
                print(f"[ERROR] No se encontró el vúmetro para {self.ticker}")

            # Establecer el color del MACD
            macd_indicator = "green" if macd.iloc[-1] > signal.iloc[-1] else "red"

            # Calcular RSI
            historical_data['RSI'] = self.calculate_rsi(historical_data, period=5)
            rsi = historical_data['RSI'].iloc[-1]
            rsi_indicator = "green" if rsi < 30 else "red" if rsi > 70 else "white"

            # Obtener volumen en tiempo real
            real_time_volume = yf.Ticker(self.ticker).info.get("volume", None)
            if not real_time_volume:
                raise ValueError("Unable to fetch real-time volume.")

            # Calcular cambio porcentual del volumen usando promedio móvil reciente
            historical_volume = historical_data['Volume'].astype(float)
            recent_volume = historical_volume.rolling(window=3).mean().iloc[-1]  # Promedio de últimos 5 períodos
            volume_change = ((real_time_volume - recent_volume) / recent_volume) * 100

            # Clasificar el indicador de volumen
            if volume_change > 20:  # Incremento significativo en volumen
                volume_indicator = "green"
            elif volume_change < -20:  # Caída significativa en volumen
                volume_indicator = "red"
            else:
                volume_indicator = "white"


            # Log de indicadores
            self.log_indicators(histogram_value, rsi, volume_change)


            # Actualizar widgets visuales
            self.circle_widgets["rsi"].set_color(rsi_indicator)
            self.circle_widgets["macd"].set_color(macd_indicator)
            self.circle_widgets["volume"].set_color(volume_indicator)

            self.content_widgets["rsi_label"].setText(f"RSI: {rsi:.2f}")
            self.content_widgets["macd_label"].setText(f"MACD: {histogram_value:.2f}")
            self.content_widgets["volume_label"].setText(f"Volumen: {volume_change:.2f}%")

            # Imprimir señal informativa si hay un cambio fuerte
            if volume_indicator == "green" and histogram_value > 0 and rsi < 30:
                print(f"[BUY] Señal de compra: Volumen +{volume_change:.2f}%, MACD {histogram_value:.2f}, RSI {rsi:.2f}")
            elif volume_indicator == "red" and histogram_value < 0 and rsi > 70:
                print(f"[SELL] Señal de venta: Volumen {volume_change:.2f}%, MACD {histogram_value:.2f}, RSI {rsi:.2f}")

        except Exception as e:
            print(f"[ERROR] Failed to analyze {self.ticker}: {e}")


    def calculate_atr(self, data, period=5):
        """
        Calcula el Average True Range (ATR) para ajustar la escala del histograma.
        :param data: DataFrame con los datos históricos (debe incluir 'High', 'Low', 'Close').
        :param period: Período para el ATR.
        :return: Valor ATR calculado.
        """
        high_low = data['High'] - data['Low']
        high_close = (data['High'] - data['Close'].shift()).abs()
        low_close = (data['Low'] - data['Close'].shift()).abs()
        
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean().iloc[-1]  # ATR del último valor
        return atr


    def start_analysis(self):
        if self.running:
            print(f"[DEBUG] El análisis ya está corriendo para {self.ticker}.")
            return
        self.running = True
        self.thread = Thread(target=self.run_analysis)
        self.thread.daemon = True
        self.thread.start()


    def run_analysis(self):
        """Ejecuta el análisis de un ticker periódicamente."""
        while self.running:
            self.analyze_ticker()
            time.sleep((self.interval * 4000) / 1000)

    def stop_analysis(self):
        """Detiene el análisis periódico."""
        self.running = False
        if self.thread:
            self.thread.join()
