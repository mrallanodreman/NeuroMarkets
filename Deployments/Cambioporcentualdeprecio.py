import csv
import os
import time
import pygame
import requests
import subprocess
import bisect
from datetime import datetime, timedelta
from rich.table import Table
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TimeRemainingColumn
from rich.live import Live

# Inicializar pygame para sonidos
pygame.mixer.init()
SONIDO_ALERTA = "sonar.mp3"

# Umbral de alerta para cambios abruptos en porcentaje
UMBRAL_ALERTA = 2.0  # 2% de cambio

console = Console()

# Periodos a analizar
periodos = {
    "5m": timedelta(minutes=5),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1)
}

# Archivo de datos CSV
CSV_FILE = "Pricedata.csv"

# Guarda la hora de inicio del script
hora_inicio_script = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Variable global para almacenar resultados previos
resultados_global = {}

def reproducir_sonido():
    """Reproduce un sonido de alerta."""
    pygame.mixer.music.load(SONIDO_ALERTA)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(1)

def generar_alerta_tts(mensaje):
    """Genera una alerta de voz usando una API de TTS."""
    url = "https://streamlined-edge-tts.p.rapidapi.com/tts"
    querystring = {"text": mensaje, "voice": "es-EC-Andrea"}
    headers = {
        "x-rapidapi-key": "c04ed2d75emsh7a7a49fc7c31bd4p17ed9bjsn751dee926d84",
        "x-rapidapi-host": "streamlined-edge-tts.p.rapidapi.com"
    }
    response = requests.get(url, headers=headers, params=querystring)
    if response.status_code == 200:
        with open("alerta.mp3", "wb") as f:
            f.write(response.content)
        subprocess.run(["ffplay", "-nodisp", "-autoexit", "alerta.mp3"])
    else:
        console.print(f"❌ Error en la API: {response.status_code}")

def leer_csv():
    """Lee el archivo CSV y devuelve una lista de diccionarios."""
    if not os.path.exists(CSV_FILE):
        console.print(f"[red]El archivo {CSV_FILE} no existe.[/red]")
        return []
    with open(CSV_FILE, mode='r') as file:
        reader = csv.DictReader(file)
        return [{key.strip(): value for key, value in row.items()} for row in reader]

def obtener_datos_ticker(datos, epic):
    """Filtra los datos para un ticket específico."""
    return [fila for fila in datos if fila["Epic"] == epic]



def encontrar_precio_mas_cercano(datos_ticker, hora_objetivo):
    """Optimiza la búsqueda del precio más cercano con bisect y reducción de conversiones."""
    
    # Verificar si los datos están ordenados antes de ordenarlos nuevamente (ahorra tiempo)
    if not all(datos_ticker[i]["fecha"] <= datos_ticker[i + 1]["fecha"] for i in range(len(datos_ticker) - 1)):
        datos_ticker.sort(key=lambda fila: fila["fecha"])  # Ordenamos por la fecha como string para evitar conversión repetida

    # Extraemos solo las fechas en formato string
    timestamps = [fila["fecha"] for fila in datos_ticker]

    # Usamos búsqueda binaria para encontrar la posición más cercana
    idx = bisect.bisect_left(timestamps, hora_objetivo.strftime("%Y-%m-%d %H:%M:%S"))

    if idx == 0:
        return datos_ticker[0]
    if idx >= len(timestamps):
        return datos_ticker[-1]

    # Comparar anterior y siguiente sin convertir `datetime` cada vez
    prev_diferencia = abs(datetime.strptime(timestamps[idx - 1], "%Y-%m-%d %H:%M:%S") - hora_objetivo)
    next_diferencia = abs(datetime.strptime(timestamps[idx], "%Y-%m-%d %H:%M:%S") - hora_objetivo)

    return datos_ticker[idx - 1] if prev_diferencia <= next_diferencia else datos_ticker[idx]


def calcular_cambios(hora_inicio, periodo_a_actualizar=None):
    """Calcula los cambios de precio en distintos periodos."""
    global resultados_global
    datos = leer_csv()
    if not datos:
        return resultados_global  # Si no hay datos, devolvemos los resultados previos

    tickers = set(row["Epic"] for row in datos)
    nuevos_resultados = {}

    for epic in tickers:
        datos_ticker = obtener_datos_ticker(datos, epic)
        precios_base = resultados_global.get(epic, ({p: "N/A" for p in periodos.keys()}, {p: "N/A" for p in periodos.keys()}))[0]
        cambios = resultados_global.get(epic, ({}, {}))[1]

        precio_actual = float(datos_ticker[-1]["Bid"]) if datos_ticker else None
        if precio_actual is None:
            continue

        for periodo, delta in periodos.items():
            if periodo_a_actualizar and periodo != periodo_a_actualizar:
                continue  # Solo recalcula el periodo correspondiente

            hora_objetivo = hora_inicio - delta
            registro = encontrar_precio_mas_cercano(datos_ticker, hora_objetivo)
            if registro:
                precios_base[periodo] = float(registro["Bid"])
                cambios[periodo] = ((precio_actual - precios_base[periodo]) / precios_base[periodo]) * 100

                # Si el cambio en % supera el umbral, dispara la alerta
                if abs(cambios[periodo]) >= UMBRAL_ALERTA:
                    console.print(f"[bold red]⚠️ ALARMA: {epic} cambió un {cambios[periodo]:.2f}% en {periodo}[/bold red]")
                    reproducir_sonido()
                    generar_alerta_tts(f"Alerta de cambio en {epic}. Cambio del {cambios[periodo]:.2f} por ciento en {periodo}.")
        
        nuevos_resultados[epic] = (precios_base, cambios)

    resultados_global.update(nuevos_resultados)  # Mantenemos los valores previos no actualizados
    return resultados_global

def mostrar_tabla(resultados):
    """Muestra la tabla con los cambios de precio para cada ticker."""
    console.clear()
    if not resultados:
        console.print("[red]No hay resultados para mostrar.[/red]")
        return

    for epic, (precios_base, cambios) in resultados.items():
        table = Table(title=f"Histórico de {epic}", expand=True)
        table.add_column("Periodo", style="cyan", justify="center")
        table.add_column("Precio Base", justify="center")
        table.add_column("Cambio (%)", justify="center")
        for periodo in periodos.keys():
            precio_base = precios_base.get(periodo, "N/A")
            cambio_formateado = f"{cambios.get(periodo, 'N/A'):.2f}%" if isinstance(cambios.get(periodo), float) else "N/A"
            table.add_row(periodo, str(precio_base), cambio_formateado)
        console.print(f"\n[bold yellow]Análisis de {epic}[/bold yellow]")
        console.print(table)
    
    console.print(f"\n[bold cyan]Inicio del Script: {hora_inicio_script}[/bold cyan]\n")

def live_progress():
    """Muestra y actualiza los cronómetros para cada intervalo."""
    start_times = {label: time.time() for label in periodos}
    progress = Progress(
        SpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(),
        TimeRemainingColumn()
    )
    task_ids = {}
    resultados = calcular_cambios(datetime.now())
    mostrar_tabla(resultados)  # Mostrar tabla inicial

    for label, delta in periodos.items():
        total_seg = int(delta.total_seconds())
        task_ids[label] = progress.add_task(label, total=total_seg, completed=0)
    
    with Live(progress, refresh_per_second=1, console=console):
        while True:
            now = time.time()
            for label, delta in periodos.items():
                total_seg = int(delta.total_seconds())
                elapsed = now - start_times[label]

                if elapsed >= total_seg:
                    start_times[label] = now
                    elapsed = 0
                    resultados = calcular_cambios(datetime.now(), periodo_a_actualizar=label)
                    mostrar_tabla(resultados)  # Actualiza la tabla en ese momento

                remaining = total_seg - elapsed
                progress.update(task_ids[label], completed=elapsed, total=total_seg, description=f"{label} - {int(remaining)} s restantes")
            time.sleep(1)

def main():
    console.clear()
    live_progress()

if __name__ == "__main__":
    main()
