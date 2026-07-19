from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.panel import Panel
from rich import box
from datetime import datetime
import os
import sys
import time
import requests
import json

# ========================
# Variables de configuración globales (leídas desde variables de entorno)
# ========================
# Configurar en el perfil del sistema:
#   CAPITAL_API_KEY, CAPITAL_LOGIN, CAPITAL_PASSWORD
#   CAPITAL_OPERATION_MODE (demo|real, default: real)
#   CAPITAL_ACCOUNT_ID

OPERATION_MODE = os.environ.get("CAPITAL_OPERATION_MODE", "real").lower()
BASE_URL = (
    "https://demo-api-capital.backend-capital.com/"
    if OPERATION_MODE == "demo"
    else "https://api-capital.backend-capital.com/"
)
SESSION_ENDPOINT = "api/v1/session"
MARKET_SEARCH_ENDPOINT = "api/v1/markets"
API_KEY = os.environ.get("CAPITAL_API_KEY")
LOGIN = os.environ.get("CAPITAL_LOGIN")
PASSWORD = os.environ.get("CAPITAL_PASSWORD")
DATA_DIR = "Reports"

_missing = [name for name, val in [
    ("CAPITAL_API_KEY", API_KEY),
    ("CAPITAL_LOGIN", LOGIN),
    ("CAPITAL_PASSWORD", PASSWORD),
] if not val]
if _missing:
    print(f"[ERROR] Variables de entorno requeridas no configuradas: {', '.join(_missing)}")
    print("[ERROR] Configúralas en tu perfil del sistema antes de ejecutar el bot.")
    sys.exit(1)

# Trading configuration
# FIXED_POSITION_SIZE: None = usar sistema dinámico de tiers por saldo
FIXED_POSITION_SIZE = None

# Sistema de tiers dinámico por leverage: {leverage: [(balance_mínimo, size_ETH), ...]}
# Se selecciona el tier más alto que el balance disponible pueda cubrir
# Cada conjunto está optimizado para el apalancamiento correspondiente
POSITION_SIZE_TIERS = {
    # Leverage 2x (cripto en cuentas minoristas) → margen 0.9%-1.7% del balance
    2: [
        (0.50,  0.001),    # $0.50+ → 0.001 ETH  ($0.85 margen = 0.9% de $100)
        (1.00,  0.00125),  # $1.00+ → 0.00125 ETH ($1.07 margen = 1.1% de $100)
        (2.00,  0.0015),   # $2.00+ → 0.0015 ETH  ($1.28 margen = 1.3% de $100)
        (3.00,  0.00175),  # $3.00+ → 0.00175 ETH ($1.49 margen = 1.5% de $100)
        (5.00,  0.002),    # $5.00+ → 0.002 ETH  ($1.71 margen = 1.7% de $100)
    ],
    # Leverage 20x+ (cuentas con margen alto) → margen 5%-8% del balance
    20: [
        (0.50,  0.001),   # $0.50+ → 0.001 ETH  ($0.08 margen = 0.08% de $100)
        (1.00,  0.002),   # $1.00+ → 0.002 ETH  ($0.16 margen = 0.16%)
        (3.00,  0.003),   # $3.00+ → 0.003 ETH  ($0.24 margen = 0.24%)
        (7.00,  0.005),   # $7.00+ → 0.005 ETH  ($0.40 margen = 0.4%)
        (15.00, 0.01),    # $15.00+ → 0.01 ETH ($0.80 margen = 0.8%)
        (30.00, 0.02),    # $30.00+ → 0.02 ETH ($1.60 margen = 1.6%)
        (60.00, 0.04),    # $60.00+ → 0.04 ETH ($3.20 margen = 3.2%)
    ],
}

SUPPORT_TOLERANCE = 0.005     # 0.5% tolerancia sobre soporte para filtro SELL
RECENT_RALLY_WINDOW_MIN = 15  # Ventana en velas para detectar rally reciente
RECENT_RALLY_PCT = 0.02       # 2% umbral de rally reciente para filtro SELL
ADX_TREND_THRESHOLD = 20      # ADX mínimo para considerar mercado en tendencia
VOLUME_NEG_THRESHOLD = -0.1   # Umbral de cambio de volumen negativo para confirmación SELL

# STOP_LOSS: flag para adjuntar un stop loss al abrir posiciones.
# Desactivado por defecto. Se controla con la variable de entorno STOP_LOSS
# (valores válidos para activarlo: 1, true, yes, on — sin distinguir mayúsculas).
# Cuando está activo, el stop loss se coloca al 99% de distancia del precio de
# entrada (el máximo permitido por Capital.com), es decir, un stop nominal que
# prácticamente no se dispara — útil para cuentas/regiones que exigen un stop
# loss para poder abrir la posición.
STOP_LOSS = os.environ.get("STOP_LOSS", "false").strip().lower() in ("1", "true", "yes", "on")
STOP_LOSS_PCT = 0.99          # Distancia del stop loss cuando STOP_LOSS está activo (99%)


def switch_active_account(account_id, cst, security_token):
    url = BASE_URL + "api/v1/session"
    headers = {
        "Content-Type": "application/json",
        "X-SECURITY-TOKEN": security_token,
        "CST": cst
    }
    payload = {"accountId": account_id}
    try:
        response = requests.put(url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"[INFO] ✅ Cuenta cambiada exitosamente a: {account_id}")
        else:
            print(f"[ERROR] ❌ No se pudo cambiar la cuenta: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"[ERROR] ❌ Error en switch_active_account: {e}")




def show_config_summary(console, username, selected_account):
    summary_table = Table(title="Resumen de Autoconfiguración", box=box.DOUBLE_EDGE)
    summary_table.add_column("Parámetro", style="cyan", no_wrap=True)
    summary_table.add_column("Valor", style="magenta")
    summary_table.add_row("Usuario", username)
    summary_table.add_row("Cuenta", selected_account.get("accountName", "N/A"))
    summary_table.add_row("Account ID", selected_account.get("accountId", "N/A"))
    summary_table.add_row("Fecha", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    summary_table.add_row("Modo", OPERATION_MODE)
    console.print(summary_table)
    console.print(Panel.fit("[bold green]La configuración se realizó con éxito.[/bold green]\n[italic]Entorno validado y listo para usar.[/italic]", border_style="green"))



def login():
    """
    Realiza el login en Capital.com usando API KEY, LOGIN y PASSWORD sin encriptar.
    Según la documentación, se debe enviar encryptedPassword en false.
    Obtiene los tokens CST y X-SECURITY-TOKEN de los headers de respuesta.
    """
    url = BASE_URL + SESSION_ENDPOINT  # Ej: https://api-capital.backend-capital.com/api/v1/session
    payload = {
        "encryptedPassword": False,
        "identifier": LOGIN,
        "password": PASSWORD
    }
    headers = {
        "Content-Type": "application/json",
        "X-CAP-API-KEY": API_KEY
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            session_data = response.json()
            cst = response.headers.get("CST")
            security_token = response.headers.get("X-SECURITY-TOKEN")
            if not cst or not security_token:
                print("[ERROR] No se obtuvieron CST o X-SECURITY-TOKEN en la respuesta.")
                return None, None, None
            print(f"[INFO] Autenticación exitosa. CST: {cst} | X-SECURITY-TOKEN: {security_token}")
            return session_data, cst, security_token
        else:
            print(f"[ERROR] Fallo en autenticación: {response.status_code} - {response.text}")
            return None, None, None
    except Exception as e:
        print(f"[ERROR] Excepción en login: {e}")
        return None, None, None


def get_account_summary(cst, security_token):
    """
    Obtiene un resumen detallado de la cuenta activa usando los tokens CST y X-SECURITY-TOKEN.
    También devuelve la lista completa de cuentas disponibles.
    """
    try:
        account_url = BASE_URL + "api/v1/accounts"
        headers = {
            "Content-Type": "application/json",
            "X-SECURITY-TOKEN": security_token,
            "CST": cst
        }
        response = requests.get(account_url, headers=headers)
        if response.status_code == 200:
            accounts_data = response.json()
            if accounts_data is None:
                raise ValueError(
                    f"Respuesta vacía (None) al consultar {account_url} "
                    f"[GET, status={response.status_code}, body={response.text!r}]"
                )
            accounts_list = accounts_data.get("accounts", [])

            # Se intenta obtener currentAccountId mediante GET /session
            session_url = BASE_URL + "api/v1/session"
            session_response = requests.get(session_url, headers=headers)
            if session_response.status_code == 200:
                session_info = session_response.json()
                current_account_id = session_info.get("currentAccountId")
            else:
                print("[ERROR] No se pudo obtener currentAccountId. Usando la primera cuenta disponible.")
                current_account_id = None

            selected_account = None
            for account in accounts_list:
                if account.get("accountId") == current_account_id:
                    selected_account = account
                    break
            if not selected_account and accounts_list:
                selected_account = accounts_list[0]

            account_summary = {
                "accountId": selected_account.get("accountId"),
                "accountName": selected_account.get("accountName"),
                "accountType": selected_account.get("accountType"),
                "currency": selected_account.get("currency"),
                "symbol": selected_account.get("symbol"),
                "balance": selected_account.get("balance", {}).get("balance", 0),
                "available": selected_account.get("balance", {}).get("available", 0),
                "deposit": selected_account.get("balance", {}).get("deposit", 0),
                "profitLoss": selected_account.get("balance", {}).get("profitLoss", 0),
                "preferred": selected_account.get("preferred", False),
                "clientId": accounts_data.get("clientId", ""),
                "timezoneOffset": accounts_data.get("timezoneOffset", 0),
                "streamingHost": accounts_data.get("streamingHost", "")
            }
            print(f"[INFO] ✅ Datos de la cuenta activa obtenidos: {json.dumps(account_summary, indent=4)}")
            return account_summary, accounts_list

        elif response.status_code == 401:
            print("[ERROR] ❌ Autenticación fallida. Verifique la API KEY y tokens.")
        else:
            print(f"[ERROR] ❌ Error al obtener la cuenta: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"[ERROR] ❌ Fallo al obtener la cuenta: {e}")
        import traceback
        traceback.print_exc()
    return {}, []


def main():
    console = Console()
    console.print("[bold green]=== Verificador de Configuración del Bot ===[/bold green]\n")

    env_table = Table(title="Variables de Entorno", box=box.ROUNDED)
    env_table.add_column("Variable", style="cyan")
    env_table.add_column("Estado", style="magenta")
    for var in ["CAPITAL_API_KEY", "CAPITAL_LOGIN", "CAPITAL_PASSWORD", "CAPITAL_OPERATION_MODE", "CAPITAL_ACCOUNT_ID"]:
        val = os.environ.get(var)
        status = "[green]✅ Configurada[/green]" if val else "[red]❌ No configurada[/red]"
        env_table.add_row(var, status)
    console.print(env_table)

    console.print(f"\n[bold cyan]Modo:[/bold cyan] {OPERATION_MODE.upper()}")
    console.print(f"[bold cyan]URL:[/bold cyan] {BASE_URL}\n")

    console.print("[bold cyan]Verificando credenciales con Capital.com...[/bold cyan]")
    session_data, cst, security_token = login()
    if not session_data:
        console.print("[bold red]❌ Autenticación fallida. Revisa tus variables de entorno.[/bold red]")
        return

    account_summary, accounts = get_account_summary(cst, security_token)
    if account_summary and "accountId" in account_summary:
        show_config_summary(console, LOGIN, account_summary)
        selection_table = Table(title="Cuentas Disponibles", box=box.ROUNDED)
        selection_table.add_column("Account ID", style="magenta")
        selection_table.add_column("Nombre", style="green")
        for account in accounts:
            selection_table.add_row(account.get("accountId", "N/A"), account.get("accountName", "N/A"))
        console.print(selection_table)
        console.print("\n[bold yellow]Para cambiar de cuenta, actualiza la variable de entorno CAPITAL_ACCOUNT_ID.[/bold yellow]")
    console.print("[bold green]Configuración verificada. El bot está listo para operar.[/bold green]\n")


if __name__ == "__main__":
    main()
