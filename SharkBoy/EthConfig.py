
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.panel import Panel
from rich import box
from datetime import datetime
import base64
import re
import subprocess
import atexit
import os
import time
import importlib

# ========================
# Variables de configuración globales
# ========================
# Si alguna de estas variables se deja en None, el script solicitará la configuración.
BASE_URL = "https://demo-api-capital.backend-capital.com/"
SESSION_ENDPOINT = "/api/v1/session"
MARKET_SEARCH_ENDPOINT = "/api/v1/markets"
API_KEY = None 
LOGIN = None
PASSWORD = None 
DATA_DIR = "Reports"  # Directorio donde se guardarán los archivos JSON
OPERATION_MODE = "demo"  # Puede ser "demo" o "real"

ENCODED_KEY = "Y2xhdmVj" 
KEY = base64.b64decode(ENCODED_KEY).decode('utf-8')

# Lista encriptada de usuarios autorizados 
WHITELIST_ENCRYPTED = "2d0515040a0c101f5742 0b0303130417 000414150d0a 2200521b04110e0d12"

def xor_encrypt(text, key=KEY):
    result = []
    for i, ch in enumerate(text):
        result.append(chr(ord(ch) ^ ord(key[i % len(key)])))
    return ''.join(f"{ord(c):02x}" for c in result)

def update_account_id_in_file(filename, new_account_id):
    """
    Busca en el archivo 'filename' la asignación de account_id y reemplaza
    únicamente el valor entre comillas por 'new_account_id', manteniendo intacto
    el resto de la línea (incluyendo comentarios).
    """
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        updated_content = re.sub(
            r'(self\.account_id\s*=\s*")[^"]+(".*)',
            lambda m: m.group(1) + new_account_id + m.group(2),
            content
        )
        with open(filename, "w", encoding="utf-8") as f:
            f.write(updated_content)
        print(f"[INFO] {filename} actualizado con el nuevo account id: {new_account_id}.")
    except Exception as e:
        print(f"[ERROR] No se pudo actualizar {filename}: {e}")


def update_config_file(filename, config_updates):
    """
    Actualiza las variables de configuración en el archivo 'filename' de acuerdo
    a los valores proporcionados en el diccionario config_updates.
    Si la variable no existe, se agrega al inicio del archivo.
    """
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        for var, new_val in config_updates.items():
            new_val_str = str(new_val)
            # Este patrón busca líneas del tipo: VARIABLE = "valor" o VARIABLE = None (manteniendo comentarios)
            pattern = re.compile(r'^(\s*' + re.escape(var) + r'\s*=\s*)(?:"[^"]*"|None)(.*)$', re.MULTILINE)
            replacement = r'\1"' + new_val_str + r'"\2'
            content, count = pattern.subn(replacement, content)
            if count == 0:
                # Si la variable no se encontró, se agrega al principio del archivo
                content = f'{var} = "{new_val_str}"\n' + content
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[INFO] Archivo de configuración {filename} actualizado.")
    except Exception as e:
        print(f"[ERROR] No se pudo actualizar el archivo de configuración {filename}: {e}")

def prompt_and_update_credentials(console):
    global BASE_URL, API_KEY, LOGIN, PASSWORD, OPERATION_MODE

    console.print("[bold cyan]No se han proporcionado credenciales completas en la configuración.[/bold cyan]")
    
    # Primero se piden las credenciales básicas:
    new_api_key = Prompt.ask("Ingrese TU  API KEY de Capital.com ")
    new_login = Prompt.ask("Ingrese su correo", default=LOGIN if LOGIN else "usuario@ejemplo.com")
    new_password = Prompt.ask("Ingrese su clave al momento de crear tu clave api  ", default=PASSWORD if PASSWORD else "", password=True)
    
    # Mostrar un Panel enriquecido con las opciones para el modo de operación:
    panel_text = "[green]1)[/green] Demo\n[blue]2)[/blue] Real"
    panel = Panel(panel_text, title="[bold cyan]Seleccione el modo de operación[/bold cyan]", expand=False)
    console.print(panel)
    
    # Luego se pide al usuario que ingrese la opción:
    mode_choice = Prompt.ask("Ingrese 1 o 2")
    
    if mode_choice == "1":
        mode = "demo"
        new_api_url = "https://demo-api-capital.backend-capital.com/"
    else:
        mode = "real"
        new_api_url = "https://api-capital.backend-capital.com/"
    
    console.print(f"\n[bold green]Modo seleccionado: {mode.upper()}[/bold green]")
    console.print(f"[bold green]URL base configurada automáticamente: [underline]{new_api_url}[/underline][/bold green]\n")
    
    # Actualizar variables globales
    BASE_URL = new_api_url
    API_KEY = new_api_key
    LOGIN = new_login
    PASSWORD = new_password
    OPERATION_MODE = mode.lower()
    
    # Actualizar el archivo de configuración con los nuevos valores
    config_updates = {
         "BASE_URL": BASE_URL,
         "API_KEY": API_KEY,
         "LOGIN": LOGIN,
         "PASSWORD": PASSWORD,
         "OPERATION_MODE": OPERATION_MODE,
    }
    update_config_file(__file__, config_updates)
    console.print("[bold green]Credenciales y configuración actualizadas correctamente.[/bold green]")

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
    console.print(Panel.fit("[bold green]¡La configuración se realizó con éxito![/bold green]\n[italic]Esto es arte, weón...[/italic]", border_style="green"))

def change_account_type(console):
    global BASE_URL, OPERATION_MODE
    panel_text = "[green]1)[/green] Demo\n[blue]2)[/blue] Real"
    panel = Panel(panel_text, title="[bold cyan]Seleccione el nuevo tipo de cuenta[/bold cyan]", expand=False)
    console.print(panel)
    mode_choice = Prompt.ask("Ingrese Opcion 1 para Demo / Opcion  2 Para real ",)
    if mode_choice == "1":
        new_api_url = "https://demo-api-capital.backend-capital.com/"
        mode = "demo"
    else:
        new_api_url = "https://api-capital.backend-capital.com/"
        mode = "real"
    console.print(f"\n[bold green]Nuevo modo seleccionado: {mode.upper()}[/bold green]")
    console.print(f"[bold green]Nueva URL base configurada: [underline]{new_api_url}[/underline][/bold green]\n")
    BASE_URL = new_api_url
    OPERATION_MODE = mode.lower()
    # Actualizamos solo BASE_URL y OPERATION_MODE en el archivo de configuración
    config_updates = {
         "BASE_URL": BASE_URL,
         "OPERATION_MODE": OPERATION_MODE,
    }
    update_config_file(__file__, config_updates)


def main():
    # Lanzar cmatrix en background (opcional)
    try:
        cmatrix_process = subprocess.Popen(
            ["cmatrix", "-b"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        atexit.register(lambda: cmatrix_process.terminate())
    except Exception as e:
        print(f"[WARNING] No se pudo iniciar cmatrix: {e}")
    
    time.sleep(2)
    os.system("clear")
    
    console = Console()
    console.print("[bold green]=== Bienvenido al Autoconfigurador del Bot ===[/bold green]\n")
    
    if not all([BASE_URL, API_KEY, LOGIN, PASSWORD]):
        prompt_and_update_credentials(console)
        import EthSession
        importlib.reload(EthSession)
    
    username = Prompt.ask("[bold cyan]Ingrese su nombre de usuario[/bold cyan]")
    encrypted_username = xor_encrypt(username, KEY)
    allowed_users = WHITELIST_ENCRYPTED.split()
    
    if encrypted_username not in allowed_users:
        console.print("[bold red]Usuario no autorizado. Acceso denegado.[/bold red]")
        return
    console.print("[bold green]Usuario autorizado. Iniciando proceso de configuración...[/bold green]\n")
    
    from EthSession import CapitalOP
    capital_ops = CapitalOP()
    console.print("[bold cyan]Autenticando con la API...[/bold cyan]")
    capital_ops.ensure_authenticated()
    
    console.print("\n[bold cyan]Obteniendo cuentas disponibles...[/bold cyan]")
    account_summary = capital_ops.get_account_summary()
    accounts = account_summary.get("accounts", [])
    if not accounts:
        console.print("[bold red]No se encontraron cuentas disponibles.[/bold red]")
        return

    # Menú extra para decidir si cambiar la configuración
    console.print("\n[bold cyan]Configuración actual detectada.[/bold cyan]")
    console.print("   [bold yellow]1)[/bold yellow] Cambiar cuenta de trading (dentro de la misma configuración)")
    console.print("   [bold yellow]2)[/bold yellow] Cambiar tipo de cuenta (de real a demo o viceversa)")
    console.print("   [bold yellow]3)[/bold yellow] Ver la configuración actual")
    change_option = Prompt.ask("[bold red]Ingrese 1, 2 o 3 según lo que necesites hacer[/bold red]")
    
    if change_option == "2":
        change_account_type(console)
        import EthSession
        importlib.reload(EthSession)
        # Reobtener resumen de cuenta con la nueva configuración
        account_summary = capital_ops.get_account_summary()
        accounts = account_summary.get("accounts", [])
        if not accounts:
            console.print("[bold red]No se encontraron cuentas disponibles tras la reconfiguración.[/bold red]")
            return
    # Para opción 1 o 3 se conserva la configuración actual
    
    # Mostrar un resumen enriquecido para cada cuenta disponible
    console.print("\n[bold cyan]Resumen de cada cuenta disponible:[/bold cyan]\n")
    for account in accounts:
        balance_info = account.get("balance", {})
        summary_table = Table(
            title=f"Resumen de Cuenta: {account.get('accountName', 'N/A')}",
            box=box.SIMPLE_HEAVY
        )
        summary_table.add_column("Parámetro", style="cyan", no_wrap=True)
        summary_table.add_column("Valor", style="magenta")
        summary_table.add_row("Account ID", account.get("accountId", "N/A"))
        summary_table.add_row("Nombre", account.get("accountName", "N/A"))
        summary_table.add_row("Balance", str(balance_info.get("balance", "N/A")))
        summary_table.add_row("Deposit", str(balance_info.get("deposit", "N/A")))
        summary_table.add_row("Profit/Loss", str(balance_info.get("profitLoss", "N/A")))
        summary_table.add_row("Disponible", str(balance_info.get("available", "N/A")))
        console.print(summary_table)
        console.print()
    
    # Mostrar una tabla para la selección
    selection_table = Table(title="Cuentas Disponibles", box=box.ROUNDED)
    selection_table.add_column("Índice", justify="right", style="cyan", no_wrap=True)
    selection_table.add_column("Account ID", style="magenta")
    selection_table.add_column("Nombre", style="green")
    for i, account in enumerate(accounts, start=1):
        selection_table.add_row(str(i), account.get("accountId", "N/A"), account.get("accountName", "N/A"))
    console.print(selection_table)
    
    index_str = Prompt.ask("\n[bold cyan]Ingrese el número de la cuenta que desea utilizar[/bold cyan]")
    try:
        index = int(index_str) - 1
        if index < 0 or index >= len(accounts):
            console.print("[bold red]Índice fuera de rango. Saliendo.[/bold red]")
            return
        selected_account = accounts[index]
    except Exception as e:
        console.print(f"[bold red]Error al seleccionar la cuenta: {e}[/bold red]")
        return
    new_account_id = selected_account.get("accountId")
    capital_ops.set_account_id(new_account_id)
    
    console.print(f"\n[bold green]Cuenta seleccionada: {selected_account.get('accountName')} (ID: {new_account_id})[/bold green]")
    console.print("[bold green]Autoconfiguración completada. El bot está listo para operar.[/bold green]\n")
    
    update_account_id_in_file("SharkBoy.py", new_account_id)
    
    show_config_summary(console, username, selected_account)


if __name__ == "__main__":
    main()