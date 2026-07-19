import time
import threading
import requests
import websocket
import json
import curses
from rich.console import Console
from EthConfig import BASE_URL, API_KEY
from EthSession import CapitalOP

# Globals
console = Console()
watchlist = set()
market_data = {"Shares": [], "Cryptocurrencies": [], "USD": []}
market_lookup = {}
latest_prices = {}
watchlist_lock = threading.Lock()

# Archivos para guardar logs
LOG_FILENAME = "api_responses.txt"
NODE_HEADERS_FILENAME = "node_headers.txt"
CATEGORIZED_FILENAME = "categorized_tickets.json"

def write_log(message):
    """Guarda el mensaje en el archivo de log."""
    with open(LOG_FILENAME, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def write_node_headers(message):
    """Guarda el mensaje en el archivo de node headers."""
    with open(NODE_HEADERS_FILENAME, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def save_categorized_tickets(data):
    """Guarda el JSON de tickets categorizados en un archivo."""
    with open(CATEGORIZED_FILENAME, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# Definición de nodos objetivo
TARGET_NODES = {
    "USD": ["hierarchy_v1.currencies.usd"],
    "Cryptocurrencies": ["hierarchy_v1.crypto_currencies_group"],
    "Shares": ["hierarchy_v1.shares", "hierarchy_v1.shares.us"]
}

# ================== API ==================
def traverse_nodes(nodes, level=0):
    result = ""
    indent = "  " * level
    for node in nodes:
        node_id = node.get("id", "")
        name = node.get("name", "")
        result += f"{indent}id: {node_id}, name: {name}\n"
        if "nodes" in node:
            result += traverse_nodes(node["nodes"], level + 1)
    return result

def list_node_headers(headers):
    navigation_url = BASE_URL + "api/v1/marketnavigation"
    try:
        response = requests.get(navigation_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        nodes = data.get("nodes", [])
        headers_text = traverse_nodes(nodes)
        write_node_headers(headers_text)
        console.log("[INFO] Los cabezales de los nodos se han guardado en node_headers.txt")
        return headers_text
    except Exception as e:
        console.print(f"[red]Error al obtener los cabezales de los nodos: {e}[/red]")
        return ""

def process_node(node_id, headers, target_category=None):
    url = f"{BASE_URL}api/v1/marketnavigation/{node_id}"
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        resumen = {
            "id": data.get("id", node_id),
            "name": data.get("name", ""),
            "nodes": len(data.get("nodes", [])) if "nodes" in data else 0,
            "markets": len(data.get("markets", [])) if "markets" in data else 0
        }
        console.log(f"[DEBUG] Nodo '{node_id}' cabecera: {json.dumps(resumen, indent=2)}")
        write_log(f"Respuesta para nodo '{node_id}':\n{json.dumps(data, indent=2)}")
        markets = []
        if "markets" in data:
            for market in data["markets"]:
                if target_category:
                    market["target_category"] = target_category
                markets.append(market)
        elif "nodes" in data:
            for subnode in data["nodes"]:
                sub_id = subnode.get("id")
                if sub_id:
                    markets.extend(process_node(sub_id, headers, target_category))
        return markets
    except Exception as e:
        console.log(f"[red]Error al procesar nodo {node_id}: {e}[/red]")
        write_log(f"Error al procesar nodo {node_id}: {e}")
        return []

def get_market_data_direct(headers):
    markets = []
    for category, node_ids in TARGET_NODES.items():
        for node_id in node_ids:
            console.log(f"[DEBUG] Procesando nodo objetivo '{node_id}' para categoría {category}")
            write_log(f"Procesando nodo objetivo '{node_id}' para categoría {category}")
            sub_markets = process_node(node_id, headers, target_category=category)
            console.log(f"[DEBUG] Nodo '{node_id}' devolvió {len(sub_markets)} mercados")
            write_log(f"Nodo '{node_id}' devolvió {len(sub_markets)} mercados")
            markets.extend(sub_markets)
            time.sleep(0.3)
    console.log(f"[INFO] Total mercados recogidos (directo): {len(markets)}")
    write_log(f"Total mercados recogidos (directo): {len(markets)}")
    return markets

def categorize_markets(all_markets):
    market_data["Shares"].clear()
    market_data["Cryptocurrencies"].clear()
    market_data["USD"].clear()
    for m in all_markets:
        cat = m.get("target_category", "").lower()
        if cat == "shares":
            market_data["Shares"].append(m)
        elif cat in ["cryptocurrencies", "crypto_currencies_group"]:
            market_data["Cryptocurrencies"].append(m)
        elif cat == "usd":
            market_data["USD"].append(m)
    console.log(f"[INFO] Total acciones: {len(market_data['Shares'])}")
    console.log(f"[INFO] Total criptos: {len(market_data['Cryptocurrencies'])}")
    console.log(f"[INFO] Total USD: {len(market_data['USD'])}")

# ================== FUNCIONES NUEVAS ==================
def open_asset(stdscr, ticker):
    """
    Realiza una solicitud a Yahoo Finance para obtener detalles del ticket (ticker)
    y muestra la respuesta en una pantalla desplazable.
    """
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        data = {"error": str(e)}
    info_text = json.dumps(data, indent=2)
    lines = info_text.splitlines()
    offset = 0
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        for idx, line in enumerate(lines[offset:offset+height-2]):
            try:
                stdscr.addstr(idx, 0, line[:width-1], curses.color_pair(1))
            except curses.error:
                pass
        stdscr.addstr(height-1, 0, "Presione 'q' para volver, ↑/↓ para desplazar", curses.color_pair(1))
        stdscr.refresh()
        key = stdscr.getch()
        if key == ord('q'):
            break
        elif key == curses.KEY_DOWN and offset + height - 2 < len(lines):
            offset += 1
        elif key == curses.KEY_UP and offset > 0:
            offset -= 1

def save_categorized_tickets(data):
    """Guarda el JSON con todos los tickets categorizados en un archivo."""
    with open("categorized_tickets.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    console.log("[INFO] JSON de tickets categorizados guardado en categorized_tickets.json")

# ================== CURSES ==================
tabs = ["Acciones", "Cryptos", "USD", "Watchlist"]
current_tab = 3  # Inicia en Watchlist

def draw_table(stdscr, markets, selected_idx, offset):
    stdscr.clear()
    stdscr.attrset(curses.color_pair(1))
    stdscr.addstr(0, 2, " Navega con ← → ↑ ↓ | ENTER para abrir activo | TAB para watchlist | Q para salir ")
    stdscr.addstr(1, 2, f"Vista: {tabs[current_tab]}", curses.A_BOLD | curses.color_pair(1))
    header = "{:<4} {:<20} {:<12} {:>10}".format("#", "Nombre", "Ticker", "Precio")
    stdscr.addstr(3, 2, header, curses.A_UNDERLINE | curses.color_pair(2))
    market_lookup.clear()
    height, width = stdscr.getmaxyx()
    available_lines = height - 4
    for idx in range(offset, min(len(markets), offset + available_lines)):
        market = markets[idx]
        line = 4 + (idx - offset)
        epic = market.get("epic", "N/A")
        name = market.get("instrumentName", "N/A")[:20]
        snapshot = market.get("snapshot") or {}
        price = snapshot.get("BID")
        price_str = f"{price:.4f}" if price is not None else "--"
        marker = "->" if idx == selected_idx else "  "
        try:
            stdscr.addstr(line, 2, f"{marker} {idx:<2} {name:<20} {epic:<12} {price_str:>10}", curses.color_pair(1))
        except curses.error:
            pass
        market_lookup[str(idx)] = epic
    stdscr.refresh()

def curses_menu(stdscr, headers, ws_client):
    global current_tab
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Texto verde, fondo negro
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Para header, se puede agregar A_BOLD
    selected = 0
    offset = 0
    subscribed_epics = set()
    while True:
        if current_tab == 0:
            current_markets = market_data["Shares"]
        elif current_tab == 1:
            current_markets = market_data["Cryptocurrencies"]
        elif current_tab == 2:
            current_markets = market_data["USD"]
        else:
            with watchlist_lock:
                current_markets = []
                for epic in watchlist:
                    data = latest_prices.get(epic, {})
                    price = data.get("BID", 0.0)
                    current_markets.append({
                        "epic": epic,
                        "instrumentName": epic,
                        "snapshot": {"BID": price}
                    })
        # En Watchlist (tab index 3) se realizan suscripciones, sino no
        if current_tab == 3:
            for m in current_markets:
                epic = m.get("epic")
                if epic and epic not in subscribed_epics:
                    ws_client.subscribe(ws_client.ws, epic)
                    subscribed_epics.add(epic)
        height, width = stdscr.getmaxyx()
        available_lines = height - 4
        if selected < offset:
            offset = selected
        elif selected >= offset + available_lines:
            offset = selected - available_lines + 1

        draw_table(stdscr, current_markets, selected, offset)
        key = stdscr.getch()
        if key == ord('q'):
            break
        elif key in [curses.KEY_RIGHT, curses.KEY_LEFT]:
            current_tab = (current_tab + (1 if key == curses.KEY_RIGHT else -1)) % len(tabs)
            selected = 0
            offset = 0
        elif key == curses.KEY_DOWN:
            if selected < len(current_markets) - 1:
                selected += 1
        elif key == curses.KEY_UP:
            if selected > 0:
                selected -= 1
        elif key == 10:  # ENTER: abrir activo
            if current_tab in [0, 1, 2] and current_markets:
                ticker = current_markets[selected].get("epic")
                open_asset(stdscr, ticker)
        elif key == 9:  # TAB: agregar a watchlist y guardar JSON
            if current_tab in [0, 1, 2] and current_markets:
                ticker = current_markets[selected].get("epic")
                watchlist.add(ticker)
                save_categorized_tickets(market_data)
                console.log(f"[INFO] {ticker} agregado a Watchlist y JSON guardado.")

# ================== LIGHTSTREAMER ==================
class LightstreamerClient:
    def __init__(self, cst, token, host="wss://push.capital.com"):
        self.ws_url = host
        self.cst = cst
        self.token = token
        self.subscribed_epics = set()
    def on_open(self, ws):
        console.log("[WS] Conectado")
        ws.send("\n\n")
        ws.send(f"bind_session\nLS_op2\nCST:{self.cst}\nX-SECURITY-TOKEN:{self.token}\n")
    def on_message(self, ws, message):
        if "|" not in message or not message.startswith("D"):
            return
        try:
            parts = message.split("|", 2)
            body = parts[2].strip()
            update = json.loads(body)
            epic = update.get("EPIC")
            if epic:
                with watchlist_lock:
                    latest_prices[epic] = update
        except Exception as e:
            console.log(f"[WS Error] {e}")
    def run(self):
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_message=self.on_message,
            on_open=self.on_open
        )
        self.ws.run_forever()
    def subscribe(self, ws, epic):
        if epic in self.subscribed_epics:
            return
        self.subscribed_epics.add(epic)
        msg = (
            f"subscribe\n"
            f"MODE:MERGE\n"
            f"LS_table:1\n"
            f"LS_schema:BID,CHANGE_PCT,EPIC\n"
            f"LS_data_adapter:QUOTE_ADAPTER\n"
            f"LS_id:{epic}\n"
        )
        try:
            ws.send(msg)
            console.log(f"[INFO] Suscrito a {epic}")
        except Exception as e:
            console.log(f"[red]Error al suscribir {epic}: {e}[/red]")

# ================== FUNCIONES DE ASSET ==================
def open_asset(stdscr, ticker):
    """
    Realiza una solicitud a Yahoo Finance para obtener detalles del ticket
    y muestra la respuesta en una pantalla desplazable.
    """
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        data = {"error": str(e)}
    info_text = json.dumps(data, indent=2)
    lines = info_text.splitlines()
    offset = 0
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        for idx, line in enumerate(lines[offset:offset+height-2]):
            try:
                stdscr.addstr(idx, 0, line[:width-1], curses.color_pair(1))
            except curses.error:
                pass
        stdscr.addstr(height-1, 0, "Presione 'q' para volver, ↑/↓ para desplazar", curses.color_pair(1))
        stdscr.refresh()
        key = stdscr.getch()
        if key == ord('q'):
            break
        elif key == curses.KEY_DOWN and offset + height - 2 < len(lines):
            offset += 1
        elif key == curses.KEY_UP and offset > 0:
            offset -= 1

# ================== MAIN ==================
def main():
    capital = CapitalOP()
    capital.ensure_authenticated()
    headers = {
        "X-CAP-API-KEY": API_KEY,
        "CST": capital.session_token,
        "X-SECURITY-TOKEN": capital.x_security_token,
    }
    # Guardar los cabezales de los nodos en un archivo y mostrarlos en consola (solo cabezales)
    node_headers = list_node_headers(headers)
    console.log(f"[DEBUG] Cabezas de nodos guardadas:\n{node_headers}")
    console.log("[INFO] Navegando a nodos objetivo:")
    for category in TARGET_NODES:
        console.log(f"  {category}: {TARGET_NODES[category]}")
    all_markets = get_market_data_direct(headers)
    categorize_markets(all_markets)
    console.log(f"[DEBUG] Inicial: Acciones: {len(market_data['Shares'])}, Cryptos: {len(market_data['Cryptocurrencies'])}, USD: {len(market_data['USD'])}")
    ws_client = LightstreamerClient(capital.session_token, capital.x_security_token)
    threading.Thread(target=ws_client.run, daemon=True).start()
    curses.wrapper(lambda stdscr: curses_menu(stdscr, headers, ws_client))

if __name__ == "__main__":
    main()
