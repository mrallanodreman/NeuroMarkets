from rich.console import Console
from rich.table import Table
from rich.live import Live
import websocket
import json
import time
import threading
from collections import defaultdict, deque

# 📌 Parámetros
SOCKET_ORDERBOOK = "wss://stream.binance.com:9443/ws/ethusdt@depth"
SOCKET_TRADES = "wss://stream.binance.com:9443/ws/ethusdt@trade"
console = Console()
order_book = {"bids": [], "asks": []}
traded_orders = deque(maxlen=21)  # Últimos 10 trades ejecutados
alert_message = ""
order_repeats = defaultdict(int)

# 📌 Umbrales de detección
WALL_ORDER_THRESHOLD = 5
SPEED_THRESHOLD = 10
SPOOFING_VOLUME_MULTIPLIER = 5
SPOOFING_REPETITION_THRESHOLD = 3

# 📌 Función para manejar WebSockets con reconexión
def websocket_handler(url, on_message):
    def run():
        while True:
            try:
                ws = websocket.WebSocketApp(url, on_message=on_message)
                ws.run_forever()
            except Exception as e:
                console.print(f"[red]Error en WebSocket ({url}): {e}. Reintentando...[/red]")
                time.sleep(5)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

# 📌 WebSocket para Order Book
def on_message_orderbook(ws, message):
    global order_book, alert_message

    data = json.loads(message)
    new_bids = [(float(price), float(qty), "BID") for price, qty in data.get('b', [])[:10]]
    new_asks = [(float(price), float(qty), "ASK") for price, qty in data.get('a', [])[:10]]

    order_book["bids"] = new_bids
    order_book["asks"] = new_asks

    # 📌 Detección de "Wall Orders"
    total_bid_volume = sum(qty for _, qty, _ in new_bids)
    total_ask_volume = sum(qty for _, qty, _ in new_asks)
    avg_volume = (total_bid_volume + total_ask_volume) / 20 if (total_bid_volume + total_ask_volume) > 0 else 1

    for price, qty, side in new_bids + new_asks:
        if qty > avg_volume * WALL_ORDER_THRESHOLD:
            alert_message = f"🚧 Wall Order en {price:.2f} ({qty:.2f}) [{side}]"

    # 🚀 Spoofing basado en volumen
    for price, qty, side in new_bids + new_asks:
        if qty > avg_volume * SPOOFING_VOLUME_MULTIPLIER:
            alert_message = f"⚠️ Spoofing detectado en {price:.2f} [{side}] (Volumen anómalo)"

# 📌 WebSocket para Trades
def on_message_trades(ws, message):
    global traded_orders
    data = json.loads(message)
    price = float(data['p'])
    qty = float(data['q'])
    is_buyer_maker = data['m']
    direction = "SELL" if is_buyer_maker else "BUY"
    traded_orders.append((price, qty, direction))

# 🔥 Inicia ambos WebSockets con reconexión
websocket_handler(SOCKET_ORDERBOOK, on_message_orderbook)
websocket_handler(SOCKET_TRADES, on_message_trades)

# 📌 Tabla del Order Book
def generate_orderbook_table():
    table = Table(title="📊 Libro de Órdenes ETH/USDT", show_header=True, header_style="bold magenta")
    table.add_column("Tipo", justify="center")
    table.add_column("Precio", justify="right", style="yellow")
    table.add_column("Cantidad", justify="right", style="cyan")

    bids = sorted(order_book["bids"], key=lambda x: x[0], reverse=True)
    asks = sorted(order_book["asks"], key=lambda x: x[0])

    for price, qty, _ in asks:
        table.add_row("[red]ASK[/red]", f"[red]{price:.2f}[/red]", f"{qty:.4f}")

    table.add_row("", "", "")  # Separador visual

    for price, qty, _ in bids:
        table.add_row("[green]BID[/green]", f"[green]{price:.2f}[/green]", f"{qty:.4f}")

    return table

# 📌 Tabla de Trades Ejecutados (corregida)
def generate_trades_table():
    table = Table(title="📈 Últimos Trades Ejecutados", show_header=True, header_style="bold cyan")
    table.add_column("Tipo", justify="center")
    table.add_column("Precio", justify="right", style="yellow")
    table.add_column("Cantidad", justify="right", style="cyan")

    # 🔹 Hacer una copia segura de traded_orders antes de iterar
    trades_copy = list(traded_orders)

    for price, qty, direction in reversed(trades_copy):  # Se evita la mutación en tiempo real
        color = "red" if direction == "SELL" else "green"
        table.add_row(f"[{color}]{direction}[/{color}]", f"[{color}]{price:.2f}[/{color}]", f"{qty:.4f}")

    return table

# 📌 Tabla de Análisis (con el título en el header)
def generate_analysis_table():
    analysis_table = Table(show_header=True, header_style="bold yellow")
    analysis_table.add_column("⚠️ Análisis del Order Book", justify="center")
    analysis_table.add_row(f"[bold yellow]{alert_message}[/bold yellow]")
    return analysis_table

# 📌 Generar Layout con tablas unidas y análisis abajo
def generate_layout():
    layout = Table.grid(padding=0)  # Sin espacio entre tablas

    # Crear una tabla que contenga las dos tablas dentro
    combined_table = Table.grid()
    combined_table.add_column()
    combined_table.add_column()

    # Agregar las tablas de order book y trades a la misma fila
    combined_table.add_row(generate_orderbook_table(), generate_trades_table())

    # Agregar la tabla combinada y luego la tabla de análisis abajo
    layout.add_row(combined_table)
    layout.add_row(generate_analysis_table())

    return layout

# 🟢 Loop principal con actualización en tiempo real
with Live(generate_layout(), refresh_per_second=4, console=console) as live:
    while True:
        live.update(generate_layout())
