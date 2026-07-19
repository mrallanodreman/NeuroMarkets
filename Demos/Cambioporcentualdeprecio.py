from gtts import gTTS
import os
import csv
import time
import pygame
import subprocess
from datetime import datetime, timedelta
from rich.table import Table
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TimeRemainingColumn
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from queue import Queue
import threading
import requests  # Asegúrate de tener requests instalado

# Webhook opcional para alertas externas
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

# Inicializar pygame para sonidos
pygame.mixer.init()
SONIDO_ALERTA = os.environ.get("NEUROMARKETS_ALERT_SOUND", "sonar.mp3")

# Umbral de alerta para cambios abruptos en porcentaje
UMBRAL_ALERTA = 5.0  # 2% de cambio

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

# Cola para mensajes de alerta TTS
alert_queue = Queue()

def alert_worker():
    """Trabaja en la cola de alertas y reproduce los mensajes TTS uno tras otro."""
    while True:
        mensaje = alert_queue.get()  # Bloquea hasta que hay un mensaje
        if mensaje is None:
            break  # Permite salir del bucle si se encola None
        generar_alerta_tts(mensaje)
        alert_queue.task_done()

# Iniciar el worker de alertas en un hilo separado (daemon)
threading.Thread(target=alert_worker, daemon=True).start()

# Variables y lock para controlar la reproducción única del sonido
sound_lock = threading.Lock()
sound_playing = False

def reproducir_sonido():
    """Reproduce un sonido de alerta en segundo plano, evitando solapamientos."""
    global sound_playing
    if not os.path.exists(SONIDO_ALERTA):
        return
    with sound_lock:
        if sound_playing:
            return  # Si el sonido ya se está reproduciendo, no se lanza otro
        sound_playing = True
    try:
        pygame.mixer.music.load(SONIDO_ALERTA)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
    finally:
        with sound_lock:
            sound_playing = False

def generar_alerta_tts(mensaje):
    """Genera una alerta de voz usando gTTS (Text-to-Speech) en Linux."""
    tts = gTTS(mensaje, lang='es')
    tts.save("alerta.mp3")
    subprocess.run(
        ["ffplay", "-nodisp", "-autoexit", "alerta.mp3"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def enviar_alerta_discord(mensaje):
    """Envía un mensaje de alerta al canal de Discord usando el webhook."""
    if not DISCORD_WEBHOOK_URL:
        return
    data = {"content": mensaje}
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=10)
        if response.status_code != 204:
            console.print(f"[red]Error enviando mensaje a Discord: {response.status_code}[/red]")
    except Exception as exc:
        console.print(f"[red]No se pudo enviar alerta a Discord: {exc}[/red]")

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
    Busca el último registro del CSV para un EPIC y periodo específico.
    """
    registros = [fila for fila in datos if fila["EPIC"] == epic and fila["Periodo"] == periodo]
    if not registros:
        return None
    return registros[-1]

def formatear_periodo(p_label):
    """Convierte abreviaturas de periodos a un formato legible para TTS."""
    if p_label.endswith("m"):
        return p_label[:-1] + " minutos"
    elif p_label.endswith("h"):
        return p_label[:-1] + " horas"
    else:
        return p_label

def calcular_cambios(hora_inicio, periodo_a_actualizar=None):
    """
    Calcula los cambios de precio en distintos periodos usando los datos del CSV.
    Solo envía alertas y mensajes a Discord cuando se especifica el parámetro
    'periodo_a_actualizar' (es decir, cuando se dispara el cronómetro para reiniciar el cálculo).
    """
    global resultados_global
    datos = leer_csv()
    if not datos:
        return resultados_global

    tickers = set(row["EPIC"] for row in datos)
    nuevos_resultados = {}

    for epic in tickers:
        precios_base, cambios = resultados_global.get(epic, ({}, {}))
        if not precios_base:
            precios_base = {p: "N/A" for p in periodos.keys()}
        if not cambios:
            cambios = {p: "N/A" for p in periodos.keys()}

        registros_epic = [r for r in datos if r["EPIC"] == epic]
        if not registros_epic:
            continue
        precio_actual = float(registros_epic[-1]["Bid"])

        for p_label, delta in periodos.items():
            if periodo_a_actualizar and p_label != periodo_a_actualizar:
                continue
            registro_periodo = obtener_datos_periodo(datos, epic, p_label)
            if registro_periodo:
                base = float(registro_periodo["Bid"])
                precios_base[p_label] = base
                cambio = ((precio_actual - base) / base) * 100
                cambios[p_label] = cambio

                # Se envían las alertas SOLO cuando se dispara el cronómetro (periodo_a_actualizar no es None)
                if periodo_a_actualizar is not None and abs(cambio) >= UMBRAL_ALERTA:
                    console.print(f"[bold red]⚠️ ALARMA: {epic} cambió un {cambio:.2f}% en {p_label}[/bold red]")
                    # Reproducir sonido de alerta una sola vez
                    threading.Thread(target=reproducir_sonido, daemon=True).start()
                    # Formatear el mensaje para TTS y Discord dependiendo del signo del cambio
                    if cambio < 0:
                        mensaje = f"Alerta de cambio en {epic}. Cambio a la baja de {abs(cambio):.2f}% en {formatear_periodo(p_label)}."
                    else:
                        mensaje = f"Alerta de cambio en {epic}. Cambio al alza de {cambio:.2f}% en {formatear_periodo(p_label)}."
                    # Encolar el mensaje TTS (se reproducirá secuencialmente)
                    alert_queue.put(mensaje)
                    # Enviar el mensaje a Discord en un hilo separado
                    threading.Thread(target=enviar_alerta_discord, args=(mensaje,), daemon=True).start()

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
    labels = list(periodos.keys())
    mitad = (len(labels) + 1) // 2
    izquierda = labels[:mitad]
    derecha = labels[mitad:]

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

    start_times = {label: time.time() for label in periodos}

    # Primera actualización sin disparar alertas (periodo_a_actualizar es None)
    resultados = calcular_cambios(hora_inicio_calculo)
    tabla = crear_tabla_resultados(resultados)

    layout = Layout()
    layout.split_column(
        Layout(name="tabla"),
        Layout(name="cronos")
    )
    layout["tabla"].update(tabla)

    cronos_layout = Layout()
    cronos_layout.split_row(
        Layout(progress_left, ratio=1),
        Layout(progress_right, ratio=1)
    )
    panel_cronos = Panel(cronos_layout, title=f"Cronómetros (Inicio: {hora_inicio_script})", border_style="magenta")
    layout["cronos"].update(panel_cronos)

    for label in izquierda:
        total_seg = int(periodos[label].total_seconds())
        task_ids_left[label] = progress_left.add_task(label, total=total_seg, completed=0)
    for label in derecha:
        total_seg = int(periodos[label].total_seconds())
        task_ids_right[label] = progress_right.add_task(label, total=total_seg, completed=0)

    with Live(layout, refresh_per_second=1, console=console, vertical_overflow="crop"):
        while True:
            now = time.time()
            for label in izquierda:
                total_seg = int(periodos[label].total_seconds())
                elapsed = now - start_times[label]
                if elapsed >= total_seg:
                    start_times[label] = now
                    elapsed = 0
                    # Se dispara el cronómetro: se actualiza y se envían alertas si corresponde
                    resultados = calcular_cambios(hora_inicio_calculo, periodo_a_actualizar=label)
                    layout["tabla"].update(crear_tabla_resultados(resultados))
                remaining = total_seg - elapsed
                progress_left.update(task_ids_left[label],
                                     completed=elapsed,
                                     total=total_seg,
                                     description=f"{label} - {int(remaining)} s restantes")
            for label in derecha:
                total_seg = int(periodos[label].total_seconds())
                elapsed = now - start_times[label]
                if elapsed >= total_seg:
                    start_times[label] = now
                    elapsed = 0
                    # Se dispara el cronómetro: se actualiza y se envían alertas si corresponde
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
