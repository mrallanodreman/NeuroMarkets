import websocket
import requests
import threading
import json
import csv
import os
import time
from datetime import datetime
from rich.table import Table
from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel

# Variables de configuración
BASE_URL = "https://api-capital.backend-capital.com/"
SESSION_ENDPOINT = "api/v1/session"
API_KEY = "dshUTxIDbHEtaOJS"
LOGIN = "ODREMANALLANR@GMAIL.COM"
PASSWORD = "Millo2025."
WEBSOCKET_URL = "wss://api-streaming-capital.backend-capital.com/connect"
CSV_FILE = "Pricedata.csv"

# Variables globales para almacenar los precios actuales
valores_actuales = {
    "BTCUSD": {"bid": None, "ofr": None, "timestamp": None, "bid_color": "white", "ofr_color": "white"},
    "ETHUSD": {"bid": None, "ofr": None, "timestamp": None, "bid_color": "white", "ofr_color": "white"},
}
console = Console()

# Lista global para almacenar mensajes de log
log_messages = []

# Función para agregar mensajes al log (manteniendo solo los últimos 10)
def add_log(message):
    log_messages.append(message)
    if len(log_messages) > 10:
        del log_messages[0]

# Intervalos en segundos y sus etiquetas (sólo snapshots se guardan)
INTERVALOS = {
    180: "3m",       # 3 minutos
    300: "5m",       # 5 minutos
    900: "15m",      # 15 minutos
    1800: "30m",     # 30 minutos
    3600: "1h",      # 1 hora
    7200: "2h",      # 2 horas
    14400: "4h",     # 4 horas
    28800: "8h",     # 8 horas
    43200: "12h",    # 12 horas
    86400: "24h"     # 24 horas
}

# Verifica si el archivo CSV existe y crea encabezados si es necesario
def verificar_archivo_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='w', newline='') as file:
            writer = csv.writer(file)
            # Nuevo encabezado: Periodo, EPIC, Bid, Offer, Timestamp, Fecha
            writer.writerow(["Periodo", "EPIC", "Bid", "Offer", "Timestamp", "Fecha"])

# Función para guardar un snapshot en el CSV (se guarda una fila por instrumento)
def guardar_snapshot(period_label):
    btc = valores_actuales["BTCUSD"]
    eth = valores_actuales["ETHUSD"]
    now = datetime.now()
    fecha = now.strftime("%Y-%m-%d %H:%M:%S")
    
    btc_bid = f"{btc['bid']:.5f}" if btc["bid"] is not None else "N/A"
    btc_ofr = f"{btc['ofr']:.5f}" if btc["ofr"] is not None else "N/A"
    eth_bid = f"{eth['bid']:.5f}" if eth["bid"] is not None else "N/A"
    eth_ofr = f"{eth['ofr']:.5f}" if eth["ofr"] is not None else "N/A"
    
    with open(CSV_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        # Guardamos una fila para BTCUSD y otra para ETHUSD
        writer.writerow([period_label, "BTCUSD", btc_bid, btc_ofr, fecha, fecha])
        writer.writerow([period_label, "ETHUSD", eth_bid, eth_ofr, fecha, fecha])
        file.flush()
        os.fsync(file.fileno())
    msg = f"Snapshot registrado para el periodo {period_label}"
    console.print(f"[blue]{msg}[/blue]")
    add_log(msg)

# Función que gestiona los snapshots en los intervalos definidos
def snapshot_manager(start_time):
    pendientes = sorted(INTERVALOS.keys())
    while pendientes:
        ahora = time.time()
        elapsed = ahora - start_time
        siguiente_intervalo = pendientes[0]
        if elapsed >= siguiente_intervalo:
            period_label = INTERVALOS[siguiente_intervalo]
            guardar_snapshot(period_label)
            pendientes.pop(0)
        else:
            time.sleep(1)

# Función para construir la tabla de precios (solo para visualización en vivo)
def crear_tabla():
    table = Table(expand=True)
    table.add_column("Epic", style="cyan", justify="center")
    table.add_column("Precio (Bid)", justify="center")
    table.add_column("Oferta (Ofr)", justify="center")
    table.add_column("Última Actualización", style="magenta", justify="center")
    
    for epic, datos in valores_actuales.items():
        bid_str = f"[{datos.get('bid_color', 'white')}]${datos['bid']:.5f}[/{datos.get('bid_color', 'white')}]" if datos["bid"] is not None else "N/A"
        ofr_str = f"[{datos.get('ofr_color', 'white')}]${datos['ofr']:.5f}[/{datos.get('ofr_color', 'white')}]" if datos["ofr"] is not None else "N/A"
        timestamp_str = datos['timestamp'] if datos['timestamp'] is not None else "N/A"
        table.add_row(epic, bid_str, ofr_str, timestamp_str)
    return table

# Función para construir el renderable unificado (reloj, log y tabla) usando Layout
def crear_renderable():
    elapsed = time.time() - start_time
    hrs, rem = divmod(int(elapsed), 3600)
    mins, secs = divmod(rem, 60)
    elapsed_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"
    
    header_text = f"Inicio: {start_datetime.strftime('%d/%m/%Y %H:%M:%S')} | Transcurrido: {elapsed_str}"
    header_panel = Panel(header_text, title="Reloj", border_style="green")
    
    # Panel de log con altura fija (5 líneas)
    log_panel = Panel("\n".join(log_messages[-10:]), title="Log", border_style="blue")
    
    table = crear_tabla()
    
    layout = Layout()
    layout.split_column(
        Layout(header_panel, size=3),
        Layout(log_panel, size=5),
        Layout(table)
    )
    return layout

# Función de autenticación en la API
def iniciar_sesion():
    headers = {"Content-Type": "application/json", "X-CAP-API-KEY": API_KEY}
    payload = {"identifier": LOGIN, "password": PASSWORD}
    try:
        response = requests.post(BASE_URL + SESSION_ENDPOINT, json=payload, headers=headers)
        response.raise_for_status()
        return response.headers.get("CST"), response.headers.get("X-SECURITY-TOKEN")
    except Exception as e:
        msg = f"Error al iniciar sesión: {e}"
        console.print(f"[red]{msg}[/red]")
        add_log(msg)
        return None, None

# Conexión WebSocket para actualización en vivo (los ticks solo se usan para visualizar)
def conectar_websocket(cst, security_token, live):
    while True:
        def on_message(ws, message):
            try:
                data = json.loads(message)
                if data.get("destination") == "quote" and data.get("payload"):
                    payload = data["payload"]
                    epic = payload["epic"]
                    if epic in valores_actuales:
                        new_bid = float(payload["bid"])
                        new_ofr = float(payload["ofr"])
                        timestamp = payload["timestamp"]  # timestamp en milisegundos
                        fecha = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S")
                        
                        old_bid = valores_actuales[epic]["bid"]
                        bid_color = "white" if old_bid is None else ("green" if new_bid > old_bid else "red" if new_bid < old_bid else "white")
                        old_ofr = valores_actuales[epic]["ofr"]
                        ofr_color = "white" if old_ofr is None else ("green" if new_ofr > old_ofr else "red" if new_ofr < old_ofr else "white")
                        
                        valores_actuales[epic].update({
                            "bid": new_bid,
                            "ofr": new_ofr,
                            "timestamp": fecha,
                            "bid_color": bid_color,
                            "ofr_color": ofr_color
                        })
                        
                        live.update(crear_renderable())
            except Exception as e:
                msg = f"Error en WebSocket: {e}"
                print(f"[ERROR WebSocket] {e}")
                add_log(msg)

        def on_open(ws):
            msg = "WebSocket conectado."
            console.print(f"[green]{msg}[/green]")
            add_log(msg)
            subscription_message = {
                "destination": "marketData.subscribe",
                "correlationId": "1",
                "cst": cst,
                "securityToken": security_token,
                "payload": {"epics": ["BTCUSD", "ETHUSD"]}
            }
            ws.send(json.dumps(subscription_message))
            msg = "Suscripción enviada: BTCUSD y ETHUSD"
            console.print(f"[blue]{msg}[/blue]")
            add_log(msg)

        def on_error(ws, error):
            msg = f"Error en WebSocket: {error}"
            console.print(f"[red]{msg}[/red]")
            add_log(msg)

        def on_close(ws, close_status_code, close_msg):
            msg = f"WebSocket cerrado: {close_status_code} - {close_msg}"
            console.print(f"[red]{msg}[/red]")
            add_log(msg)

        ws = websocket.WebSocketApp(WEBSOCKET_URL, on_message=on_message, on_open=on_open, on_error=on_error, on_close=on_close)
        ws.run_forever(ping_interval=600, ping_timeout=5)

        msg = "Conexión interrumpida. Intentando reconectar en 5 segundos..."
        console.print(f"[yellow]{msg}[/yellow]")
        add_log(msg)
        time.sleep(5)

        new_cst, new_security_token = iniciar_sesion()
        if new_cst and new_security_token:
            cst, security_token = new_cst, new_security_token
            msg = "Reautenticación exitosa. Tokens renovados."
            console.print(f"[green]{msg}[/green]")
            add_log(msg)
        else:
            msg = "Error en la reautenticación. Se usará el token anterior."
            console.print(f"[red]{msg}[/red]")
            add_log(msg)

# Inicializar CSV y registrar el tiempo de inicio
verificar_archivo_csv()
start_time = time.time()
start_datetime = datetime.now()

# Iniciar el thread para capturar snapshots en los intervalos definidos
threading.Thread(target=snapshot_manager, args=(start_time,), daemon=True).start()

# Iniciar sesión y conectar el WebSocket para visualización en vivo
cst, security_token = iniciar_sesion()
if cst and security_token:
    with Live(crear_renderable(), refresh_per_second=4, console=console) as live:
        threading.Thread(target=conectar_websocket, args=(cst, security_token, live), daemon=True).start()
        try:
            while True:
                input()  # Mantener el script en ejecución
        except KeyboardInterrupt:
            pass
else:
    console.print("[red]No se pudo autenticar al servidor de Capital.com. Verifica tus credenciales.[/red]")
