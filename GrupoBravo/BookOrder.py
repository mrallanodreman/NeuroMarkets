import websocket
import json
from EthConfig import API_KEY, LOGIN, PASSWORD
from EthSession import CapitalOP

# Inicializar sesión en Capital.com
capital_ops = CapitalOP()
capital_ops.ensure_authenticated()

# Obtener tokens de sesión
CST = capital_ops.session_token
SECURITY_TOKEN = capital_ops.x_security_token

# Configurar WebSocket de Capital.com
WS_URL = "wss://api-streaming-capital.backend-capital.com/connect"

# Epic del mercado de Ethereum
ETH_MARKET_ID = "ETHUSD"

def on_message(ws, message):
    """Procesa los mensajes entrantes del WebSocket."""
    data = json.loads(message)
    print(f"📊 Actualización del libro de órdenes: {data}")

def on_open(ws):
    """Se ejecuta al abrir la conexión WebSocket."""
    print("✅ Conectado al WebSocket de Capital.com")
    
    # Suscribirse a los datos del libro de órdenes de Ethereum
    subscription_message = {
        "destination": "marketData.subscribe",
        "correlationId": "1",
        "cst": CST,
        "securityToken": SECURITY_TOKEN,
        "payload": {
            "epics": [ETH_MARKET_ID]
        }
    }
    
    ws.send(json.dumps(subscription_message))
    print("📡 Suscrito a los datos de Ethereum.")

def on_error(ws, error):
    """Maneja errores de la conexión WebSocket."""
    print(f"❌ Error en WebSocket: {error}")

def on_close(ws, close_status_code, close_msg):
    """Se ejecuta cuando se cierra la conexión WebSocket."""
    print("🔴 Conexión cerrada.")

# Conectar al WebSocket
ws = websocket.WebSocketApp(WS_URL, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
ws.run_forever()
