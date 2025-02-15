from PyQt5.QtWidgets import (QApplication, QGridLayout,  QLineEdit, QPushButton, QTextEdit,
     QGraphicsView, QGraphicsScene, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame, QTabWidget)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from VisorTecnico import TechnicalAnalysis,  CircleWidget
from PyQt5.QtGui import QPainter, QColor, QPixmap
from PyQt5.QtWidgets import QDialog
from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem
from CapitalOperations import CapitalOP
from MainOperator2 import TradingOperator

capital_ops = CapitalOP()

from PyQt5.QtCore import Qt
from PyQt5.QtCore import QObject
from PyQt5.QtGui import QTextCursor
import yfinance as yf
import subprocess
import threading  # También asegúrate de tener threading importado
import pandas as pd
import websocket
import requests
from repulser import MarketFlow
import time
import sip
import sys
import json
import pickle
from Strategy import Strategia
import os


# Variables de configuración
BASE_URL = "https://demo-api-capital.backend-capital.com"
SESSION_ENDPOINT = "/api/v1/session"
MARKET_SEARCH_ENDPOINT = "/api/v1/markets"
API_KEY = "dshUTxIDbHEtaOJS"
LOGIN = "ODREMANALLANR@GMAIL.COM"
PASSWORD = "Millo2025."
DATA_FILE = "/home/hobeat/MoneyMakers/Reports/BTC-USD_IndicadoresCondensados.json"
DATA_DIR = "Reports"  # Directorio donde se guardarán los archivos JSON
MODEL_FILE = "BTCMD1.pkl"  # Ruta al archivo del modelo


 
class RepulserThread(QThread):
    data_ready = pyqtSignal(object)  # Señal para enviar los resultados del radar a la GUI
    
class VuMeterWidget(QWidget):
    def __init__(self, max_steps=10, parent=None):
        super().__init__(parent)
        self.max_steps = max_steps
        self.level = 0.0  # Nivel inicial (-1.0 a 1.0)
        self.setFixedWidth(20)  # Ancho fijo
        self.setMinimumHeight(100)  # Altura mínima
        
    def set_level(self, value, max_intensity=1.0):
        """
        Ajusta el nivel del vúmetro basado en el valor del histograma MACD.
        Aplica un mínimo visual y logarítmico para valores pequeños.
        """
        min_scale = 0.05  # Valor mínimo visual
        effective_max = max(max_intensity, min_scale)
        normalized_value = max(-1.0, min(value / effective_max, 1.0))
        self.level = normalized_value
        self.update()



    def paintEvent(self, event):
        """Dibuja el vúmetro con color rojo abajo y verde arriba."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        total_height = self.height()
        half_height = total_height // 2
        bar_width = self.width()

        # Altura activa según el nivel
        active_height = int(half_height * abs(self.level))

        # Pintar la parte positiva (verde) si el nivel es positivo
        if self.level > 0:
            painter.setBrush(QColor("#00ff00"))  # Verde
            painter.drawRect(0, half_height - active_height, bar_width, active_height)

        # Pintar la parte negativa (rojo) si el nivel es negativo
        elif self.level < 0:
            painter.setBrush(QColor("#ff0000"))  # Rojo
            painter.drawRect(0, half_height, bar_width, active_height)
           
class HistoricalDataManager:
        def __init__(self, data_dir="Reports"):
            self.data_dir = data_dir  # Carpeta donde se guardarán los archivos históricos

        def transform_ticker_for_yf(self, ticker):
            """
            Transforma un ticker del formato de Capital al formato de Yahoo Finance.
            - Si el ticker contiene 'USD' y tiene más de 4 caracteres, agrega un '-' antes de 'USD'.
            """
            if len(ticker) > 4 and ticker.endswith("USD"):
                return ticker[:-3] + "-" + ticker[-3:]
            return ticker


        def download_general_info(self, ticker):
            """
            Descarga información general de un ticker y la guarda como un archivo JSON.
            """
            try:
                print(f"[INFO] Descargando información general para {ticker}...")
                ticker_info = yf.Ticker(ticker).info  # Obtiene la información general del ticker
                
                if ticker_info:
                    # Asegurarse de que el directorio de datos exista
                    os.makedirs(self.data_dir, exist_ok=True)
                    
                    # Crear la ruta del archivo
                    file_path = os.path.join(self.data_dir, f"{ticker}_general.json")
                    
                    # Guardar la información como JSON
                    with open(file_path, 'w') as json_file:
                        json.dump(ticker_info, json_file, indent=4)
                    
                    print(f"[INFO] Información general guardada en {file_path}")
                else:
                    print(f"[ERROR] No se pudo obtener información para {ticker}.")

            except Exception as e:
                print(f"[ERROR] Error al descargar información general para {ticker}: {e}")

        def download_data_to_json(self, ticker):
            try:
                # Transformar el ticker al formato de Yahoo Finance
                transformed_ticker = self.transform_ticker_for_yf(ticker)

                # Descarga de datos históricos
                historical_data = yf.download(transformed_ticker, period="2y", interval="1d")
                if not historical_data.empty:
                    historical_data.reset_index(inplace=True)
                    historical_data['Date'] = historical_data['Date'].dt.strftime('%Y-%m-%d %H:%M:%S')
                    historical_data.columns = [col[0] if isinstance(col, tuple) else col for col in historical_data.columns]
                    historical_data_dict = historical_data.to_dict(orient="records")

                    # Guardar los datos históricos
                    self.save_ticker_to_individual_json(transformed_ticker, historical_data_dict, suffix="_historical")

                # Descargar información general
                self.download_general_info(transformed_ticker)

                # Descarga de datos actuales
                current_data = yf.download(transformed_ticker, period="1d", interval="15m")
                if not current_data.empty:
                    current_data.reset_index(inplace=True)
                    current_data.columns = [col[0] if isinstance(col, tuple) else col for col in current_data.columns]

                    # Ajustar la zona horaria
                    current_data["Datetime"] = pd.to_datetime(current_data["Datetime"]).dt.tz_localize("UTC").dt.tz_convert("America/Guayaquil")

                    # Convertir a dict y guardar archivos
                    current_data_dict = current_data.to_dict(orient="records")
                    self.save_ticker_to_individual_json(transformed_ticker, current_data_dict, suffix="_current")
                    self.save_ticker_to_individual_json(transformed_ticker, current_data_dict, suffix="_indicators")

                # Llamar a `HIstoricalINdicators` para procesar los condensados (sin afectar `_current.json`)
                transformed_ticker_safe = transformed_ticker.replace("-", "_")
                condensados_file = os.path.join(self.data_dir, f"{transformed_ticker_safe}_IndicadoresCondensados.json")
                self.process_historical_indicators(condensados_file)

            except Exception as e:
                print(f"[ERROR] Error al descargar datos para {ticker}: {e}")




        
        def process_historical_indicators(self, file_path):
            """
            Llama al script de indicadores históricos para procesar los `IndicadoresCondensados`.
            """
            try:
                if "_IndicadoresCondensados" not in file_path:
                    print(f"[INFO] Archivo {file_path} no es un archivo válido para indicadores. Omitido.")
                    return

                if not os.path.exists(file_path):
                    print(f"[ERROR] Archivo {file_path} no encontrado.")
                    return

                script_path = os.path.join(os.getcwd(), "HIstoricalINdicators.py")
                python_exec = sys.executable

                print(f"[INFO] Ejecutando el script HIstoricalINdicators.py con {file_path}...")
                result = subprocess.run(
                    [python_exec, script_path, file_path],
                    check=True,
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    print(f"[INFO] Procesamiento de indicadores completado para {file_path}.")
                else:
                    print(f"[ERROR] Fallo al ejecutar el script: {result.stderr}")

            except Exception as e:
                print(f"[ERROR] Error inesperado al procesar indicadores: {e}")









        def normalize_data(self, data):
            """Normaliza los datos descargados respetando las reglas de current.json."""
            if data is None or data.empty:
                print(f"[WARNING] No hay datos para normalizar.")
                return []

            try:
                normalized_data = []
                # Convertir el DataFrame a una lista de diccionarios si aún no lo es
                if isinstance(data, pd.DataFrame):
                    records = data.to_dict(orient="records")
                elif isinstance(data, list):  # Si ya es una lista, úsala directamente
                    records = data
                else:
                    print(f"[ERROR] Tipo de datos no soportado para normalizar: {type(data)}")
                    return []

                for record in records:
                    normalized_record = {}
                    if isinstance(record, dict):  # Verificar que cada elemento sea un diccionario
                        for key, value in record.items():
                            # Limpiar la clave para extraer solo la parte relevante
                            new_key = str(key).split(",")[0].strip("('')")

                            # Convertir valores Timestamp a string si es necesario
                            if isinstance(value, pd.Timestamp):
                                normalized_record[new_key] = value.strftime('%Y-%m-%d %H:%M:%S')
                            else:
                                normalized_record[new_key] = value

                        normalized_data.append(normalized_record)
                    else:
                        print(f"[ERROR] El registro {record} no es un diccionario.")
                        return []  # Si un registro no es un diccionario, retornamos una lista vacía

                return normalized_data

            except Exception as e:
                print(f"[ERROR] Error al normalizar los datos: {e}")
            


        def save_ticker_to_individual_json(self, ticker, data, suffix=""):
            """
            Guarda los datos de un ticker en un archivo JSON único basado en el ticker y el sufijo.

            :param ticker: El ticker transformado para Yahoo Finance.
            :param data: Los datos a guardar (formato lista de diccionarios o DataFrame).
            :param suffix: Sufijo opcional para el nombre del archivo (e.g., '_historical', '_current').
            """
            try:
                # Verificar y limpiar el sufijo
                suffix = suffix if suffix.startswith("_") else f"_{suffix}"
                file_path = os.path.join(self.data_dir, f"{ticker}{suffix}.json")

                # Generar la ruta del archivo único
                file_path = os.path.join(self.data_dir, f"{ticker}{suffix}.json")
                os.makedirs(self.data_dir, exist_ok=True)  # Asegurarse de que el directorio exista

                # Normalizar los datos
                if isinstance(data, pd.DataFrame):
                    normalized_data = self.normalize_data(data)
                elif isinstance(data, list):
                    normalized_data = self.normalize_data(pd.DataFrame(data))
                else:
                    raise ValueError(f"[ERROR] Tipo de datos no soportado para {ticker}: {type(data)}")

                # Validar datos normalizados
                if not normalized_data or len(normalized_data) == 0:
                    print(f"[WARNING] No se encontraron datos para guardar en {file_path}.")
                    return

                # Guardar los datos normalizados en formato JSON
                with open(file_path, "w") as file:
                    json.dump(normalized_data, file, indent=4)

                print(f"[INFO] Datos guardados correctamente en {file_path} para el ticker {ticker}.")
            except Exception as e:
                print(f"[ERROR] No se pudieron guardar los datos para {ticker} en {file_path}: {e}")



        
        def save_epics(self):
            """Guardar los epics actuales y actualizar los indicadores visualmente."""
            # Guardamos la lista actualizada de epics
            MarketSearchApp.saved_epics = [
                self.result_area_layout.itemAt(i).widget().objectName()
                for i in range(self.result_area_layout.count())
            ]
            
            self.append_to_debug_area(f"[INFO] Lista guardada: {MarketSearchApp.saved_epics}")
            self.update_saved_epics_in_code()  # Actualiza el archivo de código
            
            # Eliminamos los tickers que ya no están en saved_epics
            for ticker in list(self.threads.keys()):
                if ticker not in MarketSearchApp.saved_epics:
                    self.remove_ticker_from_interface(ticker)  # Llamamos para eliminar el ticker y su indicador
            
            # Actualizamos los labels visuales
            self.update_indicator_labels()
            
            # Crear hilos para cada ticker en saved_epics
            for ticker in MarketSearchApp.saved_epics:
                label = self.get_label_for_ticker(ticker)

                # Si no se encuentra un label, lo mostramos en la depuración
                if label is None:
                    self.append_to_debug_area(f"[ERROR] No se encontró un label para {ticker}")
                    continue  # Si no se encuentra el label, saltamos al siguiente ticker

                # Verificamos si ya existe un hilo para este ticker
                if ticker not in self.threads:
                    # Crear hilo para este ticker si no existe ya
                    thread = IndicatorThread(ticker)
                    
                    # Conectamos la señal del hilo para actualizar el label con los resultados de los indicadores
                    thread.update_signal.connect(lambda t, e, l=label: self.update_evaluation(t, e, l))
                    
                    thread.start()  # Iniciamos el hilo
                    self.threads[ticker] = thread  # Guardamos el hilo en el diccionario
                    self.append_to_debug_area(f"[INFO] Hilo creado para {ticker}")
                else:
                    self.append_to_debug_area(f"[INFO] Hilo ya existe para {ticker}")

class DownloadThread(QThread):
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str)

    def __init__(self, manager, ticker):
        super().__init__()
        self.manager = manager
        self.ticker = ticker
        self._is_running = True

    def run(self):
        while self._is_running:
            try:
                self.progress_signal.emit(f"[INFO] Descargando datos para {self.ticker}...")
                self.manager.download_data_to_json(self.ticker)
                self.progress_signal.emit(f"[INFO] Descarga completada para {self.ticker}.")
            except Exception as e:
                self.progress_signal.emit(f"[ERROR] Error al descargar datos para {self.ticker}: {e}")
                break  # Salir del bucle si hay un error crítico
                self.stop()  # Detiene el hilo si hay un error crítico
            time.sleep(350)
        self.finished_signal.emit(f"[INFO] Hilo de descarga finalizado para {self.ticker}.")



    def stop(self):
        """Detiene el hilo de forma segura."""
        self._is_running = False
        self.quit()
        self.wait()

class RepulserThread(QThread):
    progress_signal = pyqtSignal(str)  # Señal para progreso
    update_signal = pyqtSignal(dict)  # Señal para enviar resultados actualizados

    def __init__(self, radar_data, repulser):
        super().__init__()
        self.radar_data = radar_data
        self.repulser = repulser
        self._is_running = True

    def run(self):
        """Ejecuta la lógica de cálculo y actualización del Repulser en un hilo separado."""
        try:
            self.progress_signal.emit("[INFO] Iniciando actualización de Repulser...")
            if self.radar_data:
                # Procesar datos y calcular oportunidades
                processed_data = self.calculate_opportunities(self.radar_data)
                self.update_signal.emit(processed_data)  # Emitir resultados procesados
            else:
                self.progress_signal.emit("[INFO] No hay datos para procesar en Repulser.")
        except Exception as e:
            self.progress_signal.emit(f"[ERROR] Error durante la actualización de Repulser: {e}")

    def calculate_opportunities(self, data):
        """Calcula las oportunidades basadas en los datos."""
        opportunities = {}
        for ticker, details in data.items():
            # Aquí puedes colocar la lógica real del cálculo
            opportunities[ticker] = {
                "opportunity_score": 0.75,  # Simulación: reemplázalo con tu fórmula
                "details": details
            }
        return opportunities

    def stop(self):
        """Detiene el hilo de forma segura."""
        self._is_running = False
        self.quit()
        self.wait()

class WebSocketManager:
    def __init__(self, url, api_key,epic_manager=None , debug_callback=None, update_price_callback=None, sync_tickers_callback=None):
        self.url = url
        self.api_key = api_key
        self.epic_manager = epic_manager  # Asignar EpicManager
        self.cst_token = None
        self.security_token = None
        self.debug_callback = debug_callback  # Callback para mensajes de depuración
        self.update_price_callback = update_price_callback  # Callback para actualizar precios
        self.sync_tickers_callback = sync_tickers_callback  # Guardar el callback
        self.ws = None  # WebSocketApp
        self.active_epics = []  # Lista de epics suscritos
        self.is_connecting = False  # Indica si ya se está intentando conectar
        self.is_connected = False  # Indica si el WebSocket está conectado
        self.ping_thread = None  # Inicializa el atributo del hilo de ping

    def tokens_valid(self):
        """Verifica si los tokens están configurados correctamente y los renueva si es necesario."""
        valid = self.cst_token is not None and self.security_token is not None
        if not valid:
            success, _, _ = self.login_and_get_account_info(LOGIN, PASSWORD)
            if success:
                self.log_debug("[INFO] Sesión renovada exitosamente.")
                return True
            else:
                self.log_debug("[ERROR] No se pudo renovar la sesión. Verifica tus credenciales.")
                return False
        return True

    def login_and_get_account_info(self, username, password):
        """Realiza el login, obtiene los tokens y el saldo de la cuenta."""
        try:
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key
            }
            payload = {
                "identifier": username,
                "password": password,
                "encryptedPassword": False
            }
            session_url = BASE_URL + SESSION_ENDPOINT
            self.log_debug("[INFO] Iniciando sesión...")
            response = requests.post(session_url, json=payload, headers=headers)

            if response.status_code != 200:
                self.log_debug(f"[ERROR] Fallo en la autenticación: {response.text}")
                return False, None, None

            headers = response.headers
            self.cst_token = headers.get("CST")
            self.security_token = headers.get("X-SECURITY-TOKEN")

            if not self.cst_token or not self.security_token:
                self.log_debug("[ERROR] Tokens de seguridad no recibidos.")
                return False, None, None

            data = response.json()
            available_balance = data['accountInfo']['available']
            currency_iso_code = data['currencyIsoCode']

            self.log_debug(f"[INFO] CST Token: {self.cst_token}")
            self.log_debug(f"[INFO] X-Security Token: {self.security_token}")
            self.log_debug(f"[INFO] Saldo disponible: {available_balance} {currency_iso_code}")
            self.log_debug("[INFO] Sesión iniciada correctamente.")
            return True, available_balance, currency_iso_code

        except requests.RequestException as e:
            self.log_debug(f"[ERROR] Error durante la conexión: {e}")
            return False, None, None

    def log_debug(self, message):
        """Callback para mensajes de depuración."""
        if self.debug_callback:
            self.debug_callback(message)
        else:
            print(message)

    def start(self, username=None, password=None):
        """Inicia sesión y establece la conexión WebSocket."""
        if username and password:
            success, balance, currency = self.login_and_get_account_info(username, password)
            if success:
                self.log_debug("[INFO] Login exitoso.")
                self.start_websocket()  # Llama al método recién definido
                return balance, currency
            else:
                self.log_debug("[ERROR] Login fallido.")
                return None, None
        else:
            self.log_debug("[ERROR] Usuario y contraseña no proporcionados para el login.")
            return None, None

    def start_websocket(self):
        """Inicia la conexión al WebSocket."""
        if self.is_connected or self.is_connecting:
            self.log_debug("[INFO] WebSocket ya está conectado o intentando conectar.")
            return

        self.log_debug("[INFO] Iniciando conexión al WebSocket...")

        def on_open(ws):
            """Acciones al abrir la conexión."""
            self.log_debug("[INFO] WebSocket conectado exitosamente.")
            self.is_connected = True
            self.is_connecting = False
            self.send_subscription_update()

        def on_message(ws, message):
            """Procesa los mensajes entrantes del WebSocket."""
            try:
                data = json.loads(message)
                if data.get("destination") == "quote" and "payload" in data:
                    epic = data["payload"].get("epic")
                    bid = data["payload"].get("bid")
                    if epic and bid and self.update_price_callback:
                        self.update_price_callback(epic, bid)
            except Exception as e:
                self.log_debug(f"[ERROR] Error procesando mensaje: {e}")

        def on_close(ws, close_status_code, close_msg):
            """Acciones al cerrar la conexión."""
            self.log_debug("[INFO] WebSocket cerrado.")
            self.is_connected = False

        def on_error(ws, error):
            """Manejo de errores del WebSocket."""
            self.log_debug(f"[ERROR] WebSocket error: {error}")
            self.is_connected = False
            self.reconnect()

        self.ws = websocket.WebSocketApp(
            self.url,
            on_open=on_open,
            on_close=on_close,
            on_error=on_error,
            on_message=on_message
        )

        threading.Thread(target=self.ws.run_forever, daemon=True).start()

    def start_ping(self):
        """Inicia un hilo para enviar mensajes de ping periódicos al WebSocket."""
        def ping():
            while True:
                if not self.is_connected:
                    self.log_debug("[ERROR] No se puede enviar ping, WebSocket desconectado.")
                    time.sleep(5)
                    continue
                
                # Verificar y renovar tokens si es necesario
                if not self.tokens_valid():
                    self.log_debug("[ERROR] Tokens inválidos. Intentando renovar sesión...")
                    continue  # Esperar antes de intentar enviar el siguiente ping
                
                # Construir el mensaje de ping
                try:
                    ping_message = {
                        "destination": "ping",
                        "correlationId": str(int(time.time())),
                        "cst": self.cst_token,
                        "securityToken": self.security_token
                    }
                    self.ws.send(json.dumps(ping_message))
                    self.log_debug("[INFO] Ping enviado al servidor.")
                except Exception as e:
                    self.log_debug(f"[ERROR] Error al enviar ping: {e}")

                # Esperar 9 minutos (540 segundos) antes del próximo ping
                time.sleep(540)

        # Verificar si el hilo de ping ya está corriendo
        if self.ping_thread is None or not self.ping_thread.is_alive():
            self.ping_thread = threading.Thread(target=ping, daemon=True)
            self.ping_thread.start()
            self.log_debug("[INFO] Hilo de ping iniciado.")



    def send_subscription_update(self):
        """Envía todas las suscripciones activas al WebSocket."""
        self.log_debug("[DEBUG] Llamando a send_subscription_update.")
        if not self.is_connected:
            self.log_debug("[ERROR] WebSocket no conectado. No se enviarán suscripciones.")
            return

        if not self.active_epics:
            self.log_debug("[INFO] No hay epics para suscribirse.")
            return

        payload = {
            "destination": "marketData.subscribe",
            "correlationId": str(int(time.time())),
            "cst": self.cst_token,
            "securityToken": self.security_token,
            "payload": {"epics": self.active_epics}
        }

        try:
            self.ws.send(json.dumps(payload))  # Enviar suscripciones
            self.log_debug(f"[INFO] Suscripciones enviadas: {self.active_epics}")
        except Exception as e:
            self.log_debug(f"[ERROR] No se pudieron enviar las suscripciones: {e}")



    def reconnect(self, max_attempts=5, initial_delay=2):
        """Intenta reconectar el WebSocket con un backoff exponencial."""
        if self.is_connected or self.is_connecting:
            self.log_debug("[INFO] Reconexión no necesaria.")
            return

        attempt = 0
        delay = initial_delay

        while attempt < max_attempts:
            self.log_debug(f"[INFO] Intentando reconectar... Intento {attempt + 1}/{max_attempts}")
            try:
                self.start()  # Llamar a la conexión
                if self.is_connected:
                    self.log_debug("[INFO] Reconexión exitosa.")
                    return
            except Exception as e:
                self.log_debug(f"[ERROR] Error durante la reconexión: {e}")

            attempt += 1
            self.log_debug(f"[INFO] Esperando {delay} segundos antes del próximo intento.")
            time.sleep(delay)
            delay *= 2  # Incremento exponencial del retraso

        self.log_debug("[ERROR] No se pudo reconectar después de múltiples intentos.")



    def add_epic(self, epic):
        """Agrega un epic a la lista de suscripciones activas."""
        if epic not in self.active_epics:
            self.active_epics.append(epic)
            self.send_subscription_update()  # Enviar suscripciones actualizadas
            if self.sync_tickers_callback:
                self.sync_tickers_callback()  # Notificar a MarketSearchApp
        else:
            self.log_debug(f"[INFO] El epic '{epic}' ya está en la lista.")


    def remove_epic(self, epic):
        """Elimina un epic y detiene su hilo de análisis de forma segura."""
        if epic in self.saved_epics:
            self.saved_epics.remove(epic)
            self.save_epics_to_file()

            # Detener y eliminar el hilo asociado al epic
            if epic in self.app.threads:
                thread = self.app.threads.pop(epic)
                if thread.isRunning():  # Verifica si el hilo sigue activo
                    thread.stop()  # Detener el hilo
                    thread.wait()  # Asegura que termine
                    self.app.append_to_debug_area(f"[INFO] Hilo detenido para {epic}.")

            # Eliminar suscripción del WebSocketManager
            if epic in self.app.websocket_manager.active_epics:
                self.app.websocket_manager.active_epics.remove(epic)
                self.app.websocket_manager.send_subscription_update()
                self.app.append_to_debug_area(f"[INFO] Suscripción eliminada para {epic}.")

            # Eliminar widgets y botones
            if epic in self.app.ticker_widgets:
                widget_info = self.app.ticker_widgets.pop(epic)
                widget_frame = widget_info["frame"]
                self.app.result_area_layout.removeWidget(widget_frame)
                widget_frame.deleteLater()
                self.app.append_to_debug_area(f"[INFO] Widget eliminado para {epic}.")

            for i in range(self.app.result_area_layout.count()):
                widget = self.app.result_area_layout.itemAt(i).widget()
                if widget and widget.objectName() == epic:
                    self.app.result_area_layout.removeWidget(widget)
                    widget.deleteLater()
                    self.app.append_to_debug_area(f"[INFO] Botón eliminado para {epic}.")
                    break

            return True

        self.app.append_to_debug_area(f"[WARNING] Epic {epic} no encontrado.")
        return False

    def update_subscriptions(self):
        """Envía todas las suscripciones activas al servidor."""
        if not self.is_connected:
            self.log_debug("[ERROR] WebSocket no conectado. Intentando reconectar...")
            self.reconnect()
            return

        if not self.active_epics:
            self.log_debug("[INFO] No hay epics para suscribirse.")
            return

        payload = {
            "destination": "marketData.subscribe",
            "correlationId": str(int(time.time())),
            "cst": self.cst_token,
            "securityToken": self.security_token,
            "payload": {"epics": self.active_epics}
        }

        try:
            self.ws.send(json.dumps(payload))  # Enviar suscripciones
            self.log_debug(f"[INFO] Suscripciones enviadas: {self.active_epics}")
        except Exception as e:
            self.log_debug(f"[ERROR] No se pudieron enviar las suscripciones: {e}")

class IndicatorThread(QThread):
    def __init__(self, ticker, data_folder="./Reports/"):
        super().__init__()
        self.ticker = ticker
        self.data_folder = data_folder
        self._is_running = True

    def run(self):
        while self._is_running:
            try:
                self.manager.download_data_to_json(self.ticker)
            except Exception as e:
                self.progress_signal.emit(f"[ERROR] {e}")
            finally:
                self.sleep(60)


    def stop(self):
        """Detiene el hilo de forma segura."""
        self._is_running = False
        self.quit()
        self.wait()  # Asegura que el hilo termine antes de continuar
    def __init__(self, data_folder="./Reports/"):
        self.data_folder = data_folder

    def calculate(self, ticker):
        """
        Realiza el cálculo de indicadores técnicos (MACD, RSI, ATR).
        """
        try:
            # Cargar datos históricos
            historical_data = self._load_data(f"{ticker}_historical.json")

            # Cargar datos actuales
            current_data = self._load_data(f"{ticker}_current.json")

            # Fusionar datos históricos y actuales
            if historical_data is None or current_data is None:
                return ticker, "Error: Datos no disponibles"

            data = pd.concat([historical_data, current_data], ignore_index=True)

            # Calcular indicadores
            macd_condition, rsi_condition, atr_condition = self._calculate_indicators(data)

            # Generar el mensaje del estado de los indicadores
            indicator_status = f"MACD: {macd_condition} | RSI: {rsi_condition} | ATR: {atr_condition}"
            return ticker, indicator_status
        except Exception as e:
            return ticker, f"[ERROR] {str(e)}"

    def _load_data(self, file_name):
        """
        Carga datos desde un archivo JSON y los convierte a un DataFrame.
        """
        file_path = os.path.join(self.data_folder, file_name)
        if not os.path.exists(file_path):
            print(f"[ERROR] El archivo {file_name} no existe.")
            return None

        try:
            with open(file_path, "r") as file:
                data = json.load(file)
            return pd.DataFrame(data)
        except Exception as e:
            print(f"[ERROR] Error al cargar datos desde {file_name}: {e}")
            return None

    def _calculate_indicators(self, data):
        """
        Calcula MACD, RSI, y ATR para los datos proporcionados.
        """
        # Verificar que los datos contengan las columnas necesarias
        required_columns = ['Close', 'High', 'Low']
        if not all(col in data.columns for col in required_columns):
            raise ValueError("Faltan columnas necesarias en los datos.")

        # Calcular MACD
        fast, slow, signal_period = 12, 26, 9
        data['EMA_fast'] = data['Close'].ewm(span=fast, adjust=False).mean()
        data['EMA_slow'] = data['Close'].ewm(span=slow, adjust=False).mean()
        data['MACD'] = data['EMA_fast'] - data['EMA_slow']
        data['Signal'] = data['MACD'].ewm(span=signal_period, adjust=False).mean()
        macd_condition = '✔' if data['MACD'].iloc[-1] > data['Signal'].iloc[-1] else '✖'

        # Calcular RSI
        rsi_window = 14
        delta = data['Close'].diff()
        up = delta.clip(lower=0)
        down = -delta.clip(upper=0)
        roll_up = up.rolling(window=rsi_window, min_periods=1).mean()
        roll_down = down.rolling(window=rsi_window, min_periods=1).mean()
        RS = roll_up / roll_down
        data['RSI'] = 100 - (100 / (1 + RS))
        rsi_condition = '✔' if data['RSI'].iloc[-1] < 30 else '✖'

        # Calcular ATR
        atr_window = 14
        data['TR'] = pd.concat([
            data['High'] - data['Low'],
            abs(data['High'] - data['Close'].shift()),
            abs(data['Low'] - data['Close'].shift())
        ], axis=1).max(axis=1)
        data['ATR'] = data['TR'].rolling(window=atr_window, min_periods=1).mean()
        atr_condition = '✔' if data['ATR'].iloc[-1] > data['ATR'].mean() else '✖'

        return macd_condition, rsi_condition, atr_condition

class EpicManager:
    def __init__(self, app, file_path="Reports/saved_epics.json"):
        self.app = app  # Referencia a la aplicación principal
        self.file_path = file_path
        self.saved_epics = []
        self.load_epics_from_file()



    def add_epic(self, epic):
        """Agrega un epic a la lista, actualiza las suscripciones y guarda en el archivo."""
        if epic not in self.saved_epics:
            self.saved_epics.append(epic)
            self.save_epics_to_file()

            # Delegar al WebSocketManager para actualizar suscripciones
            self.app.websocket_manager.add_epic(epic)
            return True
        return False

    def remove_epic(self, epic):
        """Elimina un epic y detiene su hilo de análisis de forma segura."""
        if epic in self.saved_epics:
            self.saved_epics.remove(epic)
            self.save_epics_to_file()

            # Detener y eliminar el hilo asociado al epic
            if epic in self.app.threads:
                thread = self.app.threads.pop(epic)
                if thread.isRunning():  # Verifica si el hilo sigue activo
                    thread.stop()  # Detener el hilo
                    thread.wait()  # Asegura que termine
                    self.app.append_to_debug_area(f"[INFO] Hilo detenido para {epic}.")

            # Eliminar suscripción del WebSocketManager
            if epic in self.app.websocket_manager.active_epics:
                self.app.websocket_manager.active_epics.remove(epic)
                self.app.websocket_manager.send_subscription_update()
                self.app.append_to_debug_area(f"[INFO] Suscripción eliminada para {epic}.")

            # Eliminar widgets y botones
            if epic in self.app.ticker_widgets:
                widget_info = self.app.ticker_widgets.pop(epic)
                widget_frame = widget_info["frame"]
                self.app.ticker_widgets_container.removeWidget(widget_frame)
                widget_frame.deleteLater()
                self.app.append_to_debug_area(f"[INFO] {epic} eliminado de ticker_widgets.")

            for i in range(self.app.result_area_layout.count()):
                widget = self.app.result_area_layout.itemAt(i).widget()
                if widget and widget.objectName() == epic:
                    self.app.result_area_layout.removeWidget(widget)
                    widget.deleteLater()
                    self.app.append_to_debug_area(f"[INFO] Botón eliminado para {epic}.")
                    break

            return True

        self.app.append_to_debug_area(f"[WARNING] Epic {epic} no encontrado.")
        return False



    def get_saved_epics(self):
        """Devuelve la lista de epics guardados."""
        return self.saved_epics

    def save_epics_to_file(self):
        """Guarda la lista de epics en un archivo JSON."""
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)  # Crear directorio si no existe
        with open(self.file_path, "w") as file:
            json.dump(self.saved_epics, file, indent=4)

    def load_epics_from_file(self):
        """Carga la lista de epics desde un archivo JSON."""
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as file:
                self.saved_epics = json.load(file)
        else:
            self.saved_epics = []



class DataInitializationThread(QThread):
    progress_signal = pyqtSignal(str)  # Señal para actualizar la interfaz con el progreso
    finished_signal = pyqtSignal(str)  # Señal para notificar finalización

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._is_running = True  # Atributo para controlar el estado del hilo

    def run(self):
        """Realiza la inicialización de datos en un hilo separado."""
        for epic in self.app.epic_manager.get_saved_epics():
            if not self._is_running:  # Verificar si el hilo fue detenido
                self.progress_signal.emit("[INFO] Inicialización cancelada.")
                return
            try:
                self.progress_signal.emit(f"[INFO] Descargando datos para {epic}...")
                self.app.historical_manager.download_data_to_json(epic)
                self.progress_signal.emit(f"[INFO] Descarga completada para {epic}.")
            except Exception as e:
                self.progress_signal.emit(f"[ERROR] Error al descargar datos para {epic}: {e}")
                # Dependiendo de la lógica, podrías decidir continuar o detenerse aquí
                continue  # Continúa con el siguiente epic en caso de error

            # Implementar una pausa de 40 segundos de manera interrumpible
            self.progress_signal.emit("[INFO] Pausando por 40 segundos antes del siguiente epic...")
            for _ in range(40):
                if not self._is_running:
                    self.progress_signal.emit("[INFO] Inicialización cancelada durante la pausa.")
                    return
                QThread.sleep(1)  # Pausa de 1 segundo

        self.progress_signal.emit("[INFO] Descarga completada para todos los epics.")
        self.finished_signal.emit("[INFO] Inicialización completada.")

    def stop(self):
        """Detiene el hilo de manera segura."""
        self._is_running = False
        self.quit()
        self.wait()



class MarketSearchApp(QWidget):
    def __init__(self, capital_ops, account_id, parent=None):
        super().__init__(parent)  # Llamar al constructor base primero

        # Inicializar atributos esenciales
        self.capital_ops = capital_ops  # Usar la instancia pasada como argumento
        self.account_id = account_id
        self.positions_thread = PositionsThread(capital_ops, account_id)
        self.positions_thread.positions_ready.connect(self.update_operations_table)
        self.positions_thread.start()

        # Atributos para gestionar hilos y estado
        self.opportunity_thread = None
        self.download_threads = {}
        self.threads = {}
        self.is_initialized = False  # Bandera para verificar inicialización

        # Atributos para la interfaz y resultados
        self.result_overlay = None
        self.ticker_widgets = {}
        self.vumeter_widgets = {}

        # Inicializar tokens
        self.cst_token = None
        self.x_security_token = None

        # Inicializar la interfaz y componentes relacionados
        self.initUI()
        self.epic_manager = EpicManager(app=self)  # Pasar la referencia de esta instancia
        self.initialize_result_area()


        # Primero inicializamos WebSocketManager
        self.websocket_manager = WebSocketManager(
            url="wss://api-streaming-capital.backend-capital.com/connect",
            api_key=API_KEY,
            debug_callback=self.append_to_debug_area,
            update_price_callback=self.update_price,
            sync_tickers_callback=self.sync_active_tickers
        )


        # Inicia sesión y establece el WebSocket
        balance, currency = self.websocket_manager.start(LOGIN, PASSWORD)
        if balance is not None:
            self.update_saldo_label(balance, currency)
        else:
            self.append_to_debug_area("[ERROR] No se pudo iniciar sesión. Verifica tus credenciales.")


        # Inicializar otras clases
        self.historical_manager = HistoricalDataManager(data_dir="Reports")
        self.threads = {}
        self.load_epics()

        # Ejecutar la inicialización en segundo plano
        self.init_thread = DataInitializationThread(self)
        self.init_thread.finished_signal.connect(self.handle_thread_completion)
        self.init_thread.start()

        # Configurar un temporizador para hacer la descarga periódica
        self.download_timer = QTimer(self)
        self.download_timer.timeout.connect(self.trigger_periodic_download)
        self.download_timer.start(20000)  # Establece el intervalo de 1 hora (en milisegundos)
        # Aquí es donde debes llamar explícitamente a `setup_periodic_analysis`
        self.setup_periodic_analysis()  # Esto inicia el análisis periódico



    def update_operations_table(self, serialized_positions):
        """Actualiza la tabla de operaciones en la interfaz."""
        print("[INFO] Actualizando tabla de operaciones...")
        for position in serialized_positions:
            print(position)  # Aquí puedes agregar lógica para actualizar una tabla en la GUI

    def setup_periodic_analysis(self):
        """Configura el QTimer para ejecutar el análisis para todos los tickers periódicamente."""
        # Ejecutar el análisis por primera vez para todos los tickers
        self.run_periodic_analysis()

        # Crear QTimer para ejecutar el análisis cada 10 segundos
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.run_periodic_analysis)  # Llamar al análisis periódicamente
        self.timer.start(100000)  #

        self.append_to_debug_area("[INFO] Análisis periódico iniciado.")


    def run_periodic_analysis(self):
        """Ejecuta el análisis para todos los tickers periódicamente."""
        for ticker, widget_info in self.ticker_widgets.items():
            try:
                analysis_manager = TechnicalAnalysis(
                    data_dir="Reports",
                    ticker=ticker,
                    content_widgets=widget_info["content_widgets"],
                    circle_widgets=widget_info["circle_widgets"],
                    vumeter_widgets=self.vumeter_widgets,
                    interval=50000
                )
                analysis_manager.start_analysis()
                self.append_to_debug_area(f"[INFO] Análisis completado para {ticker}.")
            except Exception as e:
                self.append_to_debug_area(f"[ERROR] Error en análisis para {ticker}: {e}")


    def trigger_periodic_download(self):
        for epic in self.epic_manager.get_saved_epics():
            if epic not in self.download_threads:  # Crear un hilo solo si no existe
                thread = DownloadThread(self.historical_manager, epic)
                thread.progress_signal.connect(self.append_to_debug_area)
                thread.finished_signal.connect(lambda msg, e=epic: self.handle_thread_completion(msg, e))
                self.download_threads[epic] = thread
                thread.start()


    def start_repulser_thread(self, radar_data=None):
        """Inicia el hilo del Repulser."""
        if hasattr(self, 'repulser_thread') and self.repulser_thread and self.repulser_thread.isRunning():
            self.append_to_debug_area("[WARNING] El hilo de Repulser ya está en ejecución.")
            return

        # Crear el hilo del Repulser
        self.repulser_thread = RepulserThread(radar_data, self.repulser_view)
        self.repulser_thread.progress_signal.connect(self.append_to_debug_area)
        self.repulser_thread.update_signal.connect(self.on_repulser_updated)
        self.repulser_thread.start()

    def on_repulser_updated(self, processed_data):
        """Maneja los resultados del cálculo y actualiza el Repulser."""
        self.repulser_view.scene.clear()

        # Dibujar nodos con las oportunidades calculadas
        for ticker, result in processed_data.items():
            opportunity_score = result["opportunity_score"]
            details = result["details"]
            self.repulser_view.create_node(ticker, opportunity_score, details)

        self.append_to_debug_area("[INFO] Repulser actualizado con nuevas oportunidades.")



    def handle_thread_completion(self, message):
        """Maneja la finalización del hilo secundario."""
        self.append_to_debug_area(message)
        self.append_to_debug_area("[INFO] Ahora puedes usar la interfaz sin problemas.")

    def on_initialization_complete(self, message):
        """Marcamos como completa la inicialización y permitimos el análisis."""
        self.is_initialized = True
        self.append_to_debug_area(message)
        self.append_to_debug_area("[INFO] Ahora puedes usar la interfaz sin problemas.")

        # Iniciar análisis para todos los epics disponibles
        self.start_analysis_for_all_epics()

    def initUI(self):
        """Configura la interfaz gráfica del usuario."""
        self.setup_window()
        self.setup_debug_area()
        self.setup_saldo_label()  # Configuramos el label del saldo
        self.setup_search_area()
        self.setup_result_area()
        self.setup_tabs()
        self.setup_result_overlay()  # Nuevo método para configurar el layout superpuesto
        self.setup_bottom_left_panel()
        self.positions_thread.positions_ready.connect(self.update_operations_table)


    def initialize_classes(self):
        """Inicializa las clases auxiliares utilizadas por la aplicación."""
        self.historical_manager = HistoricalDataManager(data_dir="Reports")
        self.websocket_manager = WebSocketManager(
            url="wss://api-streaming-capital.backend-capital.com/connect",
            api_key=API_KEY,
            debug_callback=self.append_to_debug_area,
            update_price_callback=self.update_price
        )
        self.epic_manager = EpicManager()  # Asegúrate de inicializar esta clase
        self.threads = {}

    def update_price(self, epic, price):
        """Actualiza el precio del epic correspondiente en la interfaz."""
        formatted_price = "{:,.2f}".format(price).replace(",", ".")  # Formatea el precio
        for i in range(self.result_area_layout.count()):
            widget = self.result_area_layout.itemAt(i).widget()
            if widget and widget.objectName() == epic:
                widget.setText(f"{epic}: {formatted_price}")  # Actualiza el texto del botón
                return
        # Si no se encuentra el epic, lo registramos como advertencia.
        self.append_to_debug_area(f"[WARNING] No se encontró widget para el epic {epic}.")

    def sync_active_tickers(self):
        """Sincroniza los tickers activos con los widgets."""
        for ticker in self.websocket_manager.active_epics:
            if ticker not in self.ticker_widgets:  # Verificar en el diccionario
                self.add_ticker_widget(ticker)  # Crea un widget para el ticker activo

    def load_epics(self):
        """Carga los epics guardados y suscribe al WebSocket."""
        self.epic_manager.load_epics_from_file()
        for epic in self.epic_manager.get_saved_epics():
            self.update_result_area(epic)  # Dibuja en la interfaz
            self.websocket_manager.add_epic(epic)  # Agrega y actualiza suscripciones

    def setup_window(self):
        """Configura las propiedades principales de la ventana."""
        self.setWindowTitle("Market Search")
        self.setGeometry(100, 100, 1024, 740)
        self.setStyleSheet("""
            background-color: #0f0f0f;
            color: white;
            font-family: Arial;
        """)

    @staticmethod
    def call_historical_indicators():
        """
        Llama a HIstoricalINdicators.py al iniciar el programa.
        """
        try:
            script_path = os.path.join(os.getcwd(), "HIstoricalINdicators.py")
            python_exec = sys.executable  # Usar el mismo ejecutable de Python actual

            print(f"[INFO] Ejecutando el script {script_path}...")
            result = subprocess.run(
                [python_exec, script_path],
                check=True,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                print("[INFO] Script HIstoricalINdicators.py ejecutado exitosamente.")
                print(result.stdout)
            else:
                print(f"[ERROR] Fallo al ejecutar el script: {result.stderr}")

        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Error al ejecutar HIstoricalINdicators.py: {e}")
            print(f"[DEBUG] Salida estándar:\n{e.stdout}")
            print(f"[DEBUG] Error estándar:\n{e.stderr}")
        except Exception as e:
            print(f"[ERROR] Error inesperado al ejecutar HIstoricalINdicators.py: {e}")

    def setup_debug_area(self):
        """Crea el área de depuración para mensajes de log."""
        self.debug_area = QTextEdit(self)
        self.debug_area.setReadOnly(True)
        self.debug_area.setGeometry(20, 20, 360, 50)
        self.debug_area.setStyleSheet("""
            background-color: #1c1c1c;
            color: white;
            padding: 10px;
            font-size: 10px;
            border: 1px solid #4caf50;
        """)
        self.debug_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # Deshabilitar barra vertical
        self.debug_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # Deshabilitar barra horizontal

    def setup_search_area(self):
        """Crea la barra de búsqueda."""
        self.search_field = QLineEdit(self)
        self.search_field.setPlaceholderText("Escribe un término de búsqueda (e.g., Bitcoin, Tesla)...")
        self.search_field.setGeometry(20, 80, 300, 40)
        self.search_field.setStyleSheet("""
            padding: 10px;
            background-color: #1c1c1c;
            color: white;
            border: 2px solid #4caf50;
        """)
        self.search_field.returnPressed.connect(self.search_market)

        self.search_button = QPushButton("Buscar", self)
        self.search_button.setGeometry(340, 80, 100, 40)
        self.search_button.setStyleSheet("""
            padding: 10px;
            background-color: #4caf50;
            color: black;
            font-weight: bold;
        """)
        self.search_button.clicked.connect(self.search_market)

    def setup_saldo_label(self):
        """Crea el label para mostrar el saldo debajo del área de depuracsetup_result_areaión."""
        self.saldo_label = QLabel(self)
        self.saldo_label.setGeometry(520, 100, 200, 40)  # Posicionamos en el lado derecho, debajo del área de depuración
        self.saldo_label.setStyleSheet("""
            background-color: #4caf50;
            color: black;
            font-size: 14px;
            font-weight: bold;
            padding: 5px;
            border-radius: 1px;
        """)
        self.saldo_label.setText("\U0001F4B0 Saldo: Calculando...")  # Texto inicial

    def initialize_result_area(self):
        """Inicializa el área de resultados con los epics guardados."""
        for epic in self.epic_manager.get_saved_epics():
            self.update_result_area(epic)  # Usa la lógica de verificación en update_result_area

    def setup_result_area(self):
        """Configura el área de resultados, añadiendo Repulser y el panel de Gemini."""
        # Configuración del área de resultados
        self.result_area = QFrame(self)
        self.result_area.setGeometry(520, 143, 200, 377)
        self.result_area_layout = QVBoxLayout(self.result_area)
        self.result_area_layout.setContentsMargins(10, 10, 10, 10)
        self.result_area_layout.setSpacing(5)  # Espaciado entre botones
        self.result_area.setStyleSheet("""
            background-color: #1c1c1c;
            border: 2px solid #4caf50;
        """)

        # Importar y configurar Repulser (radar)
        from repulser import MarketFlow  # Asegúrate de que la clase MarketFlow es tu radar
        self.repulser_view = MarketFlow(self)
        self.repulser_view.setGeometry(720, 10, 300, 300)  # Colocar en la esquina superior derecha
        self.repulser_view.setStyleSheet("""
            border: 2px solid #4caf50;
            background-color: black;
        """)
        self.repulser_view.show()  # Asegúrate de que sea visible

        # Panel de chat de Gemini
        from gemini import GeminiChatPanel
        self.chat_panel = GeminiChatPanel(self)
        self.chat_panel.setGeometry(710, 310, 317, 337)  # Colocar debajo del radar
        self.chat_panel.setStyleSheet("""
            background-color: #333;
            border: 2px solid #4caf50;
        """)


    def update_result_area(self, epic):
        """Actualiza el área de resultados con un nuevo epic, evitando duplicados."""
        # Verificar si ya existe un botón con el nombre de objeto igual al epic
        for i in range(self.result_area_layout.count()):
            widget = self.result_area_layout.itemAt(i).widget()
            if widget and widget.objectName() == epic:
                self.append_to_debug_area(f"[INFO] Botón ya existe para {epic}, no se agrega de nuevo.")
                return  # No agregar duplicados

        # Crear un nuevo botón si no existe
        button = QPushButton(f"{epic}: Cargando precio...", self.result_area)
        button.setFixedSize(180, 40)  # Establecer tamaño fijo (ancho x alto)
        button.setStyleSheet("""
            background-color: #2e7d32;
            color: white;
            font-weight: bold;
            border-radius: 5px;
            text-align: center;
        """)
        button.setObjectName(epic)  # Usar el epic como nombre del objeto para referencias rápidas
        button.setCursor(Qt.PointingHandCursor)  # Cambiar el cursor al pasar sobre el botón
        button.clicked.connect(lambda: self.append_to_debug_area(f"[INFO] Epic Borrado {epic}"))
        button.clicked.connect(lambda: self.epic_manager.remove_epic(epic))

        # Agrega el botón al layout
        self.result_area_layout.addWidget(button)
        self.append_to_debug_area(f"[INFO] Botón creado para {epic}.")

    def setup_tabs(self):
        """Crea las pestañas laterales."""
        self.left_panel = QTabWidget(self)
        self.left_panel.setGeometry(20, 120, 500, 300)
        self.left_panel.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #4caf50; background: #1c1c1c; }
            QTabBar::tab { background: #1c1c1c; color: white; padding: 5px; }
            QTabBar::tab:selected { background: #4caf50; color: black; }
        """)

        self.setup_technical_tab()
        self.add_radar_tab()

    def add_settings_tab(self):
        """Set up the Visor Técnico tab layout and widgets."""
        self.settings_tab = QWidget()
        self.visor_layout = QVBoxLayout(self.settings_tab)

        # Container for ticker widgets
        self.ticker_widgets_container = QVBoxLayout()
        self.visor_layout.addLayout(self.ticker_widgets_container)

        # Placeholder instruction label
        instruction_label = QLabel("Añade un ticker para comenzar el análisis.")
        instruction_label.setStyleSheet("font-size: 14px; color: white;")
        self.visor_layout.addWidget(instruction_label)

        # Add the tab
        self.left_panel.addTab(self.settings_tab, "Visor Técnico")

    def setup_bottom_left_panel(self):
        """Configura el panel de operaciones en la esquina inferior izquierda con diseño minimalista."""
        self.bottom_left_panel = QFrame(self)
        self.bottom_left_panel.setGeometry(20, 460, 685, 150)  # Ajustar tamaño según sea necesario
        self.bottom_left_panel.setStyleSheet("""
            background-color: #212121;  /* Fondo oscuro minimalista */
            border: 1px solid #4caf50;  /* Borde fino y limpio */
            border-radius: 5px;
        """)

        # Configurar tabla de operaciones
        self.operations_table = QTableWidget(self.bottom_left_panel)
        self.operations_table.setGeometry(5, 5, 675, 140)  # Espacio reducido al borde del panel
        self.operations_table.setColumnCount(8)
        self.operations_table.setHorizontalHeaderLabels([
            "Instrumento", "Tipo", "Dirección", "Tamaño", "Precio Apertura", "Gan/Pérdida", "Moneda" , "Take Profit"
        ])
        self.operations_table.setStyleSheet("""
            QTableWidget { 
                background-color: #2b2b2b; /* Fondo más oscuro para filas */
                color: white; 
                font-size: 11px;  /* Tamaño de fuente más pequeño */
                gridline-color: #444;  /* Color sutil para líneas de celdas */
            }
            QHeaderView::section { 
                background-color: #333;  /* Fondo de encabezado neutro */
                color: #ffffff;  /* Texto blanco */
                font-weight: normal;  /* Sin negrita para minimalismo */
                border: none;  /* Sin bordes */
                padding: 4px;
            }
            QTableWidget::item { 
                border: none;  /* Sin bordes entre celdas */
                padding: 2px;
            }
            QTableWidget::item:selected { 
                background-color: #4caf50;  /* Color verde suave para selección */
                color: black;
            }
        """)
        self.operations_table.horizontalHeader().setStretchLastSection(True)  # Estira la última columna
        self.operations_table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)  # Alineación centrada de los encabezados
        self.operations_table.setEditTriggers(QTableWidget.NoEditTriggers)  # Evita edición
        self.operations_table.verticalHeader().setVisible(False)  # Ocultar el índice de fila
        self.operations_table.setAlternatingRowColors(False)  # Evitar colores alternados para simplicidad
        self.operations_table.setSelectionBehavior(QTableWidget.SelectRows)  # Selección por fila
        self.operations_table.setSelectionMode(QTableWidget.SingleSelection)  # Selección única

        # Configuración inicial
        self.refresh_positions()

        # Temporizador para actualizar posiciones
        self.update_operations_timer = QTimer()
        self.update_operations_timer.timeout.connect(self.refresh_positions)
        self.update_operations_timer.start(3000)  # Cada 60 segundos


    def refresh_positions(self):
        """
        Inicia el proceso de actualización de posiciones usando PositionsThread.
        """
        try:
            print("[INFO] Iniciando la actualización de posiciones en el hilo...")
            self.positions_thread.positions_ready.connect(self.update_operations_table)
            self.positions_thread.start()
        except Exception as e:
            print(f"[ERROR] Fallo al iniciar el hilo de posiciones: {e}")


    def update_operations_table(self, operations):
        """
        Actualiza la tabla de operaciones en la interfaz.
        Si no hay posiciones, muestra un mensaje en la consola y limpia la tabla.
        """
        if not operations:
            print("[INFO] No hay posiciones abiertas.")
            self.operations_table.setRowCount(0)  # Limpiar la tabla
            return

        self.operations_table.setRowCount(len(operations))  # Ajustar el número de filas
        for row_idx, operation in enumerate(operations):
            self.operations_table.setItem(row_idx, 0, QTableWidgetItem(operation.get("instrument", "N/A")))
            self.operations_table.setItem(row_idx, 0, QTableWidgetItem(operation.get("instrument", "N/A")))
            self.operations_table.setItem(row_idx, 1, QTableWidgetItem(operation.get("type", "N/A")))
            self.operations_table.setItem(row_idx, 2, QTableWidgetItem(operation.get("direction", "N/A")))
            self.operations_table.setItem(row_idx, 3, QTableWidgetItem(str(operation.get("size", "N/A"))))
            self.operations_table.setItem(row_idx, 4, QTableWidgetItem(str(operation.get("level", "N/A"))))
            self.operations_table.setItem(row_idx, 5, QTableWidgetItem(str(operation.get("upl", "N/A"))))
            self.operations_table.setItem(row_idx, 6, QTableWidgetItem(operation.get("currency", "N/A")))
            self.operations_table.setItem(row_idx, 7, QTableWidgetItem(str(operation.get("take_profit", "N/A"))))  # Nueva columna para TP
            self.operations_table.setColumnWidth(0, 60)  # Ancho fijo para la primera columna
            self.operations_table.setColumnWidth(1, 50)   # Ancho fijo para la segunda columna
            self.operations_table.setColumnWidth(2, 50)   # Ancho fijo para la segunda columna
            self.operations_table.setColumnWidth(3, 50)   # Ancho fijo para la segunda columna
            self.operations_table.setColumnWidth(3, 50)   # Ancho fijo para la segunda columna




    def setup_technical_tab(self):
        """Configura la pestaña Visor Técnico con un QGridLayout."""
        self.technical_tab = QWidget()
        self.ticker_widgets_container = QGridLayout()  # Set to QGridLayout
        self.ticker_widgets_container.setSpacing(0)  # Espaciado entre elementos
        self.technical_tab.setLayout(self.ticker_widgets_container)
        self.left_panel.addTab(self.technical_tab, "Visor Técnico")

    def add_ticker_widget(self, ticker):
        """Crea y añade un widget independiente para un ticker en la pestaña Visor Técnico."""
        transformed_ticker = self.historical_manager.transform_ticker_for_yf(ticker)

        if transformed_ticker in self.ticker_widgets:
            self.append_to_debug_area(f"[INFO] Procesando {transformed_ticker} Existente")
            return  # Evitar duplicados

        # Crear el marco principal del widget
        ticker_frame = QFrame()
        ticker_frame.setStyleSheet("""
            background-color: #1c1c1c;
            border: 1px solid #4caf50;
            border-radius: 5px;
            margin: 2px;
            padding: 2px;
        """)
        ticker_frame.setFixedSize(155, 120)

        # Layout horizontal principal
        main_layout = QHBoxLayout(ticker_frame)

        # Crear el vúmetro (lado izquierdo)
        vumeter = VuMeterWidget(max_steps=10)
        vumeter.setFixedWidth(20)  # Ajustar a una apariencia angosta
        self.vumeter_widgets[transformed_ticker] = vumeter
        main_layout.addWidget(vumeter)  # Añadir el vúmetro a la izquierda

        # Layout vertical para los indicadores
        ticker_layout = QVBoxLayout()
        main_layout.addLayout(ticker_layout)

        # Etiqueta para mostrar el título (ticker)
        title_label = QLabel(f"<b>{transformed_ticker}</b>")
        title_label.setStyleSheet("color: white; font-size: 10px; text-align: center;")
        ticker_layout.addWidget(title_label)

        # Crear un layout para cada indicador (texto a la izquierda, círculo a la derecha)
        def create_indicator_row(label_text):
            row_layout = QHBoxLayout()
            label = QLabel(label_text)
            label.setStyleSheet("color: white; font-size: 10px;")
            circle = CircleWidget("white")  # Círculo inicial en blanco
            circle.setFixedSize(10, 10)  # Tamaño del círculo
            row_layout.addWidget(label)
            row_layout.addStretch()
            row_layout.addWidget(circle)
            return row_layout, label, circle

        # Crear fila para RSI
        rsi_row, rsi_label, circle_rsi = create_indicator_row("RSI: -")
        ticker_layout.addLayout(rsi_row)

        # Crear fila para MACD
        macd_row, macd_label, circle_macd = create_indicator_row("MACD: -")
        ticker_layout.addLayout(macd_row)

        # Crear fila para Volumen
        volume_row, volume_label, circle_volume = create_indicator_row("Volumen: -")
        ticker_layout.addLayout(volume_row)

        # Guardar referencias de widgets para actualizaciones futuras
        self.ticker_widgets[transformed_ticker] = {
            "frame": ticker_frame,
            "content_widgets": {
                "rsi_label": rsi_label,
                "macd_label": macd_label,
                "volume_label": volume_label,
            },
            "circle_widgets": {
                "rsi": circle_rsi,
                "macd": circle_macd,
                "volume": circle_volume,
            },
        }

        # Añadir el widget al layout principal
        current_count = len(self.ticker_widgets)
        row = (current_count - 1) // 3
        col = (current_count - 1) % 3
        self.ticker_widgets_container.addWidget(ticker_frame, row, col)

        # Crear e iniciar el análisis técnico
        analysis_manager = TechnicalAnalysis(
            data_dir="Reports",
            ticker=transformed_ticker,  # Pasa el ticker transformado
            content_widgets=self.ticker_widgets[transformed_ticker]["content_widgets"],
            circle_widgets=self.ticker_widgets[transformed_ticker]["circle_widgets"],
            vumeter_widgets=self.vumeter_widgets,
            interval=10
        )

        analysis_manager.start_analysis()

        # Guardar el epic en la lista persistente
        self.epic_manager.add_epic(ticker)

    # 2. Función para ejecutar Repulser.py al iniciar la aplicación
    def start_repulser_on_start(self):
        self.repulser_thread = RepulserThread()  # Crear el hilo para Repulser
        self.repulser_thread.data_ready.connect(self.update_radar_tab)  # Conectar la señal para actualizar la pestaña Radar
        self.repulser_thread.start()  # Iniciar el hilo en segundo plano

    def add_radar_tab(self):
        """Configura la pestaña Radar con el radar generado por MarketFlow."""
        self.info_tab = QWidget()  # Creamos el widget de la pestaña



    def append_to_debug_area(self, message, log_to_terminal=True):
        """Agrega mensajes al área de depuración y asegura que siempre esté desplazada al final."""
        self.debug_area.append(message)
        if log_to_terminal:
            print(message)

    def update_indicator_labels(self, ticker, result="Cargando indicadores..."):
        """Actualiza la etiqueta del indicador asociado a un epic."""
        label = self.get_label_for_ticker(ticker)
        if label:
            label.setText(f"{ticker}: {result}")
        else:
            self.append_to_debug_area(f"[WARNING] No se encontró etiqueta para {ticker}. Considere crearla.")

    def get_label_for_ticker(self, ticker):
        """Devuelve el QLabel asociado a un ticker, si existe."""
        return self.findChild(QLabel, ticker)

    def update_saldo_label(self, available_balance, currency_iso_code):
        """
        Actualiza el label del saldo con la información obtenida.
        """
        if available_balance == "Error":
            self.saldo_label.setText("\U0001F4B0 Saldo: Error")
        else:
            self.saldo_label.setText(f"\U0001F4B0 Saldo: {available_balance} {currency_iso_code}")

    def format_currency(self, amount):
        """Formatea la cantidad en un formato legible con separadores para miles y millones."""
        if amount >= 1_000_000:
            return f"{amount / 1_000_000:.2f}M"
        elif amount >= 1_000:
            return f"{amount / 1_000:.2f}K"
        else:
            return f"{amount:.2f}"

    def search_market(self):
        """Busca un mercado usando el término ingresado y muestra un panel con los resultados."""
        search_term = self.search_field.text()
        if not search_term:
            self.append_to_debug_area("[ERROR] Por favor ingresa un término de búsqueda.")
            return

        # Verificar tokens en la instancia actual de WebSocketManager
        if not self.websocket_manager.tokens_valid():
            self.append_to_debug_area("[ERROR] Tokens no disponibles. Realiza el login primero.")
            return

        try:
            headers = {
                "Content-Type": "application/json",
                "CST": self.websocket_manager.cst_token,
                "X-SECURITY-TOKEN": self.websocket_manager.security_token
            }
            market_search_url = f"{BASE_URL}{MARKET_SEARCH_ENDPOINT}?searchTerm={search_term}"
            response = requests.get(market_search_url, headers=headers)

            if response.status_code != 200:
                self.append_to_debug_area(f"[ERROR] Fallo al buscar mercados: {response.text}")
                return

            data = response.json()
            markets = data.get("markets", [])
            if not markets:
                self.append_to_debug_area(f"[INFO] No se encontraron mercados para '{search_term}'.")
                self.hide_results_overlay()  # Ocultar el overlay si no hay resultados
            else:
                results = [f"{market.get('instrumentName', 'No disponible')} ({market.get('epic', 'No disponible')})" for market in markets]
                self.append_to_debug_area(f"[INFO] Resultados encontrados: {results}")
                self.show_results_overlay(results)  # Mostrar el overlay con los resultados

        except requests.RequestException as e:
            self.append_to_debug_area(f"[ERROR] Error durante la conexión: {e}")

    def setup_result_overlay(self):
        """Configura el overlay para mostrar los resultados."""
        if self.result_overlay is None:  # Verifica si ya existe
            self.result_overlay = QFrame(self)
            self.result_overlay.setStyleSheet("""
                background-color: rgba(0, 0, 0, 0.8);
                border: 2px solid #4caf50;
                border-radius: 10px;
            """)
            self.result_overlay.setVisible(False)  # Iniciar como invisible
            self.result_overlay_layout = QVBoxLayout(self.result_overlay)
            self.result_overlay_layout.setContentsMargins(10, 10, 10, 10)

    def show_results_overlay(self, results):
            """Muestra un panel flotante con botones para los resultados de búsqueda."""
            if not self.result_overlay:  # Verifica que esté inicializado
                self.setup_result_overlay()

            # Limpia los resultados previos
            for i in reversed(range(self.result_overlay_layout.count())):
                widget = self.result_overlay_layout.takeAt(i).widget()
                if widget:
                    widget.deleteLater()

            # Agrega nuevos botones para cada resultado
            for result in results:
                button = QPushButton(result, self.result_overlay)
                button.setStyleSheet("""
                    background-color: #4caf50;
                    color: black;
                    font-weight: bold;
                    padding: 5px;
                    margin: 5px 0;
                """)
                button.clicked.connect(lambda _, r=result: self.handle_epic_selection(r))
                self.result_overlay_layout.addWidget(button)

            # Ajustar tamaño del overlay dinámicamente
            overlay_height = 50 + (len(results) * 40)
            self.result_overlay.setGeometry(20, 130, 400, min(overlay_height, 300))
            self.result_overlay.show()

    def hide_results_overlay(self):
        """Oculta el panel flotante."""
        self.result_overlay.hide()

    def mousePressEvent(self, event):
        """Oculta el overlay al hacer clic fuera."""
        if self.result_overlay.isVisible() and not self.result_overlay.geometry().contains(event.pos()):
            self.hide_results_overlay()
        super().mousePressEvent(event)
        
    def handle_ticker_analysis(self, ticker, user_message):
        """Maneja el análisis del ticker, permitiendo reprocesamiento explícito."""
        # Revisar si el ticker ya fue procesado
        if ticker in self.processed_tickers:
            # Permitir reprocesamiento si el mensaje contiene "cambio" o "reprocesar"
            if any(keyword in user_message.lower() for keyword in ["cambio", "reprocesar"]):
                self.update_chat_log(f"🔄 Reprocesando datos para {ticker} por solicitud explícita del usuario.")
            else:
                self.update_chat_log(f"⚙️ El ticker {ticker} ya fue procesado. Usa palabras como 'cambio' o 'reprocesar' para analizarlo nuevamente.")
                return

        # Cargar los datos del ticker
        data = self.load_ticker_data(ticker)
        if data:
            self.processed_tickers.add(ticker)
            self.send_data_to_gemini(ticker, data)
        else:
            self.update_chat_log(f"🔴 No se encontraron datos válidos para el ticker {ticker}. Verifica los archivos.")


    def handle_epic_selection(self, selected_epic):
        """
        Maneja la selección de un epic (instrumento), asegurando su transformación, uso consistente,
        y que se guarde correctamente en saved_epics sin guiones ni caracteres extra.
        """
        try:
            # Verificar que el WebSocketManager está inicializado
            if not hasattr(self, 'websocket_manager') or self.websocket_manager is None:
                raise AttributeError("websocket_manager no está inicializado.")

            # Extraer el ticker principal del nombre completo del epic
            if "(" in selected_epic and ")" in selected_epic:
                ticker = selected_epic.split("(")[-1].replace(")", "").strip()
            else:
                ticker = selected_epic.strip()

            # Transformar el ticker al formato estándar
            if hasattr(self.historical_manager, 'transform_ticker_for_yf'):
                transformed_epic = self.historical_manager.transform_ticker_for_yf(ticker)
                standardized_epic = transformed_epic.replace("-", "")  # Remover guiones para estandarizar el guardado
                self.append_to_debug_area(f"[DEBUG] Epic transformado: {selected_epic} -> {ticker} -> {transformed_epic} -> {standardized_epic}")
            else:
                self.append_to_debug_area(f"[ERROR] Falta la función de transformación en HistoricalDataManager.")
                return

            # Guardar el epic en saved_epics mediante EpicManager
            if not self.epic_manager.add_epic(standardized_epic):
                self.append_to_debug_area(f"[INFO] Epic '{standardized_epic}' ya estaba guardado. No se realizaron cambios.")
                return

            # Agregar el epic al WebSocketManager
            self.websocket_manager.add_epic(standardized_epic)
            self.append_to_debug_area(f"[INFO] Epic '{standardized_epic}' añadido a la lista de suscripciones.")

            # Crear botón para el epic transformado si no existe
            if standardized_epic not in self.ticker_widgets:
                self.update_result_area(standardized_epic)
            else:
                self.append_to_debug_area(f"[INFO] Botón ya existe para {standardized_epic}.")

            # Descargar datos históricos y actuales para el epic
            try:
                self.historical_manager.download_data_to_json(standardized_epic)
                self.append_to_debug_area(f"[INFO] Datos iniciales descargados para {standardized_epic}.")
            except Exception as e:
                self.append_to_debug_area(f"[ERROR] Error descargando datos para {standardized_epic}: {e}")
                return

        except AttributeError as e:
            self.append_to_debug_area(f"[ERROR] No se pudo manejar el epic '{selected_epic}': {e}")
        except Exception as e:
            self.append_to_debug_area(f"[ERROR] Error inesperado al manejar el epic '{selected_epic}': {e}")


    def remove_button_from_result_area(self, epic):
        """Elimina el botón asociado a un epic del área de resultados."""
        for i in range(self.result_area_layout.count()):
            widget = self.result_area_layout.itemAt(i).widget()
            if widget and widget.objectName() == epic:
                widget.deleteLater()
                self.append_to_debug_area(f"[INFO] Botón eliminado para {epic}.")
                break

    def closeEvent(self, event):
        """Cierra todos los hilos y temporizadores antes de salir de la aplicación."""
        print("[INFO] Cerrando aplicación y deteniendo todos los hilos...")

        # Detener el hilo de posiciones
        if self.positions_thread.isRunning():
            self.positions_thread.stop()
            self.positions_thread.wait()
            print("[INFO] Hilo de posiciones detenido.")

        # Detener el hilo de inicialización
        if self.init_thread.isRunning():
            self.init_thread.terminate()  # Terminar porque puede no tener un `stop()`
            self.init_thread.wait()
            print("[INFO] Hilo de inicialización detenido.")

        # Detener todos los hilos de descarga
        for epic, thread in self.download_threads.items():
            if thread.isRunning():
                thread.stop()
                thread.wait()
                print(f"[INFO] Hilo de descarga detenido para {epic}.")

        # Detener el hilo de Repulser
        if hasattr(self, 'repulser_thread') and self.repulser_thread.isRunning():
            self.repulser_thread.stop()
            print("[INFO] Hilo de Repulser detenido.")

        # Detener el temporizador de descargas
        if hasattr(self, 'download_timer') and self.download_timer.isActive():
            self.download_timer.stop()
            print("[INFO] Temporizador de descargas detenido.")

        # Detener el temporizador de análisis
        if hasattr(self, 'timer') and self.timer.isActive():
            self.timer.stop()
            print("[INFO] Temporizador de análisis detenido.")

        event.accept()

class PositionsThread(QThread):
    positions_ready = pyqtSignal(list)  # Señal para enviar las posiciones a la GUI
    saldo_ready = pyqtSignal(float, str)  # Señal para enviar saldo actualizado
    error_occurred = pyqtSignal(str)  # Señal para notificar errores

    def __init__(self, capital_ops, account_id):
        super().__init__()
        self.capital_ops = capital_ops
        self.account_id = account_id
        self._is_running = True

    def run(self):
        while self._is_running:
            try:
                # Obtener posiciones abiertas
                positions = self.capital_ops.get_open_positions(self.account_id)
                raw_positions = positions.get("positions", [])

                # Obtener información del saldo
                account_info = positions.get("accountInfo", {})
                available_balance = account_info.get("available", 0.0)
                currency_iso_code = account_info.get("currencyIsoCode", "N/A")

                # Emitir el saldo actualizado
                self.saldo_ready.emit(available_balance, currency_iso_code)

                # Serializar posiciones directamente dentro del hilo
                serialized_positions = self._serialize_positions(raw_positions)
                self.positions_ready.emit(serialized_positions)  # Enviar posiciones serializadas
            except Exception as e:
                error_message = f"[ERROR] Error en PositionsThread: {e}"
                print(error_message)
                self.error_occurred.emit(error_message)  # Emitir señal de error

            # Pausa en intervalos cortos para verificar _is_running
            for _ in range(30):  # Pausar por 30 segundos en intervalos de 1 segundo
                if not self._is_running:
                    return
                time.sleep(1)


    def stop(self):
        self._is_running = False
        self.quit()
        self.wait()

    def _serialize_positions(self, raw_positions):
        """
        Serializa las posiciones crudas en un formato listo para la tabla.
        """
        if not raw_positions:
            print("[DEBUG] No hay posiciones para serializar.")
            return []

        serialized = []
        for item in raw_positions:
            # Extraer datos de "position" y "market"
            position = item.get("position", {})
            market = item.get("market", {})

            # Construir una posición serializada
            serialized.append({
                "instrument": market.get("instrumentName", "N/A"),
                "epic": market.get("epic", "N/A"),
                "size": position.get("size", 0),
                "direction": position.get("direction", "N/A"),
                "level": position.get("level", 0),
                "upl": position.get("upl", 0),
                "currency": position.get("currency", "N/A"),
                "leverage": position.get("leverage", "N/A"),
                "createdDate": position.get("createdDate", "N/A"),
            })
        return serialized



class OperatorThread(QThread):
    operator_ready = pyqtSignal(object)  # Señal para indicar que el operador está listo
    error_occurred = pyqtSignal(str)     # Señal para manejar errores

    def __init__(self, model, features, strategy_params, data_file ,data_frame, scaler_stats , saldo_update_callback=None):
        super().__init__()
        self.model = model
        self.features = features
        self.strategy_params = strategy_params
        self.data_frame = data_frame
        self.saldo_update_callback = saldo_update_callback
        self.trading_operator = None  # Será inicializado en el método run
        self.data_file = data_file
        self.scaler_stats = scaler_stats  # Asegúrate de pasar scaler_stats correctamente


    def run(self):
        print(f"[DEBUG] OperatorThread running in thread: {QThread.currentThread()}")
        try:
            print("[INFO] Inicializando TradingOperator...")
            strategy = Strategia(**self.strategy_params)
            self.trading_operator = TradingOperator(
                model=self.model,
                features=self.features,
                strategy=strategy,
                saldo_update_callback=self.saldo_update_callback,
                scaler_stats=scaler_stats
            )
            self.operator_ready.emit(self.trading_operator)

            while True:
                try:
                    # Leer el archivo JSON
                    with open(self.data_file, 'r') as file:
                        raw_data = json.load(file)

                    # Verificar y cargar solo la última entrada
                    if "data" in raw_data and raw_data["data"]:
                        last_entry = raw_data["data"][-1]  # Última entrada del JSON
                        print(f"[INFO] Última entrada cargada: {last_entry}")

                        # Convertir la última entrada a un DataFrame temporal
                        last_entry_df = pd.DataFrame([last_entry])  # DataFrame de una sola fila
                        row = last_entry_df.iloc[0]  # Primera (y única) fila del DataFrame
                        print(f"[INFO] Procesando la última fila: {row.to_dict()}")

                        # Actualizar saldo y posiciones
                        balance, positions = self.trading_operator.update_balance_and_positions()

                        # Procesar posiciones abiertas
                        self.trading_operator.process_open_positions(
                            account_id=self.trading_operator.account_id,
                            capital_ops=self.trading_operator.capital_ops,
                            current_price=row["Close"],
                            features={
                                "RSI": row.get("RSI", 0),
                                "MACD": row.get("MACD", 0),
                                "ATR": row.get("ATR", 0),
                                "VolumeChange": row.get("VolumeChange", 0),
                            },
                            state=self.trading_operator.model.predict([row[self.trading_operator.features].values])[0],
                            previous_state=getattr(self.trading_operator, 'previous_state', None)
                        )

                        # Procesar datos actuales para registrar decisiones
                        self.trading_operator.process_data(
                            row=row,
                            balance=balance,
                            positions=positions
                        )

                        # Imprimir el log si hay registros en cualquiera de los logs
                        if self.trading_operator.log_open_positions or self.trading_operator.log_process_data:
                            print("[DEBUG] Llamando a print_log para mostrar los contenidos de los logs.")
                            self.trading_operator.print_log()
                        else:
                            print("[INFO] No hay registros en los logs para imprimir.")

                    else:
                        print("[WARNING] El archivo JSON no contiene datos válidos.")

                    # Pausar antes de la próxima iteración
                    QThread.msleep(25000)

                except Exception as iteration_error:
                    print(f"[ERROR] Error durante la iteración: {iteration_error}")

        except Exception as e:
            error_message = f"[ERROR] Error al inicializar OperatorThread: {e}"
            logging.error(error_message)
            self.error_occurred.emit(error_message)

    def stop(self):
        """Detiene el hilo de manera segura."""
        logging.info("[INFO] Deteniendo OperatorThread...")
        self._is_running = False
        self.quit()
        self.wait()
        logging.info("[INFO] OperatorThread detenido.")


def stop_operator_thread(operator_thread):
    """Detiene OperatorThread de forma segura."""
    if operator_thread and operator_thread.isRunning():
        operator_thread.stop()
        operator_thread.wait()
        logging.info("[INFO] OperatorThread detenido.")



# Bloque principal de ejecución
if __name__ == "__main__":
    try:
        # Inicializa la aplicación PyQt5
        app = QApplication(sys.argv)

        # Configuración para Capital Operations y datos
        capital_ops = CapitalOP()  # Asegúrate de que CapitalOP esté configurado correctamente
        account_id = "253360361314791710"  # ID de cuenta de ejemplo

        # Cargar modelo y datos
        MODEL_FILE = "BTCMD1.pkl"
        DATA_FILE = "/home/hobeat/MoneyMakers/Reports/BTC_USD_IndicadoresCondensados.json"

        try:
            print("[INFO] Cargando modelo y datos...")
            with open(MODEL_FILE, 'rb') as file:
                model_data = pickle.load(file)

            model = model_data.get("model")
            MODEL_FEATURES = model_data.get("features", [])
            scaler_stats = model_data.get("scaler_stats", {})

            with open(DATA_FILE, 'r') as file:
                raw_data = json.load(file)

            current_data = pd.DataFrame(raw_data["data"])
        except Exception as e:
            print(f"[ERROR] Error al cargar modelo y datos: {e}")
            sys.exit(1)  # Termina el programa si falla la carga de modelo o datos

        # Crear la ventana principal con los datos necesarios
        window = MarketSearchApp(capital_ops=capital_ops, account_id=account_id)

        # Mostrar la ventana antes de iniciar el hilo
        window.show()

        # Iniciar el hilo secundario con `OperatorThread`
        try:
            operator_thread = OperatorThread(
                model=model,
                features=MODEL_FEATURES,
                strategy_params={"threshold_buy": 0, "threshold_sell": 2},
                data_frame=current_data,
                data_file=DATA_FILE,
                scaler_stats=scaler_stats,  # Añadido scaler_stats
                saldo_update_callback=window.update_saldo_label  # Callback para actualizar el saldo en la UI
            )
            operator_thread.start()
        except Exception as e:
            print(f"[ERROR] Error al iniciar el hilo secundario: {e}")

        app.aboutToQuit.connect(lambda: stop_operator_thread(OperatorThread))

        # Ejecutar el loop de la aplicación
        sys.exit(app.exec_())

    except Exception as e:
        print(f"[ERROR] Error durante la inicialización de la aplicación: {e}")
