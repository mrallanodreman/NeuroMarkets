from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.panel import Panel
from rich import box
from datetime import datetime
import re
import subprocess
import atexit
import os
import time

# Variables de configuración
BASE_URL = "https://api-capital.backend-capital.com/"
SESSION_ENDPOINT = "/api/v1/session"
MARKET_SEARCH_ENDPOINT = "/api/v1/markets"
API_KEY = "dshUTxIDbHEtaOJS"
LOGIN = "ODREMANALLANR@GMAIL.COM"
PASSWORD = "Millo2025."
DATA_DIR = "Reports"  # Directorio donde se guardarán los archivos JSON

# Configuración para la whitelist encriptada
KEY = "clavec"
# Whitelist encriptada para usuarios autorizados (por ejemplo, "hobeat" y "chende")
WHITELIST_ENCRYPTED = "0b0303130417 000404180106"

def xor_encrypt(text, key=KEY):
    """Aplica XOR sobre cada carácter y retorna la representación hexadecimal."""
    result = []
    for i, ch in enumerate(text):
        result.append(chr(ord(ch) ^ ord(key[i % len(key)])))
    return ''.join(f"{ord(c):02x}" for c in result)

def update_account_id_in_file(filename, new_account_id):
    """
    Busca en el archivo 'filename' la asignación de account_id y reemplaza
    únicamente el valor entre comillas por 'new_account_id', manteniendo intacto
    el resto de la línea (incluyendo comentarios). Por ejemplo, la línea:
        self.account_id = "260136346534097182"  # Tu cuenta Id
    se actualizará a:
        self.account_id = "260494821678994628"  # Tu cuenta Id
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

def show_config_summary(console, username, selected_account):
    summary_table = Table(title="Resumen de Autoconfiguración", box=box.DOUBLE_EDGE)
    summary_table.add_column("Parámetro", style="cyan", no_wrap=True)
    summary_table.add_column("Valor", style="magenta")
    summary_table.add_row("Usuario", username)
    summary_table.add_row("Cuenta", selected_account.get("accountName", "N/A"))
    summary_table.add_row("Account ID", selected_account.get("accountId", "N/A"))
    summary_table.add_row("Fecha", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    console.print(summary_table)
    console.print(Panel.fit("[bold green]¡La configuración se realizó con éxito![/bold green]\n[italic]Esto es arte, weón...[/italic]", border_style="green"))

def main():
    # Lanzar cmatrix en background
    try:
        cmatrix_process = subprocess.Popen(
            ["cmatrix", "-b"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        # Aseguramos que se termine al salir
        atexit.register(lambda: cmatrix_process.terminate())
    except Exception as e:
        print(f"[WARNING] No se pudo iniciar cmatrix: {e}")
    
    # Dar tiempo a que cmatrix se inicie y luego limpiar la pantalla
    time.sleep(2)
    os.system("clear")
    
    console = Console()
    console.print("[bold green]=== Bienvenido al Autoconfigurador del Bot ===[/bold green]\n")
    
    # Solicitar nombre de usuario
    username = Prompt.ask("[bold cyan]Ingrese su nombre de usuario[/bold cyan]")
    encrypted_username = xor_encrypt(username, KEY)
    allowed_users = WHITELIST_ENCRYPTED.split()
    
    # Validar usuario en base a la whitelist encriptada
    if encrypted_username not in allowed_users:
         console.print("[bold red]Usuario no autorizado. Acceso denegado.[/bold red]")
         return
    console.print("[bold green]Usuario autorizado. Iniciando proceso de configuración...[/bold green]\n")
    
    # Importar la clase CapitalOP desde EthSession
    try:
         from EthSession import CapitalOP
    except ImportError as e:
         console.print(f"[bold red]Error al importar EthSession: {e}[/bold red]")
         return
    
    # Crear instancia de CapitalOP y autenticar
    capital_ops = CapitalOP()
    console.print("[bold cyan]Autenticando con la API...[/bold cyan]")
    capital_ops.ensure_authenticated()
    
    # Obtener resumen de cuenta
    console.print("\n[bold cyan]Obteniendo cuentas disponibles...[/bold cyan]")
    account_summary = capital_ops.get_account_summary()
    accounts = account_summary.get("accounts", [])
    if not accounts:
         console.print("[bold red]No se encontraron cuentas disponibles.[/bold red]")
         return
    
    # Mostrar cuentas disponibles en una tabla
    table = Table(title="Cuentas Disponibles", box=box.ROUNDED)
    table.add_column("Índice", justify="right", style="cyan", no_wrap=True)
    table.add_column("Account ID", style="magenta")
    table.add_column("Nombre", style="green")
    for i, account in enumerate(accounts, start=1):
         table.add_row(str(i), account.get("accountId", "N/A"), account.get("accountName", "N/A"))
    console.print(table)
    
    # Solicitar selección de cuenta
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
    
    # Actualizar el archivo SharkBoy.py para reemplazar solo el valor entre comillas en la asignación de account_id.
    update_account_id_in_file("SharkBoy.py", new_account_id)
    
    show_config_summary(console, username, selected_account)

if __name__ == "__main__":
    main()
