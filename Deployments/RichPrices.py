import websocket
import requests
import threading
import json
import shutil
import csv
import os
import time
from datetime import datetime
from rich.table import Table
from rich.console import Console
from rich.live import Live

# Variables de configuración
BASE_URL = "https://api-capital.backend-capital.com/"
SESSION_ENDPOINT = "api/v1/session"
API_KEY = "dshUTxIDbHEtaOJS"
LOGIN = "ODREMANALLANR@GMAIL.COM"
PASSWORD = "Millo2025."
WEBSOCKET_URL = "wss://api-streaming-capital.backend-capital.com/connect"
CSV_FILE = "Pricedata.csv"

# Variables globales
valores_actuales = {
    "BTCUSD": {"bid": None, "ofr": None, "timestamp": None, "bid_color": "white", "ofr_color": "white"},
    "ETHUSD": {"bid": None, "ofr": None, "timestamp": None, "bid_color": "white", "ofr_color": "white"},
}
console = Console()

# Verifica si el archivo CSV existe y crea encabezados si es necesario
def verificar_archivo_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Epic", "Bid", "Offer", "Timestamp", "fecha "])

# Guarda un nuevo tick en el archivo CSV en tiempo real
def guardar_en_csv(epic, bid, ofr, timestamp, fecha):
    try:
        with open(CSV_FILE, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([epic, f"{bid:.5f}", f"{ofr:.5f}", timestamp, fecha])  # Agregamos fecha
            file.flush()
            os.fsync(file.fileno())  # Asegura que los datos se escriban inmediatamente en el archivo
    except Exception as e:
        print(f"[ERROR CSV] {e}")

# Crea la tabla en consola
def crear_tabla():
    table = Table(title="Precios de BTC y ETH en Vivo", expand=True)
    table.add_column("Epic", style="cyan", justify="center")
    table.add_column("Precio (Bid)", justify="center")
    table.add_column("Oferta (Ofr)", justify="center")
    table.add_column("Última Actualización", style="magenta", justify="center")
    
    for epic, datos in valores_actuales.items():
        bid_str = f"[{datos.get('bid_color', 'white')}]${datos['bid']:.5f}[/{datos.get('bid_color', 'white')}]" if datos["bid"] else "N/A"
        ofr_str = f"[{datos.get('ofr_color', 'white')}]${datos['ofr']:.5f}[/{datos.get('ofr_color', 'white')}]" if datos["ofr"] else "N/A"
        timestamp_str = datos['timestamp'] if datos['timestamp'] else "N/A"
        table.add_row(epic, bid_str, ofr_str, timestamp_str)
    return table

# Autenticación en la API
def iniciar_sesion():
    headers = {"Content-Type": "application/json", "X-CAP-API-KEY": API_KEY}
    payload = {"identifier": LOGIN, "password": PASSWORD}
    try:
        response = requests.post(BASE_URL + SESSION_ENDPOINT, json=payload, headers=headers)
        response.raise_for_status()
        return response.headers.get("CST"), response.headers.get("X-SECURITY-TOKEN")
    except Exception as e:
        console.print(f"[red]Error al iniciar sesión: {e}[/red]")
        return None, None

# Conexión WebSocket con reconexión y reautenticación para operar 24/7
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
                        timestamp = payload["timestamp"]  # Se mantiene el timestamp original en milisegundos
                        fecha = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S")  # Convertimos a fecha
                        
                        # Determinar color basado en cambio de precio
                        old_bid = valores_actuales[epic]["bid"]
                        bid_color = "white" if old_bid is None else ("green" if new_bid > old_bid else "red" if new_bid < old_bid else "white")
                        old_ofr = valores_actuales[epic]["ofr"]
                        ofr_color = "white" if old_ofr is None else ("green" if new_ofr > old_ofr else "red" if new_ofr < old_ofr else "white")
                        
                        # Actualizar valores
                        valores_actuales[epic].update({"bid": new_bid, "ofr": new_ofr, "timestamp": fecha, "bid_color": bid_color, "ofr_color": ofr_color})
                        
                        # Guardar en CSV en tiempo real
                        guardar_en_csv(epic, new_bid, new_ofr, timestamp, fecha)
                        
                        # Actualizar consola
                        live.update(crear_tabla())
            except Exception as e:
                print(f"[ERROR WebSocket] {e}")

        def on_open(ws):
            console.print("[green]WebSocket conectado.[/green]")
            subscription_message = {
                "destination": "marketData.subscribe",
                "correlationId": "1",
                "cst": cst,
                "securityToken": security_token,
                "payload": {"epics": ["BTCUSD", "ETHUSD"]}
            }
            ws.send(json.dumps(subscription_message))
            console.print("[blue]Suscripción enviada: BTCUSD y ETHUSD[/blue]")

        def on_error(ws, error):
            console.print(f"[red]Error en WebSocket: {error}[/red]")

        def on_close(ws, close_status_code, close_msg):
            console.print(f"[red]WebSocket cerrado: {close_status_code} - {close_msg}[/red]")

        ws = websocket.WebSocketApp(WEBSOCKET_URL, on_message=on_message, on_open=on_open, on_error=on_error, on_close=on_close)
        ws.run_forever(ping_interval=600, ping_timeout=5)

        console.print("[yellow]Conexión interrumpida. Intentando reconectar en 5 segundos...[/yellow]")
        time.sleep(5)

        # Reautenticación antes de reconectar
        new_cst, new_security_token = iniciar_sesion()
        if new_cst and new_security_token:
            cst, security_token = new_cst, new_security_token
            console.print("[green]Reautenticación exitosa. Tokens renovados.[/green]")
        else:
            console.print("[red]Error en la reautenticación. Se usará el token anterior.[/red]")

# Verificar si el archivo CSV existe
verificar_archivo_csv()

# Iniciar sesión y conectar WebSocket
cst, security_token = iniciar_sesion()
if cst and security_token:
    with Live(crear_tabla(), refresh_per_second=4, console=console) as live:
        threading.Thread(target=conectar_websocket, args=(cst, security_token, live), daemon=True).start()
        try:
            while True:
                input()
        except KeyboardInterrupt:
            pass
else:
    console.print("[red]No se pudo autenticar al servidor de Capital.com. Verifica tus credenciales.[/red]")
