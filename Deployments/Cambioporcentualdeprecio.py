import csv
import os
import time
import pygame
import requests
import subprocess
from datetime import datetime, timedelta
from rich.table import Table
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TimeRemainingColumn
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel

# Inicializar pygame para sonidos
pygame.mixer.init()
SONIDO_ALERTA = "sonar.mp3"

# Umbral de alerta para cambios abruptos en porcentaje
UMBRAL_ALERTA = 2.0  # 2% de cambio

console = Console()

# Periodos a analizar (los que generó richprices en el CSV)
periodos = {
    "3m": timedelta(minutes=3),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "4h": timedelta(hours=4),
    "8h": timedelta(hours=8),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24)
}

# Archivo de datos CSV (generado por richprices)
CSV_FILE = "Pricedata.csv"

# Guarda la hora de inicio del script y la fija para el cálculo
hora_inicio_script = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
hora_inicio_calculo = datetime.now()

# Variable global para almacenar resultados previos
resultados_global = {}

def reproducir_sonido():
    """Reproduce un sonido de alerta en segundo plano."""
    pygame.mixer.music.load(SONIDO_ALERTA)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.1)

def generar_alerta_tts(mensaje):
    """Genera una alerta de voz usando una API de TTS (bloqueante)."""
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
        subprocess.run(["ffplay", "-nodisp", "-autoexit", "alerta.mp3"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        console.print(f"❌ Error en la API: {response.status_code}")

def leer_csv():
    """Lee el archivo CSV y devuelve una lista de diccionarios.
       Se asume que el CSV tiene las columnas: Periodo, EPIC, Bid, Offer, Timestamp, Fecha."""
    if not os.path.exists(CSV_FILE):
        console.print(f"[red]El archivo {CSV_FILE} no existe.[/red]")
        return []
    with open(CSV_FILE, mode='r') as file:
        reader = csv.DictReader(file)
        return [dict(row) for row in reader]

def obtener_datos_periodo(datos, epic, periodo):
    """
    En lugar de buscar el timestamp más cercano, 
    buscamos directamente el registro que tenga el campo 'Periodo' igual al periodo deseado.
    Tomamos el último registro encontrado para ese periodo y EPIC.
    """
    # Filtrar solo los registros con EPIC y Periodo iguales
    registros = [fila for fila in datos if fila["EPIC"] == epic and fila["Periodo"] == periodo]
    if not registros:
        return None
    # Tomar el último registro (por ejemplo, el más reciente) 
    # suponiendo que están en orden cronológico o no, 
    # tomamos el último de la lista para ser el "precio base" de ese periodo
    return registros[-1]

def calcular_cambios(hora_inicio, periodo_a_actualizar=None):
    """
    Calcula los cambios de precio en distintos periodos usando las claves del CSV,
    pero en lugar de buscar por timestamp más cercano, 
    usamos directamente el último registro del CSV que tenga 'Periodo' = '3m', '5m', etc.
    """
    global resultados_global
    datos = leer_csv()
    if not datos:
        return resultados_global

    # Reunir todos los EPICs del CSV
    tickers = set(row["EPIC"] for row in datos)
    nuevos_resultados = {}

    for epic in tickers:
        # Recuperar precios base y cambios previos si existen
        precios_base, cambios = resultados_global.get(epic, ({}, {}))
        # Inicializar dict si no existía
        if not precios_base:
            precios_base = {p: "N/A" for p in periodos.keys()}
        if not cambios:
            cambios = {p: "N/A" for p in periodos.keys()}

        # Precio actual = último registro (independientemente del periodo) 
        # con EPIC = epic
        registros_epic = [r for r in datos if r["EPIC"] == epic]
        if not registros_epic:
            continue
        # Tomar el último en orden (suponiendo que están ordenados, 
        # si no, se podría ordenar por Timestamp)
        precio_actual = float(registros_epic[-1]["Bid"])

        for p_label, delta in periodos.items():
            if periodo_a_actualizar and p_label != periodo_a_actualizar:
                continue
            # Buscar el último registro en el CSV con Periodo = p_label
            registro_periodo = obtener_datos_periodo(datos, epic, p_label)
            if registro_periodo:
                base = float(registro_periodo["Bid"])
                precios_base[p_label] = base
                cambio = ((precio_actual - base) / base) * 100
                cambios[p_label] = cambio

                # Si el cambio excede el umbral, disparamos la alerta
                if abs(cambio) >= UMBRAL_ALERTA:
                    console.print(f"[bold red]⚠️ ALARMA: {epic} cambió un {cambio:.2f}% en {p_label}[/bold red]")
                    import threading
                    threading.Thread(target=reproducir_sonido, daemon=True).start()
                    threading.Thread(
                        target=generar_alerta_tts,
                        args=(f"Alerta de cambio en {epic}. Cambio del {cambio:.2f}% en {p_label}.",),
                        daemon=True
                    ).start()

        nuevos_resultados[epic] = (precios_base, cambios)

    resultados_global.update(nuevos_resultados)
    return resultados_global

def crear_tabla_resultados(resultados):
    """Retorna un objeto Table con los cambios de precio para cada ticker."""
    table = Table(title="Análisis de cambios", expand=True)
    table.add_column("EPIC", style="cyan", justify="center")
    for periodo in periodos.keys():
        table.add_column(periodo, justify="center")

    for epic, (precios_base, cambios) in resultados.items():
        fila = [epic]
        for periodo in periodos.keys():
            cambio = cambios.get(periodo, "N/A")
            if isinstance(cambio, float):
                celda = f"[green]{cambio:.2f}%[/green]" if cambio >= 0 else f"[red]{cambio:.2f}%[/red]"
            else:
                celda = "N/A"
            fila.append(celda)
        table.add_row(*fila)
    table.caption = f"Inicio del Script: {hora_inicio_script}"
    return table

def live_progress():
    """
    Muestra y actualiza los cronómetros en dos columnas junto con la tabla de resultados 
    en un único layout. 
    Los cronómetros se envuelven en un Panel cuyo título muestra la hora de inicio del script.
    """
    # Dividir la lista de periodos en dos grupos
    labels = list(periodos.keys())
    mitad = (len(labels) + 1) // 2
    izquierda = labels[:mitad]
    derecha = labels[mitad:]
    
    # Crear dos objetos Progress para cada columna
    progress_left = Progress(
        SpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(),
        TimeRemainingColumn()
    )
    progress_right = Progress(
        SpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(),
        TimeRemainingColumn()
    )
    task_ids_left = {}
    task_ids_right = {}
    
    # Inicializamos los tiempos de inicio para cada intervalo
    start_times = {label: time.time() for label in periodos}
    
    # Calcular cambios inicialmente
    resultados = calcular_cambios(hora_inicio_calculo)
    tabla = crear_tabla_resultados(resultados)
    
    # Layout con dos filas: tabla arriba, cronómetros abajo
    layout = Layout()
    layout.split_column(
        Layout(name="tabla"),
        Layout(name="cronos")
    )
    layout["tabla"].update(tabla)
    
    # Layout para cronómetros (dos columnas), envuelto en un panel
    cronos_layout = Layout()
    cronos_layout.split_row(
        Layout(progress_left, ratio=1),
        Layout(progress_right, ratio=1)
    )
    panel_cronos = Panel(cronos_layout, title=f"Cronómetros (Inicio: {hora_inicio_script})", border_style="magenta")
    layout["cronos"].update(panel_cronos)
    
    # Crear las tareas en los progress
    for label in izquierda:
        total_seg = int(periodos[label].total_seconds())
        task_ids_left[label] = progress_left.add_task(label, total=total_seg, completed=0)
    for label in derecha:
        total_seg = int(periodos[label].total_seconds())
        task_ids_right[label] = progress_right.add_task(label, total=total_seg, completed=0)
    
    # Bucle principal
    with Live(layout, refresh_per_second=1, console=console, vertical_overflow="crop"):
        while True:
            now = time.time()
            # Actualizar columna izquierda
            for label in izquierda:
                total_seg = int(periodos[label].total_seconds())
                elapsed = now - start_times[label]
                if elapsed >= total_seg:
                    start_times[label] = now
                    elapsed = 0
                    # Recalcular cambios solo para este periodo
                    resultados = calcular_cambios(hora_inicio_calculo, periodo_a_actualizar=label)
                    layout["tabla"].update(crear_tabla_resultados(resultados))
                remaining = total_seg - elapsed
                progress_left.update(task_ids_left[label],
                                     completed=elapsed,
                                     total=total_seg,
                                     description=f"{label} - {int(remaining)} s restantes")
            # Actualizar columna derecha
            for label in derecha:
                total_seg = int(periodos[label].total_seconds())
                elapsed = now - start_times[label]
                if elapsed >= total_seg:
                    start_times[label] = now
                    elapsed = 0
                    resultados = calcular_cambios(hora_inicio_calculo, periodo_a_actualizar=label)
                    layout["tabla"].update(crear_tabla_resultados(resultados))
                remaining = total_seg - elapsed
                progress_right.update(task_ids_right[label],
                                      completed=elapsed,
                                      total=total_seg,
                                      description=f"{label} - {int(remaining)} s restantes")
            time.sleep(1)

def main():
    console.clear()
    live_progress()

if __name__ == "__main__":
    main()
