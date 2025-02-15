import json
import math
import os
import requests
import subprocess  # Importar subprocess
from PyQt5.QtWidgets import (
    QApplication, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, 
    QGraphicsTextItem, QGraphicsLineItem
)
from PyQt5.QtMultimedia import QMediaPlayer  # Puedes eliminar esto si ya no lo usas
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QPointF, QUrl
from PyQt5.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor, QTransform, QFont
from io import BytesIO
import sys
import yfinance as yf
import time

DEFAULT_LOGO_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/480px-No_image_available.svg.png"

class MarketNode(QGraphicsPixmapItem):
    """Nodo que representa un activo financiero."""
    def __init__(self, x, y, size, name, logo_url):
        super().__init__()
        self.size = size
        self.name = name

        # Establecer el tooltip con texto estilizado
        tooltip_html = f"""
        <div style="font-family: Arial; font-size: 9pt; color: white; background-color: black; padding: 1px; border-radius: 1px;">
            <b>{name}</b>
        </div>
        """
        self.setToolTip(tooltip_html)

        try:
            # Intentar cargar el logo desde la URL
            response = requests.get(logo_url, timeout=5)
            if response.status_code == 200:
                pixmap = QPixmap()
                pixmap.loadFromData(BytesIO(response.content).read())
                pixmap = self.create_circular_pixmap(pixmap, int(size))
                self.setPixmap(pixmap)
            else:
                self.set_default_logo(size)
        except:
            self.set_default_logo(size)

        self.setPos(x, y)  # Establecer la posición del nodo

    def set_default_logo(self, size):
        """Configurar el logo predeterminado si no se puede cargar el logo."""
        response = requests.get(DEFAULT_LOGO_URL)
        pixmap = QPixmap()
        pixmap.loadFromData(BytesIO(response.content).read())
        pixmap = self.create_circular_pixmap(pixmap, int(size))
        self.setPixmap(pixmap)

    def create_circular_pixmap(self, pixmap, size):
        """Crear un pixmap circular desde una imagen."""
        scaled_pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        circular_pixmap = QPixmap(size, size)
        circular_pixmap.fill(Qt.transparent)
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter = QPainter(circular_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, scaled_pixmap)
        painter.end()
        return circular_pixmap


class DataLoader(QThread):
    """Cargar datos desde los epics guardados en saved_epics.json."""
    data_loaded = pyqtSignal(dict)  # Señal para enviar los datos cargados al hilo principal

    def __init__(self, saved_epics_file="/home/hobeat/MoneyMakers/Reports/saved_epics.json", 
                 data_folder="/home/hobeat/MoneyMakers/Reports/"):
        super().__init__()
        self.saved_epics_file = saved_epics_file
        self.data_folder = data_folder

    def run(self):
        """Cargar los datos en un hilo separado."""
        data = self.load_data()
        self.data_loaded.emit(data)  # Emitir los datos cargados
    def normalize_epic(self, epic):

        """Normaliza el nombre del epic para garantizar consistencia."""
        if "USD" in epic and not epic.endswith("-USD"):
            return epic.replace("USD", "-USD")
        return epic

    def load_data(self, max_retries=5, wait_time=10):
        """Carga datos desde saved_epics.json con reintentos."""
        merged_data = {}
        retries = 0

        print(f"[INFO] Intentando leer archivo: {self.saved_epics_file}")
        try:
            with open(self.saved_epics_file, "r") as file:
                saved_epics = json.load(file)
            print(f"[INFO] Epics encontrados en {self.saved_epics_file}: {saved_epics}")
        except Exception as e:
            print(f"[ERROR] No se pudo leer {self.saved_epics_file}: {e}")
            return {}

        while retries < max_retries:
            print(f"[INFO] Intento {retries + 1}/{max_retries} para cargar datos...")
            try:
                for epic in saved_epics:
                    normalized_epic = self.normalize_epic(epic)
                    print(f"[INFO] Procesando epic: Original: {epic}, Normalizado: {normalized_epic}")
                    
                    file_path = os.path.join(self.data_folder, f"{normalized_epic}_current.json")
                    if os.path.exists(file_path):
                        try:
                            print(f"[INFO] Cargando datos actuales desde {file_path}")
                            with open(file_path, "r") as f:
                                record = json.load(f)[0]

                            historical_file = os.path.join(self.data_folder, f"{normalized_epic}_historical.json")
                            if os.path.exists(historical_file):
                                print(f"[INFO] Cargando datos históricos desde {historical_file}")
                                with open(historical_file, "r") as hist_f:
                                    historical_data = json.load(hist_f)
                                    recent_volumes = [d["Volume"] for d in historical_data[-5:]]
                                    recent_volume_avg = sum(recent_volumes) / len(recent_volumes)
                                    recent_prices = [d["Close"] for d in historical_data[-5:]]
                                    max_price = max(recent_prices)
                                    min_price = min(recent_prices)
                            else:
                                print(f"[WARN] No se encontró historial para {normalized_epic}. Usando datos actuales como referencia.")
                                max_price = record["High"]
                                min_price = record["Low"]
                                recent_volume_avg = record["Volume"]

                            merged_data[normalized_epic] = {
                                "Close": record["Close"],
                                "High": record["High"],
                                "Low": record["Low"],
                                "Volume": record["Volume"],
                                "money_flow": (record["High"] - record["Low"]) * record["Volume"],
                                "volatility": max(record["High"] - record["Low"], 1),
                                "max_price": max_price,
                                "min_price": min_price,
                                "recent_volume_avg": recent_volume_avg,
                            }
                            print(f"[INFO] Datos procesados para {normalized_epic}: {merged_data[normalized_epic]}")
                        except Exception as e:
                            print(f"[ERROR] No se pudo procesar {file_path}: {e}")
                    else:
                        print(f"[WARN] Archivo actual no encontrado para {normalized_epic}: {file_path}")
                
                if merged_data:
                    print(f"[INFO] Datos cargados exitosamente: {len(merged_data)} epics procesados.")
                    return merged_data
            except Exception as e:
                print(f"[ERROR] Error al cargar datos: {e}")
            print(f"[INFO] Reintentando en {wait_time} segundos...")
            time.sleep(wait_time)
            retries += 1

        print("[INFO] No se pudieron cargar los datos después de múltiples intentos.")
        return merged_data


class MarketFlow(QGraphicsView):
    """Radar principal del mercado."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene()
        self.player = QMediaPlayer()

        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setStyleSheet("background-color: black; border: 10px solid #222;")

        # Ajustar el tamaño de la ventana y escena
        self.resize(300, 300)  # Ajustar según sea necesario
        self.scene.setSceneRect(0, 0, self.width(), self.height())

        self.base_size = 14
        self.max_size = 60
        self.nodes = []

        # Inicializar self.data como un diccionario vacío
        self.data = {}
        self.domains = {}

        # -------------------
        # Variables para la Animación del Radar
        # -------------------
        self.radar_angle = 0  # Ángulo actual del radar en grados
        self.radar_trails_items = []  # Lista para almacenar las estelas del radar
        self.radar_trail_length = 20  # Número de líneas en la estela

        # Crear una línea giratoria para el radar
        radar_pen = QPen(QColor(0, 0, 0, 0), 2)  # Verde con algo de transparencia
        self.radar_line = QGraphicsLineItem(0, 0, 0, -250)  # Línea desde el centro hacia arriba
        self.radar_line.setPen(radar_pen)
        self.radar_line.setZValue(1)  # Por encima de otros elementos

        # Posicionar el radar en el centro del círculo
        self.center_x, self.center_y = self.scene.width() / 2, self.scene.height() / 2
        self.radar_line.setPos(self.center_x, self.center_y)
        self.scene.addItem(self.radar_line)

        # Hilo para cargar los datos
        self.data_loader = DataLoader()
        self.data_loader.data_loaded.connect(self.on_data_loaded)
        self.data_loader.start()  # Iniciar el hilo para cargar los datos

        # Dibujar el radar sin nodos si los datos no están disponibles
        self.draw_radar()  # Llamada a draw_radar()

        # -------------------
        # Temporizador para Radar
        # -------------------
        self.radar_timer = QTimer()
        self.radar_timer.timeout.connect(self.update_radar)
        self.radar_timer.start(300000)  # Actualizar cada 30 ms (~33 FPS)




    def draw_radar(self):
        """Dibuja el radar con etiquetas y efecto glow de forma responsiva."""
        self.center_x, self.center_y = self.scene.width() / 2, self.scene.height() / 2
        max_radius = (min(self.scene.width(), self.scene.height()) / 2 - 30) * 1.1  # Ajustamos un 10% más grande

        radar_pen = QPen(Qt.green, 2, Qt.SolidLine)  # Pen base

        # Dibujar los círculos concéntricos
        num_circles = 5
        for i in range(num_circles):
            radius = (max_radius / num_circles) * (i + 1)
            self.scene.addEllipse(self.center_x - radius, self.center_y - radius, radius * 2, radius * 2, radar_pen)

        # Etiquetas de los círculos
        for i in range(num_circles):
            percentage = 100 - (i * (100 // num_circles))
            label = QGraphicsTextItem(f"{percentage}%")
            label.setDefaultTextColor(Qt.white)
            radius = (max_radius / num_circles) * (i + 1)
            label.setPos(self.center_x + radius - 25, self.center_y - 25)  # Ajuste manual para posicionar bien
            self.scene.addItem(label)


    def on_data_loaded(self, data):
        """Actualizar los datos cuando se cargan desde el hilo."""
        self.data = data
        self.domains = self.assign_logos()

        # Si los datos ahora están disponibles, dibujamos los nodos
        if self.data:
            self.create_nodes()

    def update_radar(self):
        """Actualiza la posición de la línea del radar y maneja la estela con fading."""
        self.radar_angle = (self.radar_angle + 2) % 360  # Rotar 2 grados

        transform = QTransform()
        transform.translate(self.center_x, self.center_y)
        transform.rotate(self.radar_angle)
        self.radar_line.setTransform(transform)

        # Crear nueva estela
        trail = QGraphicsLineItem(0, 0, 0, -250)
        trail.setPen(QPen(QColor(0, 255, 0, 150), 2))  # Verde semi-transparente
        trail.setTransform(transform)
        trail.setZValue(0)
        self.scene.addItem(trail)
        self.radar_trails_items.append(trail)

        # Aplicar fading
        for existing_trail in self.radar_trails_items:
            current_pen = existing_trail.pen()
            color = current_pen.color()
            new_opacity = max(color.alpha() - 10, 0)
            existing_trail.setPen(QPen(QColor(color.red(), color.green(), color.blue(), new_opacity), current_pen.width()))

        # Eliminar estelas transparentes
        self.radar_trails_items = [t for t in self.radar_trails_items if t.pen().color().alpha() > 0]

        # Limitar la longitud de la estela
        if len(self.radar_trails_items) > self.radar_trail_length:
            old_trail = self.radar_trails_items.pop(0)
            self.scene.removeItem(old_trail)


    def assign_logos(self):
        """Asigna URLs de logos para criptomonedas y acciones dinámicamente."""
        crypto_logos_base = "https://s2.coinmarketcap.com/static/img/coins/64x64/"
        default_logo = DEFAULT_LOGO_URL  # URL por defecto si no se encuentra un logo
        
        # IDs de criptomonedas conocidos (se puede expandir dinámicamente si tienes una API)
        crypto_ids = {
            "BTC-USD": 1,
            "ETH-USD": 1027,
            "XRP-USD": 52,
            "DOGE-USD": 74,
            "SOL-USD": 5426,
        }
        
        logos = {}

        for ticker in self.data.keys():
            logo_url = default_logo  # Valor por defecto inicial
            
            # Verificar si es una criptomoneda conocida
            if ticker in crypto_ids:
                logo_url = f"{crypto_logos_base}{crypto_ids[ticker]}.png"
            else:
                # Buscar el dominio usando yfinance
                try:
                    info = yf.Ticker(ticker).info
                    website = info.get("website", "")
                    if website:
                        domain = website.replace("https://", "").replace("http://", "").split("/")[0]
                        logo_url = f"https://logo.clearbit.com/{domain}"
                except Exception as e:
                    print(f"[ERROR] No se pudo obtener el logo para {ticker}: {e}")
            
            # Verificar si el logo existe realmente
            if not self.validate_logo(logo_url):
                logo_url = default_logo
            
            logos[ticker] = logo_url
        
        return logos

    def validate_logo(self, url):
        """Verifica si un logo existe en la URL proporcionada."""
        try:
            response = requests.head(url, timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def calculate_opportunity(self, data, max_volume, max_money_flow, min_price, max_price_hist):
        volume = data.get("Volume", 0)
        money_flow = data.get("money_flow", 0)
        adj_close = data.get("Adj Close", 1)
        volatility = data.get("volatility", 1)

        # Validaciones para evitar divisiones por cero
        if volume <= 0 or adj_close <= 0 or volatility <= 0 or max_price_hist <= min_price:
            return 0

        # Factor histórico basado en el precio actual respecto al rango histórico
        factor_historico = 1 - abs(adj_close - min_price) / (max_price_hist - min_price)

        # Volumen y flujo de dinero relativos
        volume_relativo = volume / max_volume
        flujo_relativo = money_flow / max_money_flow

        # Ajuste de volatilidad (logarítmico para reflejar mejor los cambios)
        volatilidad_ajustada = max(1, math.log(volatility + 1))

        # Fórmula ajustada para calcular la oportunidad
        opportunity = (
            0.4 * volume_relativo +
            0.3 * flujo_relativo +
            0.3 * factor_historico
        ) / volatilidad_ajustada

        return max(opportunity, 0)  # Asegura que no haya valores negativos

    def create_nodes(self):
        """Crea nodos y calcula su posición basada en oportunidad."""
        if not self.data:
            print("[INFO] No se encontraron datos. No se dibujarán los nodos.")
            return

        max_radius = min(self.scene.width(), self.scene.height()) / 2 - 50 - self.base_size

        # Calculamos máximos y mínimos
        max_volume = max(v["Volume"] for v in self.data.values())
        max_money_flow = max(v["money_flow"] for v in self.data.values())
        min_price = min(v["Close"] for v in self.data.values())
        max_price_hist = max(v["Close"] for v in self.data.values())

        for index, (ticker, info) in enumerate(self.data.items()):
            opportunity = self.calculate_opportunity(info, max_volume, max_money_flow, min_price, max_price_hist)
            distance = min((1 - opportunity) * max_radius, max_radius)

            # Posicionamiento radial
            angle = 2 * math.pi * index / len(self.data)
            x = self.center_x + math.cos(angle) * distance
            y = self.center_y + math.sin(angle) * distance

            size = self.base_size + opportunity * 30
            node = MarketNode(x, y, size, ticker, self.domains.get(ticker, DEFAULT_LOGO_URL))
            self.scene.addItem(node)
            self.nodes.append(node)


    def add_pulse(self):
        """Método de placeholder si necesitas agregar pulsos adicionales."""
        pass  # Actualmente no implementado, pero puedes agregar lógica aquí si lo deseas


    def play_sound(self, filename="sonar_out.wav", volume= 5):
        """
        Reproduce un archivo de sonido usando ffplay con un control de volumen ajustable.
        
        :param filename: Nombre del archivo de sonido a reproducir (por defecto "sonar_out.wav").
        :param volume: Nivel de volumen de 0 a 100 (por defecto 50, ajustable para mayor control).
        """
        sound_path = os.path.join(os.getcwd(), filename)
        
        if not os.path.exists(sound_path):
            print(f"Archivo {filename} no encontrado.")
            return
        
        try:            
            # Asegurarse de que el volumen esté entre 0 y 100
            volume = max(0, min(100, volume))  # Ajusta el volumen a un rango de 0 a 100
            
            subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-volume", str(volume), sound_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"[ERROR] No se pudo reproducir {filename} con ffplay: {e}")

    # Ejemplo de uso:
    # Llamamos a la función para reproducir un sonido con un volumen ajustable




if __name__ == "__main__":
    app = QApplication(sys.argv)
    view = MarketFlow()
    view.setWindowTitle("Radar de Oportunidad del Mercado")
    view.show()
    sys.exit(app.exec_())
