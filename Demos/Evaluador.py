#!/usr/bin/env python3
# ===============================================
# IMPORTS
# ===============================================
import asyncio
import curses
import time
import requests
import json
import builtins
import os
import sys
import subprocess
import threading
from datetime import datetime, timezone
import math
import queue

# Imports adicionales específicos
from MomentumHub import add_tick, get_metrics
from DataLoader import DataLoader
from EthConfig import BASE_URL, API_KEY, LOGIN, PASSWORD
from EthSession import CapitalOP

# Cache para DataLoader (recargar cada 60s)
_dl_cache = {'time': 0, 'htf': None, 'ltf': None}

# ------------------- Deuda por overnight fee ------------------- #
# Flat $0.01 por posición cada 24h (~0.01/24 = 0.0004167 por hora)
DEBT_RATE_PER_HOUR = 0.01 / 24.0  # $ por posición por hora
STRATEGY_CLOSE_SCORE_MIN = 6.0  # 6/8 o ~75/100: score fuerte, no forzar cierre


def _normalize_strategy_score(raw_score):
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return None
    if score > 8.0:
        score = score / 12.5  # 100 -> 8, 75 -> 6
    return max(0.0, min(score, 8.0))


def _get_strategy_score(*candidates):
    for candidate in candidates:
        score = _normalize_strategy_score(candidate)
        if score is not None:
            return score
    return None


def _calculate_accumulated_debt(hours_open, size):
    try:
        hours = float(hours_open)
        qty = float(size)
    except (TypeError, ValueError):
        return 0.0
    if hours <= 0 or qty <= 0:
        return 0.0
    return hours * DEBT_RATE_PER_HOUR

# ------------------- Momentum y Logging Centralizado ------------------- #

class MomentumCapture:
    def __init__(self):
        self.ticks = []  # [(timestamp, price)]
        self.running = False
        self.lock = threading.Lock()
        self.last_price = None
        self.momentum_data = {
            'velocidad': 0.0,
            'aceleracion': 0.0,
            'score': 0.0,
            'direccion': 'N/A',
            'ultimo': 0.0
        }

    def start(self, price_source_func):
        if self.running:
            return
        self.running = True
        thread = threading.Thread(target=self._capture_loop, args=(price_source_func,), daemon=True)
        thread.start()

    def _capture_loop(self, price_source_func):
        while self.running:
            price = price_source_func()
            now = time.time()
            with self.lock:
                self.ticks.append((now, price))
                self.last_price = price
                # Mantener solo últimos 120 ticks (2 minutos)
                self.ticks = self.ticks[-120:]
                self._calc_momentum()
            time.sleep(1)

    def _calc_momentum(self):
        if len(self.ticks) < 2:
            return
        t0, p0 = self.ticks[-2]
        t1, p1 = self.ticks[-1]
        dt = t1 - t0
        if dt == 0:
            return
        velocidad = (p1 - p0) / dt
        aceleracion = 0.0
        if len(self.ticks) >= 3:
            t_2, p_2 = self.ticks[-3]
            v0 = (p0 - p_2) / (t0 - t_2) if (t0 - t_2) != 0 else 0
            aceleracion = (velocidad - v0) / dt
        score = velocidad * 1000  # Escala para visualización
        direccion = '⬆️' if velocidad > 0 else ('⬇️' if velocidad < 0 else '→')
        self.momentum_data = {
            'velocidad': velocidad,
            'aceleracion': aceleracion,
            'score': score,
            'direccion': direccion,
            'ultimo': p1
        }

    def get_momentum(self):
        with self.lock:
            return dict(self.momentum_data)

# Logging centralizado para panel de logs
class UILogger:
    def __init__(self, log_list):
        self.log_list = log_list
    def log(self, msg):
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        self.log_list.append(f"{timestamp} {msg}")
        if len(self.log_list) > 15:
            self.log_list.pop(0)

# IPC file path para leer último tick escrito por EthBoy
TICK_IPC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "momentum_tick.json")

# 🔍 SISTEMA DE TRACKING DE CIERRES
# Archivo para tracking de posiciones vistas (detectar cierres desde web)
LAST_SEEN_POSITIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_seen_positions.json")
# 🕳️ LIMBO: posiciones que desaparecieron 1 ciclo pero aún no confirmadas (evitar falsos positivos al reiniciar)
DISAPPEARED_LIMBO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "disappeared_limbo.json")

# 🎯 HELPER: Detectar winners y activar re-entrada rápida
def get_current_market_signal():
    """
    Intenta obtener la señal actual del mercado desde archivos IPC disponibles.
    Retorna la señal como string (ej: "BUY ✅", "SELL ❌", "HOLD ⚠️") o '' si no está disponible.
    """
    signal = ''

    # 1. Leer última línea de process_data.jsonl (sin cargar todo)
    try:
        process_data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "process_data.jsonl")
        if os.path.exists(process_data_path):
            with open(process_data_path, 'rb') as f:
                f.seek(0, 2)
                pos = f.tell()
                while pos > 0:
                    pos -= 1
                    f.seek(pos)
                    if f.read(1) == b'\n':
                        break
                last_line = f.read().decode().strip()
                if last_line:
                    data = json.loads(last_line)
                    signal = data.get('signal', '')
                    if signal:
                        return signal
    except Exception:
        pass

    # 2. Intentar leer desde un archivo de estado IPC si existe (futuro)
    # TODO: EthBoy podría escribir un archivo market_state.json con la señal actual

    return signal

def check_and_activate_fast_reentry(deal_id, direction, max_profit_pct, current_signal='', debug_callback=None):
    """
    Detecta si un cierre fue un "winner" (max_profit >= 10%) con tendencia continuada.
    Si es así, actualiza eth_trade_cooldown.json con allow_fast_reentry=True.

    Args:
        deal_id: ID de la posición cerrada
        direction: Dirección de la posición cerrada ('BUY' o 'SELL')
        max_profit_pct: Máximo profit alcanzado (%)
        current_signal: Señal actual del mercado (ej: "BUY ✅", "SELL ❌")
        debug_callback: Función de logging opcional
    """
    try:
        # Verificar si fue un winner (max_profit >= 10%)
        if max_profit_pct < 10.0:
            return  # No es winner, salir

        # Determinar dirección del winner y de la señal actual
        winner_direction = direction.upper() if direction else ''
        signal_direction = 'BUY' if 'BUY' in current_signal else ('SELL' if 'SELL' in current_signal else '')

        # Verificar si la tendencia continúa en la misma dirección
        if winner_direction == signal_direction and winner_direction in ['BUY', 'SELL']:
            # 🚀 WINNER CON TENDENCIA CONTINUADA: Activar re-entrada rápida
            cooldown_file = 'eth_trade_cooldown.json'

            try:
                with open(cooldown_file, 'r') as f:
                    cooldown_data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                cooldown_data = {}

            cooldown_data['allow_fast_reentry'] = True

            with open(cooldown_file, 'w') as f:
                json.dump(cooldown_data, f, indent=2)

            msg = f"🎯 WINNER DETECTADO: {winner_direction} cerrado con {max_profit_pct:.2f}% max profit, tendencia continúa {signal_direction} → Fast re-entry activado"

            if debug_callback:
                debug_callback(msg)
            else:
                print(msg)
    except Exception as e:
        if debug_callback:
            debug_callback(f"[WARNING] check_and_activate_fast_reentry falló: {e}")

def save_closure_reason(deal_id, reason, upl, direction, epic, timestamp=None):
    """Guarda la razón de cierre y muestra panel en pantalla"""
    if not timestamp:
        timestamp = datetime.now().isoformat()

    closure_data = {
        "timestamp": timestamp,
        "deal_id": deal_id,
        "direction": direction,
        "epic": epic,
        "upl": float(upl),
        "reason": reason
    }

    # 📄 Guardar en archivo de log
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_closures_log.json")
    try:
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                closures = json.load(f)
        else:
            closures = []
        closures.append(closure_data)
        closures = closures[-50:]
        with open(log_file, "w") as f:
            json.dump(closures, f, indent=2)
    except Exception as e:
        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"⚠️ Error guardando closure log: {e}")

    ui = globals().get('ui', None)
    msg = (
        f"🔴 ÚLTIMO TRADE CERRADO\n"
        f"📅 Hora: {timestamp[:19]}\n"
        f"🆔 Deal: {deal_id[-8:] if len(deal_id) > 8 else deal_id}\n"
        f"📊 Dirección: {direction} | Epic: {epic}\n"
        f"💰 PnL: ${upl:.4f}\n"
        f"📋 Razón: {reason}\n"
        + "="*60
    )
    if ui:
        ui.add_log(msg)
    # Si no hay UI, no mostrar nada en consola

    # 💾 Archivo de último cierre (para referencia rápida)
    last_closure_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_trade_closure.txt")
    try:
        with open(last_closure_file, "w") as f:
            f.write(f"ÚLTIMO TRADE CERRADO - {timestamp[:19]}\n")
            f.write(f"Deal: {deal_id[-8:]}\n")
            f.write(f"Dirección: {direction} | Epic: {epic}\n")
            f.write(f"PnL: ${upl:.4f}\n")
            f.write(f"Razón: {reason}\n")
    except Exception as e:
        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"⚠️ Error guardando last closure: {e}")

# ------------------- Configuración de la API ------------------- #
SESSION_ENDPOINT = "api/v1/session"
POSITIONS_ENDPOINT = "/api/v1/positions"

# ------------------- Sonidos ------------------- #
# Rastreo de cuándo fue el último sonido para evitar spam
last_sound_time = {}
SOUND_COOLDOWN_SECONDS = 2.0  # Cooldown entre sonidos del mismo tipo

# Mapeo de eventos a archivos de sonido
SOUND_MAP = {
    'open_position': [  # Posiciones abiertas - sonido de campana
        '/usr/share/sounds/freedesktop/stereo/bell.oga',
        '/usr/share/sounds/freedesktop/stereo/message-new-instant.oga',
    ],
    'close_position': [  # Posiciones cerradas - sonido de moneda
        '/usr/share/sounds/sound-icons/cembalo-1.wav',
        '/usr/share/sounds/sound-icons/piano-3.wav',
    ],
    'positive_position': [  # Posiciones en positivo - sonido de gota
        '/usr/share/sounds/sound-icons/glass-water-1.wav',
    ]
}

def play_sound(event_type, debug_callback=None):
    """
    Reproduce un sonido según el tipo de evento.

    Args:
        event_type: 'open_position', 'close_position', o 'positive_position'
        debug_callback: función opcional para logging
    """
    global last_sound_time

    current_time = time.time()

    # Verificar cooldown SOLO para open_position y close_position
    # positive_position no tiene cooldown porque se controla por posición individual
    if event_type in ['open_position', 'close_position']:
        if event_type in last_sound_time:
            if current_time - last_sound_time[event_type] < SOUND_COOLDOWN_SECONDS:
                return

    def play_sound_async():
        success = False
        method_used = None

        # Intentar reproducir los sonidos específicos del evento
        sound_files = SOUND_MAP.get(event_type, [])
        for sound_file in sound_files:
            try:
                subprocess.run(['paplay', sound_file],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
                success = True
                method_used = sound_file.split('/')[-1]
                break
            except:
                pass

        # Fallback: beep del terminal
        if not success:
            try:
                # No emitir beep en consola
                success = True
                method_used = "terminal_beep"
            except:
                pass

        if debug_callback:
            event_names = {
                'open_position': '🆕 Nueva posición',
                'close_position': '💰 Posición cerrada',
                'positive_position': '💚 Cambió a positivo'
            }
            if success:
                debug_callback(f"🔔 {event_names.get(event_type, event_type)}: {method_used}")
            else:
                debug_callback(f"⚠️ No se pudo reproducir sonido para {event_type}")

    # Reproducir en un thread separado para no bloquear la UI
    sound_thread = threading.Thread(target=play_sound_async, daemon=True)
    sound_thread.start()

    # Actualizar timestamp del último sonido (solo para eventos con cooldown)
    if event_type in ['open_position', 'close_position']:
        last_sound_time[event_type] = current_time

# Mantener compatibilidad con función antigua
def play_positive_position_sound(deal_id, debug_callback=None):
    play_sound('positive_position', debug_callback)


def authenticate():
    url = BASE_URL + SESSION_ENDPOINT
    headers = {"X-CAP-API-KEY": API_KEY, "Content-Type": "application/json"}
    data = {"encryptedPassword": False, "identifier": LOGIN, "password": PASSWORD}
    MAINTENANCE_RETRY_INTERVAL = 1800  # 30 minutos
    while True:
        try:
            response = requests.post(url, headers=headers, json=data, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"[MAINTENANCE] ❌ Error de conexión: {e}. Reintentando en 30 min...")
            import time as _time
            _time.sleep(MAINTENANCE_RETRY_INTERVAL)
            continue
        resp_text = response.text.lower()
        is_maintenance = (
            response.status_code == 503
            or (response.status_code == 401 and ("maintance" in resp_text or "maintenance" in resp_text))
            or "temporarily-unavailable" in resp_text
            or "temporarily.unavailable" in resp_text
        )
        if is_maintenance:
            from datetime import datetime as _dt
            print(f"[WARNING] 🔧 Servidor en MODO MANTENIMIENTO ({response.status_code}). Esperando reconexión cada 30 minutos...")
            ui = globals().get('ui', None)
            if ui:
                ui.add_log(f"[WARNING] 🔧 Servidor en MODO MANTENIMIENTO ({response.status_code}). Reintentando en 30 min...")
            print(f"[MAINTENANCE] 🔧 Próximo intento en 30 minutos ({_dt.now().strftime('%H:%M:%S')})...")
            import time as _time
            _time.sleep(MAINTENANCE_RETRY_INTERVAL)
            print(f"[MAINTENANCE] 🔄 Reintentando conexión tras mantenimiento ({_dt.now().strftime('%H:%M:%S')})...")
            continue
        response.raise_for_status()
        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"[DEBUG] Respuesta de autenticación: {response.json()}")
        return response.json(), response.headers

def log_closed_position(details):
    try:
        # Validar que existan las claves necesarias
        required_keys = ['dealId', 'epic', 'direction', 'size', 'reason']
        for key in required_keys:
            if key not in details:
                ui = globals().get('ui', None)
                if ui:
                    ui.add_log(f"[WARNING] ⚠️ Clave '{key}' faltante en details, usando 'N/A'")
                details[key] = 'N/A'

        # Adicional: incluir exit_price y close_indicators si están disponibles
        exit_price = details.get('exit_price', None)
        close_inds = details.get('close_indicators', None)

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "closed_positions.txt"), "a", encoding="utf-8") as file:
            timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            base = (f"{timestamp} | DealID: {details['dealId']} | EPIC: {details['epic']} | "
                    f"Direction: {details['direction']} | Size: {details['size']} | "
                    f"Reason: {details['reason']}")
            if details.get('strategy_score') is not None:
                try:
                    base += f" | StrategyScore: {float(details['strategy_score']):.1f}/8"
                except Exception:
                    base += f" | StrategyScore: {details['strategy_score']}"
            if exit_price is not None:
                try:
                    base += f" | Exit: ${float(exit_price):.6f}"
                except Exception:
                    base += f" | Exit: {exit_price}"
            if close_inds:
                # Resumir indicadores clave para la línea de texto (evitar volcar todo el dict)
                try:
                    keys = ['Close', 'RSI', 'MACD', 'ATR', 'VolumeChange', 'EMA_3', 'EMA_9', 'ADX']
                    summary = []
                    for k in keys:
                        if k in close_inds:
                            summary.append(f"{k}={close_inds[k]}")
                    if not summary:
                        # Si no se encontraron keys, volcar el dict como string limitado
                        summary_str = str(close_inds)
                    else:
                        summary_str = ",".join(summary)
                    base += f" | Indicators: {summary_str}"
                except Exception:
                    try:
                        base += f" | Indicators: {str(close_inds)}"
                    except Exception:
                        pass
            base += "\n"
            file.write(base)
        # 🧠 Exportar para bot IA
        export_trade_for_ai(details)
    except Exception as e:
        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"[ERROR] No se pudo registrar cierre en archivo: {e}")

def log_web_closed_position(details):
    """Registra posiciones cerradas desde la web (no por el bot)"""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_closed_positions.txt"), "a", encoding="utf-8") as file:
            timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

            deal_id = details.get('dealId', 'N/A')
            epic = details.get('epic', 'N/A')
            direction = details.get('direction', 'N/A')
            size = details.get('size', 'N/A')
            entry_price = details.get('entry_price', 'N/A')
            last_upl = details.get('last_upl', 'N/A')
            last_upl_pct = details.get('last_upl_pct', 'N/A')
            max_profit_pct = details.get('max_profit_pct', 'N/A')
            hours_open = details.get('hours_open', 'N/A')
            last_seen = details.get('last_seen_time', 'N/A')

            line = (f"{timestamp} | 🌐 CERRADO DESDE WEB | DealID: {deal_id} | "
                   f"EPIC: {epic} | Direction: {direction} | Size: {size} | "
                   f"Entry: ${entry_price} | Last UPL: ${last_upl} ({last_upl_pct}%) | "
                   f"Max Profit: {max_profit_pct}% | Hours Open: {hours_open} | "
                   f"Last Seen: {last_seen}\n")
            file.write(line)

        # También guardarlo en formato JSON para análisis
        web_closed_json = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_closed_positions.json")
        try:
            with open(web_closed_json, 'r') as f:
                web_closures = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            web_closures = []

        # 🔒 ANTI-DUPLICADOS: Verificar si este dealId ya existe
        deal_id_to_add = details.get('dealId')
        existing_index = None
        for idx, existing in enumerate(web_closures):
            if existing.get('dealId') == deal_id_to_add:
                existing_index = idx
                break

        new_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dealId": deal_id_to_add,
            "epic": details.get('epic'),
            "direction": details.get('direction'),
            "size": details.get('size'),
            "entry_price": details.get('entry_price'),
            "last_upl": details.get('last_upl'),
            "last_upl_pct": details.get('last_upl_pct'),
            "max_profit_pct": details.get('max_profit_pct'),
            "hours_open": details.get('hours_open'),
            "last_seen_time": details.get('last_seen_time'),
            "last_indicators": details.get('last_indicators', {}),
            "strategy_score": details.get('strategy_score')
        }

        if existing_index is not None:
            # Ya existe: actualizar registro existente (mantener solo UNA entrada)
            web_closures[existing_index] = new_record
            ui = globals().get('ui', None)
            if ui:
                ui.add_log(f"[WEB] 🔄 Actualizando cierre existente: {deal_id_to_add[-8:]} (evitando duplicado)")
        else:
            # Nuevo: agregar normalmente
            web_closures.append(new_record)

        with open(web_closed_json, 'w') as f:
            json.dump(web_closures, f, indent=2)

        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"[WEB] 🌐 Detectado cierre desde web: {deal_id[-6:]} ({direction}) UPL: {last_upl_pct}%")

    except Exception as e:
        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"[ERROR] No se pudo registrar cierre desde web: {e}")

def sync_closed_from_history(capital_ops, days_back=7, debug_callback=None):
    """
    Consulta el historial de actividad de Capital.com y sincroniza cierres de
    posiciones a web_closed_positions.json.
    Llama a esto al arrancar y periodicamente para nunca perder un cierre.
    """
    try:
        activities = capital_ops.get_activity_history(days_back=days_back)
        if not activities:
            if debug_callback:
                debug_callback("[SYNC] Sin actividad en historial de Capital.com")
            return 0

        web_closed_json = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_closed_positions.json")
        try:
            with open(web_closed_json, 'r') as f:
                web_closures = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            web_closures = []

        existing_deal_ids = {r.get('dealId') for r in web_closures if r.get('dealId')}

        new_count = 0
        for txn in activities:
            # Solo cierres TRADE con note 'Trade closed' y status PROCESSED
            if txn.get('transactionType', '') != 'TRADE':
                continue
            note = txn.get('note', '').lower()
            if 'closed' not in note:
                continue
            if txn.get('status', '') != 'PROCESSED':
                continue

            deal_id = txn.get('dealId', '')
            if not deal_id or deal_id in existing_deal_ids:
                continue

            date_str = txn.get('date', '')
            # instrumentName es ej. 'ETHUSD'; referencia cruzada con reference
            instrument = txn.get('instrumentName', 'ETHUSD')
            size_raw = txn.get('size', '0')
            # size positivo = BUY cerrado, negativo = SELL cerrado
            try:
                size_val = float(size_raw)
                direction = 'BUY' if size_val >= 0 else 'SELL'
                size_abs = str(abs(size_val))
            except (ValueError, TypeError):
                direction = 'N/A'
                size_abs = size_raw

            new_record = {
                "timestamp": date_str if date_str else datetime.now(timezone.utc).isoformat(),
                "dealId": deal_id,
                "epic": instrument,
                "direction": direction,
                "size": size_abs,
                "entry_price": None,
                "last_upl": None,
                "last_upl_pct": None,
                "max_profit_pct": 0,
                "hours_open": None,
                "last_seen_time": date_str,
                "last_indicators": {},
                "source": "transactions_api",
                "reference": txn.get('reference', '')
            }
            web_closures.append(new_record)
            existing_deal_ids.add(deal_id)
            new_count += 1

        if new_count > 0:
            with open(web_closed_json, 'w') as f:
                json.dump(web_closures, f, indent=2)
            if debug_callback:
                debug_callback(f"[SYNC] {new_count} nuevos cierres sincronizados desde Capital.com history API")
        else:
            if debug_callback:
                debug_callback("[SYNC] Sin nuevos cierres en historial de Capital.com")
        return new_count
    except Exception as e:
        if debug_callback:
            debug_callback(f"[SYNC] Error en sync_closed_from_history: {e}")
        return 0


def export_trade_for_ai(details):
    """Exporta información del trade en formato JSON para consumo del bot IA"""
    try:
        # Validar que details sea un diccionario
        if not isinstance(details, dict):
            ui = globals().get('ui', None)
            if ui:
                ui.add_log(f"[WARNING] ⚠️ export_trade_for_ai recibió datos inválidos: {type(details)}")
            return

        ai_data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_trading_data.json")

        # Leer datos existentes con manejo de errores
        try:
            if os.path.exists(ai_data_file):
                with open(ai_data_file, 'r') as f:
                    data = json.load(f)
                # Validar estructura
                if not isinstance(data, dict):
                    ui = globals().get('ui', None)
                    if ui:
                        ui.add_log(f"[WARNING] ⚠️ Estructura inválida en {ai_data_file}, reseteando")
                    data = None
            else:
                data = None
        except (json.JSONDecodeError, IOError) as e:
            ui = globals().get('ui', None)
            if ui:
                ui.add_log(f"[WARNING] ⚠️ Error al leer {ai_data_file}: {e}, creando nuevo archivo")
            data = None

        # Inicializar estructura si no existe o está corrupta
        if data is None:
            data = {
                "last_update": None,
                "account_balance": 0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0,
                "recent_trades": [],
                "open_positions": []
            }

        # Calcular PnL del trade con validación
        pnl = 0
        try:
            pnl = float(details.get('pnl', 0))
        except (ValueError, TypeError):
            ui = globals().get('ui', None)
            if ui:
                ui.add_log(f"[WARNING] ⚠️ PnL inválido en details: {details.get('pnl')}")

        # Construir trade data con valores seguros
        trade_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "deal_id": str(details.get('dealId', 'UNKNOWN')),
            "epic": str(details.get('epic', 'UNKNOWN')),
            "type": str(details.get('direction', 'UNKNOWN')),
            "entry_price": float(details.get('entry_price', 0)),
            "exit_price": float(details.get('exit_price', 0)),
            "size": float(details.get('size', 0)),
            "pnl": pnl,
            "pnl_pct": float(details.get('pnl_pct', 0)),
            "duration": float(details.get('duration', 0)),
            "reason": str(details.get('reason', 'MANUAL'))
        }
        # Incluir snapshot de indicadores al cierre si está disponible (útil para entrenamiento/forense)
        try:
            close_inds = details.get('close_indicators', None)
            if close_inds and isinstance(close_inds, dict):
                trade_entry['close_indicators'] = close_inds
            else:
                # permitir también entry indicators si se proporcionan
                entry_inds = details.get('entry_indicators', None)
                if entry_inds and isinstance(entry_inds, dict):
                    trade_entry['entry_indicators'] = entry_inds
        except Exception:
            pass

        # Actualizar estadísticas de forma segura
        data["total_trades"] = data.get("total_trades", 0) + 1
        data["total_pnl"] = data.get("total_pnl", 0) + pnl

        if pnl > 0:
            data["winning_trades"] = data.get("winning_trades", 0) + 1
        else:
            data["losing_trades"] = data.get("losing_trades", 0) + 1

        # Agregar a historial (mantener últimos 100)
        if "recent_trades" not in data or not isinstance(data["recent_trades"], list):
            data["recent_trades"] = []
        data["recent_trades"].append(trade_entry)
        if len(data["recent_trades"]) > 100:
            data["recent_trades"] = data["recent_trades"][-100:]

        data["last_update"] = datetime.now(timezone.utc).isoformat()

        # Guardar
        with open(ai_data_file, 'w') as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"[ERROR] No se pudo exportar para IA: {e}")

def update_open_positions_for_ai(positions_list, account_balance):
    """Actualiza posiciones abiertas para el bot IA"""
    try:
        ai_data_file = "ai_trading_data.json"

        # Leer datos existentes
        if os.path.exists(ai_data_file):
            try:
                with open(ai_data_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
                    else:
                        # Archivo vacío, crear estructura nueva
                        data = None
            except (json.JSONDecodeError, ValueError) as e:
                ui = globals().get('ui', None)
                if ui:
                    ui.add_log(f"[WARN] Archivo JSON corrupto, recreando: {e}")
                data = None
        else:
            data = None

        if data is None:
            data = {
                "last_update": None,
                "account_balance": 0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "total_pnl": 0,
                "recent_trades": [],
                "open_positions": []
            }

        # Actualizar balance y posiciones
        data["account_balance"] = account_balance
        data["last_update"] = datetime.now(timezone.utc).isoformat()

        # Procesar posiciones abiertas
        open_positions = []
        for pos in positions_list:
            market = pos.get("market", {})
            position = pos.get("position", {})

            open_positions.append({
                "deal_id": position.get("dealId"),
                "epic": market.get("epic"),
                "instrument": market.get("instrumentName"),
                "direction": position.get("direction"),
                "size": position.get("size"),
                "level": position.get("level"),
                "upl": position.get("upl", 0),
                "created": position.get("createdDateUTC") or position.get("createdDate")
            })

        data["open_positions"] = open_positions

        # Guardar
        with open(ai_data_file, 'w') as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"[ERROR] No se pudo actualizar posiciones para IA: {e}")



def log_debug_message(panel, messages, message=None):
    """
    Registra un mensaje de debug en el panel.
    Se limita a 10 mensajes.
    """
    try:
        if message:
            messages.append(message)
            if len(messages) > 10:
                messages.pop(0)

        if panel is None:
            # Fallback si el panel no está disponible
            if message:
                ui = globals().get('ui', None)
                if ui:
                    ui.add_log(f"[DEBUG] {message}")
            return
        panel.erase()
        panel.box()
        safe_addstr(panel, 0, 2, "DEBUG LOG", curses.A_BOLD)
        row = 1
        for msg in messages:
            safe_addstr(panel, row, 2, msg[:panel.getmaxyx()[1]-4])
            row += 1
        panel.refresh()
    except Exception as e:
        # Si falla el panel, al menos imprimir en consola
        if message:
            ui = globals().get('ui', None)
            if ui:
                ui.add_log(f"[DEBUG] {message}")

def change_account(cst, security_token, account_id):
    url = f"{BASE_URL.rstrip('/')}/api/v1/session"
    headers = {
        "X-CAP-API-KEY": API_KEY,
        "Content-Type": "application/json",
        "CST": cst,
        "X-SECURITY-TOKEN": security_token,
    }
    data = {"accountId": account_id}
    response = requests.put(url, headers=headers, json=data)
    response.raise_for_status()
    new_token = response.headers.get("X-SECURITY-TOKEN")
    if not new_token:
        new_token = security_token
    return new_token

def get_positions(cst, security_token):
    url = f"{BASE_URL.rstrip('/')}{POSITIONS_ENDPOINT}"
    headers = {
        "X-CAP-API-KEY": API_KEY,
        "CST": cst,
        "X-SECURITY-TOKEN": security_token,
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

# ------------------- Funciones auxiliares para curses ------------------- #
def safe_addstr(win, y, x, text, attr=curses.A_NORMAL):
    max_y, max_x = win.getmaxyx()
    if y < max_y and x < max_x:
        try:
            win.addnstr(y, x, text, max_x - x, attr)
        except curses.error:
            pass


def draw_momentum_panel(panel, metrics):
    """Dibuja el panel de momentum de forma segura.

    Usa claves según `MomentumAnalyzer.get_metrics()` y maneja valores None.
    """
    panel.erase()
    try:
        panel.box()
    except Exception:
        try:
            panel.border()
        except Exception:
            pass

    safe_addstr(panel, 0, 2, "📈 MOMENTUM", curses.A_BOLD)

    # Normalizar métricas esperadas
    price = metrics.get('price') if isinstance(metrics, dict) else None
    if price is None:
        price = 0.0
    velocity = metrics.get('velocity', 0.0) if isinstance(metrics, dict) else 0.0
    acceleration = metrics.get('acceleration', 0.0) if isinstance(metrics, dict) else 0.0
    score = metrics.get('momentum_score', 0.0) if isinstance(metrics, dict) else 0.0
    direction = metrics.get('direction', 'NEUTRAL') if isinstance(metrics, dict) else 'NEUTRAL'
    # Lógica de score más lógica y progresiva
    if score <= 0:
        estado_score = 'NULO'
    elif score < 20:
        estado_score = 'MUY DÉBIL'
    elif score < 40:
        estado_score = 'DÉBIL'
    elif score < 60:
        estado_score = 'MODERADO'
    elif score < 90:
        estado_score = 'FUERTE'
    else:
        estado_score = 'MUY FUERTE'

    # Estado textual de la aceleración
    if acceleration > 0.01:
        estado_acc = 'ACELERANDO'
    elif acceleration < -0.01:
        estado_acc = 'DESACELERANDO'
    else:
        estado_acc = 'NEUTRO'

    tick_count = metrics.get('tick_count', 0) if isinstance(metrics, dict) else 0
    safe_addstr(panel, 1, 2, f"Precio: {price:.2f}  {direction}  (ticks: {tick_count})")
    safe_addstr(panel, 2, 2, f"Velocidad: {velocity:.5f}  Aceleración: {acceleration:.5f}  Estado: {estado_acc}")
    safe_addstr(panel, 3, 2, f"Score: {score:.2f}  Estado: {estado_score}")
    panel.refresh()

def calc_open_time(created_str):
    try:
        if created_str.endswith("Z"):
            created_str = created_str.replace("Z", "+00:00")
        dt_created = datetime.fromisoformat(created_str)
        if dt_created.tzinfo is None:
            dt_created = dt_created.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt_created
        total_hours = delta.days * 24 + delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        return f"{total_hours}h{minutes:02d}"
    except Exception:
        return "N/A"

def draw_positions_table(panel, positions_list, mode, previous_upl):
    panel.erase()
    # Bordes dobles
    try:
        panel.attron(curses.A_BOLD)
        panel.box(ord('║'), ord('═'))
        panel.attroff(curses.A_BOLD)
    except Exception:
        panel.box()
    header = "📊 POSICIONES" + (f" [{len(positions_list)}]" if positions_list else "")
    safe_addstr(panel, 0, 2, header, curses.color_pair(3) | curses.A_BOLD)
    columns = [
        ("Epic", 8),
        ("Dir", 6),
        ("Size", 8),
        ("Precio", 10),
        ("UPL $", 10),
        ("UPL %", 8),
        ("Max💰", 10),
        ("Deuda", 8),
        ("Tiempo", 8),
        ("Estado", 10)
    ]
    row = 2
    col = 2
    header_items = [f"{title:<{width}}" for title, width in columns]
    header_line = " │ ".join(header_items)
    safe_addstr(panel, row, col, header_line, curses.color_pair(3) | curses.A_BOLD)
    row += 1
    sep_line = "═" * len(header_line)
    safe_addstr(panel, row, col, sep_line, curses.color_pair(3))
    row += 1
    for pos in positions_list:
        market = pos.get("market", {})
        position = pos.get("position", {})
        epic = str(market.get("epic", "N/A"))[:8]
        direction = str(position.get("direction", "N/A"))
        direction_icon = "🟢BUY" if direction == "BUY" else ("🔴SELL" if direction == "SELL" else direction)
        size = str(position.get("size", ""))
        price = f"{position.get('level', 0):.2f}" if position.get('level') else "N/A"
        try:
            upl_val = float(position.get("upl", 0))
        except Exception:
            upl_val = 0.0
        upl_str = f"{upl_val:8.4f}"
        try:
            upl_pct = float(position.get("upl_pct", 0))
        except Exception:
            upl_pct = 0.0
        upl_pct_str = f"{upl_pct:6.1f}%"
        max_profit = pos.get("max_profit", 0.0)
        max_profit_str = f"${max_profit:.2f}"
        created_str = position.get("createdDateUTC") or position.get("createdDate")
        open_time = calc_open_time(created_str) if created_str else "N/A"
        _hours = get_hours_open(created_str) if created_str else 0.0
        _size = float(position.get("size", 0))
        _debt = _hours * DEBT_RATE_PER_HOUR if _size > 0 else 0.0
        debt_str = f"${_debt:.4f}"
        estado = pos.get("estado", "")
        # Colores
        dir_color = curses.color_pair(2) if direction == "BUY" else (curses.color_pair(1) if direction == "SELL" else curses.A_NORMAL)
        upl_color = curses.color_pair(2) if upl_val > 0 else (curses.color_pair(1) if upl_val < 0 else curses.A_NORMAL)
        items = [
            f"{epic:<8}",
            f"{direction_icon:<6}",
            f"{size:<8}",
            f"{price:<10}",
            f"{upl_str:<10}",
            f"{upl_pct_str:<8}",
            f"{max_profit_str:<10}",
            f"{debt_str:<8}",
            f"{open_time:<8}",
            f"{estado:<10}"
        ]
        # Render con color
        col_offset = col
        for idx, val in enumerate(items):
            attr = dir_color if idx == 1 else (upl_color if idx == 4 else curses.A_NORMAL)
            safe_addstr(panel, row, col_offset, val, attr)
            col_offset += len(val) + 3  # 3 por ' │ '
        row += 1
    panel.refresh()

def get_hours_open(created_str):
    try:
        if created_str.endswith("Z"):
            created_str = created_str.replace("Z", "+00:00")
        dt_created = datetime.fromisoformat(created_str)
        if dt_created.tzinfo is None:
            dt_created = dt_created.replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        delta = now_utc - dt_created
        return delta.total_seconds() / 3600.0
    except Exception:
        return 0.0

def draw_decisions_table(panel, positions_list, width, mode):
    needed_height = 3 + len(positions_list) + 1
    try:
        panel.resize(needed_height, width)
    except Exception:
        pass
    panel.erase()
    panel.box()
    header = "🎯 ANÁLISIS DE DECISIONES - EVALUADOR AUTOMÁTICO"
    safe_addstr(panel, 0, 2, header, curses.A_BOLD)
    header_line = f"{'Deal':<8} │ {'UPL':<10} │ {'Max💰':<10} │ {'Piso🔒':<10} │ {'Decisión':<{width-44}}"
    safe_addstr(panel, 1, 2, header_line, curses.A_BOLD)
    sep = "═" * (width - 4)
    safe_addstr(panel, 2, 2, sep, curses.A_DIM)
    row = 3
    for pos in positions_list:
        full_deal_id = pos.get("position", {}).get("dealId", "N/A")
        deal_id_trunc = full_deal_id[-4:] if full_deal_id != "N/A" else "N/A"
        upl = pos.get("position", {}).get("upl", 0.0)
        max_profit = pos.get("max_profit", 0.0)
        piso = pos.get("locked_floor_usd", "---")
        mensaje = pos.get("reason", "")
        line = f"{deal_id_trunc:<8} │ ${upl:<9.4f} │ ${max_profit:<9.2f} │ {piso!s:<10} │ {mensaje:<{width-44}}"
        safe_addstr(panel, row, 2, line)
        row += 1
    panel.refresh()

def extract_closure_snapshot(features):
    """Extrae exit_price y close_indicators desde features para cierres."""
    exit_price = None
    try:
        exit_price = float(features.get('Close')) if isinstance(features, dict) and features.get('Close') is not None else None
    except Exception:
        exit_price = None
    close_inds = None
    try:
        if isinstance(features, dict):
            keys = ['Close', 'RSI', 'MACD', 'ATR', 'VolumeChange', 'EMA_3', 'EMA_9', 'ADX']
            close_inds = {k: features.get(k) for k in keys if k in features}
    except Exception:
        close_inds = None
    return exit_price, close_inds


# ═══════════════════════════════════════════════════════════
# 🎯 SISTEMA DE TRAILING STOP POR ZONAS
# ═══════════════════════════════════════════════════════════

def get_trend_strength_from_features(features, historical_data=None):
    """
    Extrae métricas de fuerza de tendencia desde features/historical_data.

    Returns:
        dict: {
            'ADX': float,
            'Market_Regime': str,
            'RSI': float,
            'MACD': float,
            'EMA_20': float,
            'EMA_50': float,
            'OBV_Trend': str
        }
    """
    trend_data = {}

    # Intentar desde features primero
    if isinstance(features, dict):
        trend_data['RSI'] = features.get('RSI', 50)
        trend_data['MACD'] = features.get('MACD', 0)
        trend_data['ADX'] = features.get('ADX', 20)
        trend_data['Market_Regime'] = features.get('Market_Regime', 'UNKNOWN')

    # Si tenemos historical_data, usar última vela HTF para datos más robustos
    if historical_data is not None:
        try:
            import pandas as pd
            if isinstance(historical_data, pd.DataFrame) and not historical_data.empty:
                latest_htf = historical_data.iloc[-1]
                trend_data['ADX'] = latest_htf.get('ADX', trend_data.get('ADX', 20))
                trend_data['Market_Regime'] = latest_htf.get('Market_Regime', trend_data.get('Market_Regime', 'UNKNOWN'))
                trend_data['RSI'] = latest_htf.get('RSI', trend_data.get('RSI', 50))
                trend_data['MACD'] = latest_htf.get('MACD', trend_data.get('MACD', 0))
                trend_data['EMA_20'] = latest_htf.get('EMA_20', 0)
                trend_data['EMA_50'] = latest_htf.get('EMA_50', 0)
                trend_data['OBV_Trend'] = latest_htf.get('OBV_Trend', 'NEUTRAL')
        except Exception:
            pass

    return trend_data


def is_trend_strong(trend_data, direction='BUY'):
    """
    Evalúa si la tendencia es FUERTE (Zona 2: 10-20% ganancia).

    Criterios:
    - ADX > 25 (trending confirmado)
    - Market_Regime != CHOPPY
    - RSI saludable (30-70)
    - MACD favorable
    """
    if not trend_data:
        return False

    adx = trend_data.get('ADX', 0)
    regime = trend_data.get('Market_Regime', 'UNKNOWN')
    rsi = trend_data.get('RSI', 50)
    macd = trend_data.get('MACD', 0)

    # ADX debe indicar trending
    if adx < 25:
        return False

    # No debe ser choppy
    if regime == 'CHOPPY':
        return False

    # RSI check direction-aware:
    # - Para BUY: RSI < 30 (rebote posible) o RSI > 70 (sobrecompra) = tendencia poco fiable
    # - Para SELL: RSI < 30 = caída CONTINUANDO (sobreventa en downtrend = fuerza bajista)
    #              RSI > 70 = sobrecompra extrema durante SELL = sí preocupa
    if direction == 'BUY':
        if rsi < 30 or rsi > 70:
            return False
    else:  # SELL
        if rsi > 70:  # Sobrecompra extrema en SELL sí puede indicar reversión
            return False
        # RSI < 30 para SELL = continuación de la caída, NO bloquear

    # MACD alineado con dirección
    # Para BUY: cualquier MACD negativo es señal en contra
    # Para SELL: MACD=1 o 2 es ruido de lag al inicio de una caída → usar umbral > 5
    if direction == 'BUY' and macd < 0:
        return False
    if direction == 'SELL' and macd > 5:  # umbral > 5 evita falsos positivos por lag de MACD
        return False

    return True


def is_trend_very_strong(trend_data, direction='BUY'):
    """
    Evalúa si la tendencia es MUY FUERTE (Zona 3: 20%+ ganancia).

    Criterios más estrictos:
    - ADX > 30 (trending MUY fuerte)
    - Market_Regime == TRENDING
    - EMAs alineadas (20 > 50 para BUY)
    - OBV positivo
    - RSI entre 40-65 (momentum sostenible)
    """
    if not trend_data:
        return False

    adx = trend_data.get('ADX', 0)
    regime = trend_data.get('Market_Regime', 'UNKNOWN')
    rsi = trend_data.get('RSI', 50)
    ema_20 = trend_data.get('EMA_20', 0)
    ema_50 = trend_data.get('EMA_50', 0)
    obv_trend = trend_data.get('OBV_Trend', 'NEUTRAL')

    # ADX muy fuerte
    if adx < 30:
        return False

    # Debe ser TRENDING explícitamente
    if regime != 'TRENDING':
        return False

    # EMAs alineadas según dirección
    if direction == 'BUY' and ema_20 > 0 and ema_50 > 0 and ema_20 <= ema_50:
        return False
    if direction == 'SELL' and ema_20 > 0 and ema_50 > 0 and ema_20 >= ema_50:
        return False

    # OBV favorable (si está disponible)
    if obv_trend != 'NEUTRAL':
        if direction == 'BUY' and obv_trend in ['NEGATIVE', 'FALLING']:
            return False
        if direction == 'SELL' and obv_trend in ['POSITIVE', 'RISING']:
            return False

    # RSI en zona sostenible - direction-aware:
    # - Para BUY: RSI fuera de 40-65 = momentum en duda
    # - Para SELL: RSI bajo (<40) en caída fuerte = continuación, no cerrar
    #              RSI > 65 durante SELL = posible reversión alcista
    if direction == 'BUY':
        if rsi < 40 or rsi > 65:
            return False
    else:  # SELL
        if rsi > 65:
            return False
        # RSI < 40 para SELL en TRENDING = caída sostenida, NO bloquear

    return True


def smart_trailing_by_zone(position, trend_data, profittracker, features, debug_callback=None):
    """
    Sistema de trailing stop dinámico por zonas de ganancia.

    Returns:
        dict o None: Closure action si debe cerrar, None si debe mantener
    """
    full_deal_id = position.get("position", {}).get("dealId", "N/A")
    max_profit_pct = profittracker.get(full_deal_id, {}).get("max_profit_pct", 0.0)
    direction = position.get("position", {}).get("direction", "BUY")

    try:
        upl = float(position.get("position", {}).get("upl", 0))
        upl_pct_raw = position.get("position", {}).get("upl_pct", None)
        if upl_pct_raw is not None:
            upl_pct = float(upl_pct_raw)
            if abs(upl_pct) < 1:
                upl_pct = upl_pct * 100.0
        else:
            upl_pct = upl * 100.0 if abs(upl) < 5 else upl
    except Exception:
        upl_pct = 0.0

    # ═══════════════════════════════════════════════════════════
    # ZONA 1: Ganancia Inicial (0-10%) - SCALPING CON AIRE
    # Objetivo: Proteger capital pero dar espacio para pullbacks normales
    # ═══════════════════════════════════════════════════════════
    if max_profit_pct < 10:
        # Trailing stop: permitir 15% retroceso SOLO si la tendencia se debilitó.
        # Si la tendencia sigue fuerte, aguantar aunque haya un mini-rebote.
        # Umbral mínimo 5% (antes 3%) para no cerrar por ruido en ganancias pequeñas.
        if max_profit_pct > 5 and upl_pct < max_profit_pct * 0.85:  # Retrocedió 15%
            if is_trend_strong(trend_data, direction):
                # Tendencia sigue fuerte: el retroceso es ruido de mercado, no cierre
                position["reason"] += f"🟢 ZONA 1: Retroceso {max_profit_pct:.2f}%→{upl_pct:.2f}% pero tendencia FUERTE (ADX={trend_data.get('ADX',0):.1f}). HOLD."
                if debug_callback:
                    debug_callback(f"[ZONA 1] Retroceso ignorado — tendencia fuerte: {full_deal_id[-4:]}")
                return None
            # Tendencia débil + retroceso → cerrar
            reason = f"🔒 ZONA 1: Retroceso desde {max_profit_pct:.2f}% a {upl_pct:.2f}% con tendencia débil"
            position["reason"] += reason
            if debug_callback:
                debug_callback(f"[ZONA 1] Cierre por retroceso + tendencia débil: {full_deal_id[-4:]}")

            exit_price, close_inds = extract_closure_snapshot(features)
            return {
                "action": "Close",
                "dealId": full_deal_id,
                "size": position.get("size"),
                "reason": reason,
                "direction": direction,
                "epic": position.get("market", {}).get("epic", "N/A"),
                "exit_price": exit_price,
                "close_indicators": close_inds,
                "max_profit_pct": max_profit_pct
            }

        position["reason"] += f"🟢 ZONA 1: Ganancia {max_profit_pct:.2f}% < 10%. Mantener."
        return None  # No cerrar

    # ═══════════════════════════════════════════════════════════
    # ZONA 2: Ganancia Buena (10-20%) - SWING MODERADO
    # Objetivo: Dejar respirar si tendencia continúa
    # ═══════════════════════════════════════════════════════════
    elif 10 <= max_profit_pct < 20:
        # Evaluar fuerza de tendencia
        if is_trend_strong(trend_data, direction):
            # Tendencia fuerte → MANTENER sin cerrar
            position["reason"] += f"🟡 ZONA 2: Ganancia {max_profit_pct:.2f}%, tendencia FUERTE (ADX={trend_data.get('ADX', 0):.1f}). HOLD 📈"
            if debug_callback:
                debug_callback(f"[ZONA 2] Mantener por tendencia fuerte: {full_deal_id[-4:]}")
            return None
        else:
            # Tendencia débil → Trailing stop moderado (10% retroceso permitido)
            if upl_pct < max_profit_pct * 0.90:  # Retrocedió 10%
                reason = f"🟡 ZONA 2: Retroceso desde {max_profit_pct:.2f}% a {upl_pct:.2f}% con tendencia débil"
                position["reason"] += reason
                if debug_callback:
                    debug_callback(f"[ZONA 2] Cierre por retroceso + tendencia débil: {full_deal_id[-4:]}")

                exit_price, close_inds = extract_closure_snapshot(features)
                return {
                    "action": "Close",
                    "dealId": full_deal_id,
                    "size": position.get("size"),
                    "reason": reason,
                    "direction": direction,
                    "epic": position.get("market", {}).get("epic", "N/A"),
                    "exit_price": exit_price,
                    "close_indicators": close_inds,
                    "max_profit_pct": max_profit_pct
                }

            position["reason"] += f"🟡 ZONA 2: Ganancia {max_profit_pct:.2f}%, tendencia débil pero sin retroceso crítico. HOLD ⚠️"
            return None

    # ═══════════════════════════════════════════════════════════
    # ZONA 3: TREMENDA POSICIÓN (20%+) 🔥 - SWING CONSERVADOR
    # Objetivo: "Papá, síguele pa' ve" pero con protección
    # ═══════════════════════════════════════════════════════════
    else:  # max_profit_pct >= 20
        # Evaluar fuerza MUY fuerte
        if is_trend_very_strong(trend_data, direction):
            # Tendencia MUY fuerte → ¡DEJAR CORRER!
            position["reason"] += f"🔥 ZONA 3: Ganancia {max_profit_pct:.2f}%, tendencia MUY FUERTE (ADX={trend_data.get('ADX', 0):.1f}, {trend_data.get('Market_Regime', 'N/A')}). ¡SÍGUELE! 🚀"
            if debug_callback:
                debug_callback(f"[ZONA 3] ¡TREMENDA POSICIÓN CORRIENDO!: {full_deal_id[-4:]}")
            return None  # Dejar correr
        else:
            # Tendencia se debilitó → Trailing stop generoso (15% retroceso permitido)
            if upl_pct < max_profit_pct * 0.85:  # Retrocedió 15%
                reason = f"🔥 ZONA 3: Retroceso significativo desde {max_profit_pct:.2f}% a {upl_pct:.2f}%. Tendencia se debilitó."
                position["reason"] += reason
                if debug_callback:
                    debug_callback(f"[ZONA 3] Cierre por debilitamiento de tendencia: {full_deal_id[-4:]}")

                exit_price, close_inds = extract_closure_snapshot(features)
                return {
                    "action": "Close",
                    "dealId": full_deal_id,
                    "size": position.get("size"),
                    "reason": reason,
                    "direction": direction,
                    "epic": position.get("market", {}).get("epic", "N/A"),
                    "exit_price": exit_price,
                    "close_indicators": close_inds,
                    "max_profit_pct": max_profit_pct
                }

            position["reason"] += f"🔥 ZONA 3: Ganancia {max_profit_pct:.2f}%, tendencia debilitada pero sin retroceso >20%. HOLD ⚠️"
            return None


def evaluate_positions(positions, features, profittracker, debug_callback=None, historical_data=None):
    to_close = []
    now_time = datetime.now(timezone.utc)
    # Umbrales en porcentaje
    min_threshold_pct = 0.3  # 0.3%
    closure_pct = 0.90
    base_profit_pct = 10.0  # Umbral base: 10%

    # 🌐 DETECCIÓN DE CIERRES DESDE WEB
    # Cargar posiciones vistas en el ciclo anterior
    try:
        with open(LAST_SEEN_POSITIONS_FILE, 'r') as f:
            last_seen = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        last_seen = {}

    # Crear set de dealIds actuales
    current_deal_ids = set()
    for pos in positions:
        deal_id = pos.get("position", {}).get("dealId", "N/A")
        if deal_id != "N/A":
            current_deal_ids.add(deal_id)

    # 🕳️ LIMBO: posiciones que desaparecieron 1 ciclo pero no confirmadas aún
    # Cargamos el limbo del ciclo anterior
    try:
        with open(DISAPPEARED_LIMBO_FILE, 'r') as _f:
            disappeared_limbo = json.load(_f)
    except (FileNotFoundError, json.JSONDecodeError):
        disappeared_limbo = {}

    new_limbo = {}

    # Detectar posiciones que desaparecieron (cerradas desde web)
    for old_deal_id, old_data in last_seen.items():
        if old_deal_id not in current_deal_ids:
            # Guardia anti-fantasma: ignorar si nunca tuvo horas reales de seguimiento
            hours_tracked = old_data.get("hours_open")
            try:
                hours_tracked = float(hours_tracked)
            except (TypeError, ValueError):
                hours_tracked = None
            if hours_tracked is None or hours_tracked < 0.05:  # < 3 minutos → ignorar
                continue

            if old_deal_id in disappeared_limbo:
                # Segundo ciclo consecutivo sin ver la posición → cierre confirmado
                ui = globals().get('ui', None)
                if ui:
                    ui.add_log(f"[WEB] ✅ Cierre confirmado (2 ciclos) para {old_deal_id[-8:]}")
                log_web_closed_position(old_data)
                # No pasar al new_limbo: ya fue registrado
            else:
                # Primer ciclo que desaparece → poner en limbo, no registrar todavía
                new_limbo[old_deal_id] = old_data
                ui = globals().get('ui', None)
                if ui:
                    ui.add_log(f"[WEB] ⏳ Posición {old_deal_id[-8:]} desapareció (ciclo 1/2), esperando confirmación...")

    # Guardar nuevo limbo
    try:
        with open(DISAPPEARED_LIMBO_FILE, 'w') as _f:
            json.dump(new_limbo, _f)
    except Exception:
        pass

    # Actualizar tracking con posiciones actuales
    new_tracking = {}

    entry_snapshots = {}
    entry_snapshots_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entry_snapshots.json")
    try:
        if os.path.exists(entry_snapshots_path):
            with open(entry_snapshots_path, 'r') as f:
                entry_snapshots = json.load(f)
    except Exception:
        pass

    # Obtener el momentum/score actual (de features o de un fetch externo si aplica)
    momentum_score = None
    if isinstance(features, dict):
        # Puede venir como 'score' o 'momentum_score'
        momentum_score = features.get('momentum_score')
        if momentum_score is None:
            momentum_score = features.get('score')

    for position in positions:
        # Obtener el dealId completo (sin truncar) para usar en la solicitud de cierre
        full_deal_id = position.get("position", {}).get("dealId", "N/A")
        # Para visualización se puede truncar, pero para el cierre se usará el full_deal_id
        deal_id_trunc = full_deal_id[-4:] if full_deal_id != "N/A" else "N/A"

        # 🌐 Guardar estado actual de esta posición para tracking
        if full_deal_id != "N/A":
            snap = entry_snapshots.get(full_deal_id, {}) if isinstance(entry_snapshots, dict) else {}
            strategy_score = _get_strategy_score(
                snap.get("strategy_score"),
                snap.get("confianza_score"),
                snap.get("strategy_confidence"),
                momentum_score,
            )
            position["strategy_score"] = strategy_score
            try:
                new_tracking[full_deal_id] = {
                    "dealId": full_deal_id,
                    "epic": position.get("market", {}).get("epic", "N/A"),
                    "direction": position.get("position", {}).get("direction", "N/A"),
                    "size": position.get("position", {}).get("size", "N/A"),
                    "entry_price": position.get("position", {}).get("level", "N/A"),
                    "last_upl": position.get("position", {}).get("upl", 0),
                    "last_upl_pct": None,  # Se calculará más abajo
                    "max_profit_pct": profittracker.get(full_deal_id, {}).get("max_profit_pct", 0),
                    "hours_open": None,  # Se calculará más abajo
                    "strategy_score": strategy_score,
                    "last_seen_time": datetime.now(timezone.utc).isoformat(),
                    "last_indicators": {
                        "Close": features.get("Close") if isinstance(features, dict) else None,
                        "RSI": features.get("RSI") if isinstance(features, dict) else None,
                        "MACD": features.get("MACD") if isinstance(features, dict) else None,
                        "ATR": features.get("ATR") if isinstance(features, dict) else None,
                        "VolumeChange": features.get("VolumeChange") if isinstance(features, dict) else None
                    }
                }
            except Exception:
                pass
        created_str = position.get("position", {}).get("createdDateUTC") or position.get("position", {}).get("createdDate")
        hours_open = None
        if created_str:
            try:
                if created_str.endswith("Z"):
                    created_str = created_str.replace("Z", "+00:00")
                dt_created = datetime.fromisoformat(created_str)
                if dt_created.tzinfo is None:
                    dt_created = dt_created.replace(tzinfo=timezone.utc)
                delta = now_time - dt_created
                hours_open = delta.total_seconds() / 3600
            except Exception:
                hours_open = None
        position["hours_open"] = hours_open if hours_open is not None else "N/A"
        position["reason"] = ""

        # Actualizar tracking con horas abiertas calculadas
        if full_deal_id in new_tracking:
            new_tracking[full_deal_id]["hours_open"] = hours_open if hours_open is not None else "N/A"

        # Obtener UPL en valor y en porcentaje de forma robusta
        try:
            upl = float(position.get("position", {}).get("upl", 0))
        except Exception:
            upl = 0.0

        # Preferir campo 'upl_pct' si viene del API; normalizar a porcentaje (ej. 7.5 => 7.5, 0.075 => 7.5)
        upl_pct_raw = position.get("position", {}).get("upl_pct", None)
        upl_pct = None
        try:
            if upl_pct_raw is not None:
                upl_pct = float(upl_pct_raw)
                if abs(upl_pct) < 1:
                    upl_pct = upl_pct * 100.0
            else:
                # Inferir porcentaje desde 'upl' si parece un ratio pequeño
                if abs(upl) < 5:
                    upl_pct = upl * 100.0
                else:
                    upl_pct = upl
        except Exception:
            upl_pct = upl * 100.0

        # Actualizar tracking con upl_pct calculado
        if full_deal_id in new_tracking:
            new_tracking[full_deal_id]["last_upl_pct"] = round(upl_pct, 2)

        if debug_callback:
            debug_callback(f"DEBUG: Evaluando posición {deal_id_trunc} -> upl_val: {upl} | upl_pct: {upl_pct:.4f}%")

        # 🔔 DETECTAR CAMBIO A POSITIVO Y REPRODUCIR SONIDO
        if full_deal_id not in profittracker:
            profittracker[full_deal_id] = {"max_profit_pct": 0.0, "was_positive": False}

        was_positive_before = profittracker[full_deal_id].get("was_positive", False)

        # ═══════════════════════════════════════════════════════════
        # ⏰ ZONA 0: RESCATE GRACEFUL — 50h+ en zona breakeven
        # Si la posición lleva ≥50h, nunca escapó del 1% de ganancia,
        # el UPL sigue en el rango [-$0.01, +$0.05] y el mercado está
        # débil → evaluar rescate.
        #
        # 💸 SISTEMA DE DEUDA: la posición acumula deuda por overnight fee.
        # En vez de cerrar en $0, espera a que UPL cubra la deuda acumulada.
        # Nunca fuerza cierre: si la deuda no se cubre, la posición sigue abierta.
        # ═══════════════════════════════════════════════════════════
        _GRACEFUL_HOURS = 50.0
        _GRACEFUL_UPL_MIN = -0.01   # pérdida máxima tolerable en $ para activar
        _GRACEFUL_UPL_MAX = 0.05    # ganancia máxima en $  (nunca "escapó" breakeven)
        _GRACEFUL_MAX_PROFIT_PCT = 1.0  # la posición jamás alcanzó 1% de ganancia
        _max_pct_so_far = profittracker.get(full_deal_id, {}).get("max_profit_pct", 0.0)

        # 💰 Calcular deuda acumulada por overnight fee
        _pos_size = 0.0
        try:
            _pos_size = float(position.get("position", {}).get("size", 0))
        except (TypeError, ValueError):
            pass
        _accumulated_debt = 0.0
        if isinstance(hours_open, (int, float)) and _pos_size > 0:
            _accumulated_debt = hours_open * DEBT_RATE_PER_HOUR

        if (
            isinstance(hours_open, (int, float)) and hours_open >= _GRACEFUL_HOURS
            and _GRACEFUL_UPL_MIN <= upl <= _GRACEFUL_UPL_MAX
            and _max_pct_so_far < _GRACEFUL_MAX_PROFIT_PCT
        ):
            _direction = position.get("position", {}).get("direction", "BUY")
            _td_early = get_trend_strength_from_features(features, historical_data)

            # 🔒 Candado: si Bollinger squeeze activo, NO cerrar — breakout inminente
            _squeeze_active = False
            try:
                mctx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_context.json")
                if os.path.exists(mctx_path):
                    with open(mctx_path, "r") as _mf:
                        mctx = json.load(_mf)
                    _squeeze_active = mctx.get("squeeze_pct", 100) < 4.0
            except Exception:
                pass

            if _squeeze_active:
                position["reason"] += "⏰ ZONA 0 bloqueada: Bollinger squeeze activo. "
                if debug_callback:
                    debug_callback(
                        f"🔒 [ZONA 0] Squeeze activo — rescate bloqueado: {deal_id_trunc} "
                        f"({hours_open:.1f}h, UPL=${upl:.2f})"
                    )
                continue

            _strategy_score = _get_strategy_score(
                position.get("strategy_score"),
                features.get("confianza_score") if isinstance(features, dict) else None,
                features.get("strategy_score") if isinstance(features, dict) else None,
                features.get("momentum_score") if isinstance(features, dict) else None,
            )
            _strategy_score_label = f"{_strategy_score:.1f}/8" if _strategy_score is not None else "N/A"
            if _strategy_score is not None and _strategy_score >= STRATEGY_CLOSE_SCORE_MIN:
                position["reason"] += f"⏸️ ZONA 0 retenida: score estrategia {_strategy_score_label} fuerte. "
                if debug_callback:
                    debug_callback(
                        f"⏸️ [ZONA 0] HOLD por score fuerte: {deal_id_trunc} "
                        f"({hours_open:.1f}h, score={_strategy_score_label})"
                    )
                continue

            if not is_trend_strong(_td_early, _direction):
                # 💸 Verificar deuda: solo cerrar si UPL cubre los fees acumulados
                if upl >= _accumulated_debt:
                    net_upl = upl - _accumulated_debt
                    net_upl_pct = net_upl / abs(position.get("position", {}).get("size", 1)) / 10  # aprox
                    reason = (
                        f"⏰ ZONA 0 RESCATE: {hours_open:.1f}h · "
                        f"UPL ${upl:.2f} · deuda ${_accumulated_debt:.4f} · "
                        f"score {_strategy_score_label} · "
                        f"neto ${net_upl:.4f} · "
                        f"max_profit {_max_pct_so_far:.2f}% · "
                        f"tendencia débil → cierre graceful"
                    )
                    position["reason"] += reason
                    exit_price, close_inds = extract_closure_snapshot(features)
                    to_close.append({
                        "action": "Close",
                        "dealId": full_deal_id,
                        "size": position.get("size"),
                        "reason": reason,
                        "direction": _direction,
                        "epic": position.get("market", {}).get("epic", "N/A"),
                        "exit_price": exit_price,
                        "close_indicators": close_inds,
                        "max_profit_pct": _max_pct_so_far,
                        "accumulated_debt": _accumulated_debt,
                        "strategy_score": _strategy_score,
                        "net_upl": net_upl,
                        "net_upl_pct": net_upl_pct,
                        "last_upl": upl,
                        "last_upl_pct": upl_pct
                    })
                    if debug_callback:
                        debug_callback(
                            f"⏰ [ZONA 0] Rescate graceful: {deal_id_trunc} "
                            f"({hours_open:.1f}h, UPL=${upl:.2f}, deuda=${_accumulated_debt:.4f})"
                        )
                else:
                    # Deuda no cubierta → esperar
                    _deficit = _accumulated_debt - upl
                    position["reason"] += (
                        f"⏰ ZONA 0 diferida: {hours_open:.1f}h · "
                        f"UPL ${upl:.2f} < deuda ${_accumulated_debt:.4f} "
                        f"· score {_strategy_score_label} "
                        f"(faltan ${_deficit:.4f}) · esperando cubrir fees..."
                    )
                    if debug_callback:
                        debug_callback(
                            f"⏰ [ZONA 0] Diferida por deuda: {deal_id_trunc} "
                            f"({hours_open:.1f}h, UPL=${upl:.2f}, deuda=${_accumulated_debt:.4f}, score={_strategy_score_label}, "
                            f"faltan=${_deficit:.4f})"
                        )
                    continue

        if upl_pct > 0 and not was_positive_before:
            # 🎵 ¡Cambió de negativo a positivo!
            play_sound('positive_position', debug_callback)
            profittracker[full_deal_id]["was_positive"] = True
            if debug_callback:
                debug_callback(f"🔔 Posición {deal_id_trunc} cambió a positivo: {upl_pct:.2f}%")
        elif upl_pct < 0:
            # Resetear flag para que suene de nuevo si vuelve a positivo
            profittracker[full_deal_id]["was_positive"] = False
            position["reason"] += f"UPL negativo ({upl_pct:.2f}%). Sin acción."
            continue
        prev_max_pct = profittracker[full_deal_id].get("max_profit_pct", 0.0)

        if upl_pct > prev_max_pct:
            profittracker[full_deal_id]["max_profit_pct"] = upl_pct
            position["max_profit_pct"] = upl_pct
            position["max_profit"] = upl
            position["reason"] += f"Max Profit actualizado a {upl_pct:.2f}%. "
        else:
            position["max_profit_pct"] = prev_max_pct
            position["max_profit"] = prev_max_pct / 100.0
            position["reason"] += f" Max Profit Alcanzado en {prev_max_pct:.2f}%). "


        # ═══════════════════════════════════════════════════════════
        # 💰 ZONA MICRO: Posiciones pequeñas (≤0.003 ETH)
        # Solo tiers Supervivencia (0.001) y Micro (0.002)
        # Objetivo: acumular centavos rápido cerrando a $0.01 de ganancia
        # ═══════════════════════════════════════════════════════════
        _MICRO_MAX_SIZE = 0.003   # ETH — umbral de posición micro (excluye tier Normal 0.005+)
        _MICRO_TARGET_USD = 0.01  # $0.01 de ganancia objetivo
        try:
            _pos_size = float(position.get("position", {}).get("size", 0))
        except (TypeError, ValueError):
            _pos_size = 0.0

        if 0 < _pos_size <= _MICRO_MAX_SIZE and upl >= _MICRO_TARGET_USD:
            _direction_micro = position.get("position", {}).get("direction", "BUY")
            reason = (
                f"💰 ZONA MICRO: Posición {_pos_size} ETH · "
                f"UPL ${upl:.4f} ≥ ${_MICRO_TARGET_USD} · "
                f"Cierre rápido para acumular"
            )
            position["reason"] += reason
            if debug_callback:
                debug_callback(f"💰 [MICRO] Cerrando {full_deal_id[-4:]}: {_pos_size} ETH con ${upl:.4f} ganancia")
            exit_price, close_inds = extract_closure_snapshot(features)
            to_close.append({
                "action": "Close",
                "dealId": full_deal_id,
                "size": position.get("size"),
                "reason": reason,
                "direction": _direction_micro,
                "epic": position.get("market", {}).get("epic", "N/A"),
                "exit_price": exit_price,
                "close_indicators": close_inds,
                "max_profit_pct": prev_max_pct
            })
            continue

        # ═══════════════════════════════════════════════════════════
        # 🎯 SISTEMA DE TRAILING STOP POR ZONAS
        # ═══════════════════════════════════════════════════════════

        # Obtener datos de tendencia para evaluación de zonas
        trend_data = get_trend_strength_from_features(features, historical_data)

        # Evaluar decisión por zonas
        closure_decision = smart_trailing_by_zone(position, trend_data, profittracker, features, debug_callback)

        if closure_decision is not None:
            # Sistema de zonas decidió cerrar
            # ⚡ POST se hará INMEDIATAMENTE, sonido DESPUÉS
            to_close.append(closure_decision)
            if debug_callback:
                debug_callback(f"🎯 Preparando cierre de posición {deal_id_trunc} por zonas")
            continue  # Ir a siguiente posición (no evaluar reglas adicionales)

        # Si no cerró por zonas, continuar con reglas de cierre forzado

        # ═══════════════════════════════════════════════════════════
        # REGLA DE CIERRE FORZADO: 24 horas
        # ═══════════════════════════════════════════════════════════
        if isinstance(hours_open, (int, float)) and hours_open >= 24 and upl >= 0.5:
            _strategy_score = _get_strategy_score(
                position.get("strategy_score"),
                features.get("confianza_score") if isinstance(features, dict) else None,
                features.get("strategy_score") if isinstance(features, dict) else None,
                features.get("momentum_score") if isinstance(features, dict) else None,
            )
            _strategy_score_label = f"{_strategy_score:.1f}/8" if _strategy_score is not None else "N/A"
            _accumulated_debt = _calculate_accumulated_debt(hours_open, position.get("position", {}).get("size", 0))
            if upl < _accumulated_debt:
                position["reason"] += f"Cierre forzado diferido: deuda ${_accumulated_debt:.4f} > UPL ${upl:.2f}. "
                continue
            position["reason"] += f"Cierre forzado: Abierta {hours_open:.1f}h, UPL {upl_pct:.2f}%."
            # ⚡ POST se hará INMEDIATAMENTE, sonido DESPUÉS
            # Incluir exit_price y snapshot de indicadores si están disponibles
            exit_price, close_inds = extract_closure_snapshot(features)
            to_close.append({
                "action": "Close",
                "dealId": full_deal_id,
                "size": position.get("size"),
                "reason": position["reason"],
                "direction": position.get("position", {}).get("direction", "N/A"),
                "epic": position.get("market", {}).get("epic", "N/A"),
                "exit_price": exit_price,
                "close_indicators": close_inds,
                "strategy_score": _strategy_score,
                "accumulated_debt": _accumulated_debt
            })
            if debug_callback:
                debug_callback(f"🔔 Cerrando posición {deal_id_trunc} por cierre forzado 24h")

    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "profittracker.json"), "w") as file:
            json.dump(profittracker, file, indent=4)
        if debug_callback:
            debug_callback("[INFO] profittracker.json actualizado y guardado correctamente.")
    except Exception as e:
        if debug_callback:
            debug_callback(f"[ERROR] No se pudo guardar profittracker.json: {e}")

    # 🌐 Guardar tracking actualizado de posiciones para detectar cierres desde web
    try:
        with open(LAST_SEEN_POSITIONS_FILE, 'w') as f:
            json.dump(new_tracking, f, indent=2)
    except Exception as e:
        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"[WARNING] No se pudo guardar tracking de posiciones: {e}")

    # 📊 Enriquecer cada cierre con datos completos de tracking para el dashboard
    for closure in to_close:
        deal_id = closure.get('dealId')
        if deal_id and deal_id in new_tracking:
            tracking = new_tracking[deal_id]
            closure.setdefault('entry_price', tracking.get('entry_price'))
            closure.setdefault('last_upl', tracking.get('last_upl'))
            closure.setdefault('last_upl_pct', tracking.get('last_upl_pct'))
            closure.setdefault('hours_open', tracking.get('hours_open'))
            closure.setdefault('last_indicators', tracking.get('last_indicators'))
            closure.setdefault('last_seen_time', tracking.get('last_seen_time'))
            closure.setdefault('size', tracking.get('size'))
            closure.setdefault('strategy_score', tracking.get('strategy_score'))
        # Agregar datos de apertura desde entry_snapshots
        if deal_id and deal_id in entry_snapshots:
            snap = entry_snapshots[deal_id]
            closure.setdefault('open_indicators', snap.get('indicators', {}))
            closure.setdefault('open_reason', snap.get('reason', ''))
            closure.setdefault('open_datetime', snap.get('open_datetime', ''))
            closure.setdefault('strategy_score', snap.get('strategy_score', closure.get('strategy_score')))
            if not closure.get('entry_price') and snap.get('open_price'):
                closure['entry_price'] = snap.get('open_price')

    return to_close


def execute_closures(closures, capital_ops=None, default_close_snapshot=None, debug_callback=None, current_features=None):
    """
    Ejecuta una lista de cierres (closures) provistas en el formato generado por evaluate_positions().

    Cada elemento de `closures` es un dict con al menos:
      - 'dealId'
      - 'epic'
      - 'direction'
      - 'size'
      - 'reason'
      - opcionalmente: 'exit_price', 'close_indicators'

    Si se proporciona `capital_ops` (una instancia de CapitalOP), se llamará a
    `capital_ops.close_position(dealId)` para cerrar y se intentará extraer
    el precio efectivo de cierre desde la respuesta de la API. Si no se puede
    obtener, se usa `exit_price` del elemento o se consulta `capital_ops.get_last_price()`.

    Finalmente, se invoca `log_closed_position(details)` con los campos
    completos incluyendo `exit_price` y `close_indicators`.
    """
    results = []
    # Crear instancia local si no se proporcionó (intentará autenticarse)
    created_local = False
    if capital_ops is None:
        try:
            capital_ops = CapitalOP()
            created_local = True
        except Exception:
            capital_ops = None

    for item in closures:
        deal_id = item.get('dealId')
        epic = item.get('epic')
        direction = item.get('direction')
        size = item.get('size')
        reason = item.get('reason', '')

        # Preferir exit_price provisto en el item
        exit_price = item.get('exit_price', None)
        close_inds = item.get('close_indicators', None) or default_close_snapshot

        api_resp = None
        api_error = None
        if capital_ops is not None and deal_id:
            try:
                api_resp = capital_ops.close_position(deal_id)
            except Exception as e:
                api_error = str(e)

        # Intentar extraer precio desde la respuesta API si existe
        if exit_price is None and api_resp:
            try:
                # Intentar campos comunes que podrían contener el precio
                for key in ('exitPrice', 'exit_level', 'closePrice', 'level', 'price', 'deal_price'):
                    if isinstance(api_resp, dict) and key in api_resp:
                        exit_price = api_resp.get(key)
                        break
                # Si la respuesta tiene nested structures, buscar 'deal' o 'position'
                if exit_price is None and isinstance(api_resp, dict):
                    if 'deal' in api_resp and isinstance(api_resp['deal'], dict):
                        for k in ('level', 'price', 'closePrice'):
                            if k in api_resp['deal']:
                                exit_price = api_resp['deal'].get(k)
                                break
            except Exception:
                exit_price = None

        # Si aún no tenemos exit_price y tenemos capital_ops, pedir precio tick
        if exit_price is None and capital_ops is not None:
            try:
                exit_price = capital_ops.get_last_price(epic or 'ETHUSD')
            except Exception:
                exit_price = None

        # Construir details para logging/export
        _pnl = item.get('net_upl') if item.get('net_upl') is not None else item.get('pnl', 0)
        _pnl_pct = item.get('net_upl_pct') if item.get('net_upl_pct') is not None else item.get('pnl_pct', 0)
        details = {
            'dealId': deal_id or 'N/A',
            'epic': epic or 'N/A',
            'direction': direction or 'N/A',
            'size': size or 0,
            'reason': reason or 'Closed by executor',
            'exit_price': exit_price,
            'close_indicators': close_inds,
            'pnl': _pnl,
            'pnl_pct': _pnl_pct,
            'duration': item.get('duration', 0),
            'entry_price': item.get('entry_price', 0),
            'accumulated_debt': item.get('accumulated_debt', 0),
            'strategy_score': item.get('strategy_score')
        }

        # Registrar en logs y export para IA
        try:
            log_closed_position(details)
        except Exception as e:
            if debug_callback:
                debug_callback(f"[ERROR] log_closed_position falló para {deal_id}: {e}")

        # 📊 Registrar en web_closed_positions.json para el dashboard
        try:
            web_closed_json = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_closed_positions.json")
            try:
                with open(web_closed_json, 'r') as f:
                    web_closures = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                web_closures = []

            # Anti-duplicados: verificar si este dealId ya existe
            existing_index = None
            for idx, existing in enumerate(web_closures):
                if existing.get('dealId') == deal_id:
                    existing_index = idx
                    break

            # Construir registro completo con todos los detalles para el dashboard
            # Combinar close_indicators en last_indicators (lo que lee el dashboard)
            last_indicators = item.get('last_indicators', {}) or {}
            if close_inds and isinstance(close_inds, dict):
                last_indicators.update(close_inds)

            _upl = item.get('net_upl') if item.get('net_upl') is not None else item.get('last_upl', details.get('pnl', 0))
            _upl_pct = item.get('net_upl_pct') if item.get('net_upl_pct') is not None else item.get('last_upl_pct')
            dashboard_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "dealId": deal_id or 'N/A',
                "epic": epic or 'ETHUSD',
                "direction": direction or 'N/A',
                "size": size or 0,
                "entry_price": item.get('entry_price') or details.get('entry_price'),
                "last_upl": _upl,
                "last_upl_pct": _upl_pct,
                "max_profit_pct": item.get('max_profit_pct', 0),
                "hours_open": item.get('hours_open'),
                "last_seen_time": item.get('last_seen_time', datetime.now(timezone.utc).isoformat()),
                "last_indicators": last_indicators,
                "open_indicators": item.get('open_indicators', {}),
                "open_reason": item.get('open_reason', ''),
                "open_datetime": item.get('open_datetime', ''),
                "exit_price": exit_price,
                "reason": reason or 'Bot closure',
                "source": "bot",
                "accumulated_debt": item.get('accumulated_debt', 0),
                "strategy_score": item.get('strategy_score')
            }

            if existing_index is not None:
                web_closures[existing_index] = dashboard_record
            else:
                web_closures.append(dashboard_record)

            with open(web_closed_json, 'w') as f:
                json.dump(web_closures, f, indent=2)

            if debug_callback:
                debug_callback(f"[DASHBOARD] ✅ Cierre registrado para dashboard: {(deal_id or '')[-8:]}")
        except Exception as e:
            if debug_callback:
                debug_callback(f"[WARNING] No se pudo registrar cierre para dashboard: {e}")

        # 🎯 DETECCIÓN DE WINNERS: Si cierre con max_profit >= 10% y tendencia continúa → permitir re-entrada rápida
        if current_features is not None:
            current_signal = current_features.get('signal', '')
            max_profit_pct = item.get('max_profit_pct', 0.0)
            check_and_activate_fast_reentry(
                deal_id=deal_id or 'N/A',
                direction=direction,
                max_profit_pct=max_profit_pct,
                current_signal=current_signal,
                debug_callback=debug_callback
            )

        # Guardar closure reason legible
        try:
            save_closure_reason(deal_id or 'N/A', reason or '', details.get('pnl', 0), direction or 'N/A', epic or 'N/A')
        except Exception:
            pass

        results.append({'dealId': deal_id, 'exit_price': exit_price, 'api_resp': api_resp, 'api_error': api_error})

    # Si creamos una instancia local, no dejamos tokens en memoria (no es crítico aquí)
    return results


def close_position(action, cst, security_token):
    """
    Cierra una posición específica usando DELETE /api/v1/positions/{dealId}.
    Se espera que 'action' contenga al menos:
      - "dealId": identificador completo de la posición.
    Los tokens (cst y security_token) se usan directamente.
    """
    deal_id = action.get("dealId")
    try:
        url = f"{BASE_URL.rstrip('/')}/api/v1/positions/{deal_id}"
        headers = {
            "Content-Type": "application/json",
            "X-CAP-API-KEY": API_KEY,
            "CST": cst,
            "X-SECURITY-TOKEN": security_token,
        }
        response = requests.delete(url, headers=headers)
        response.raise_for_status()

        # Registrar posición cerrada exitosamente
        log_closed_position(action)
        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"🔔 Posición cerrada: {action['direction']} {action['epic']} | Size: {action['size']} | Razón: {action['reason']}")
        return response.json() if response.text else {"message": "Posición cerrada sin contenido."}
    except Exception as e:
        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"[ERROR] Fallo al cerrar la posición {deal_id}: {e}")
        return None



# ------------------- Función principal con curses ------------------- #

async def curses_main_async(stdscr, cst, security_token, auto_mode=False):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_RED, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLUE)

    mode = "evaluador" if auto_mode else "monitor"
    evaluator_message = "Modo EVALUADOR: Activo (--auto)" if auto_mode else ""
    update_interval = 5
    last_update = 0
    positions_list = []
    previous_upl = {}
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "profittracker.json"), "r") as file:
            profittracker = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        profittracker = {}
    debug_messages = []
    capital_ops = CapitalOP()
    logger = UILogger(debug_messages)

    # Interceptar print para redirigir mensajes también al panel de debug
    original_print = builtins.print
    def _captured_print(*args, **kwargs):
        try:
            original_print(*args, **kwargs)
        except Exception:
            pass
        try:
            # Añadir al logger si existe
            logger.log(" ".join(str(a) for a in args))
        except Exception:
            pass
    builtins.print = _captured_print

    last_momentum_update = 0

    try:
        while True:
            max_y, max_x = stdscr.getmaxyx()
            header_lines = 3
            debug_panel_height = min(8, max_y // 8)
            momentum_panel_height = 6
            available_height = max_y - header_lines - debug_panel_height - momentum_panel_height
            pos_height = max(3, available_height // 2)
            dec_height = max(3, available_height - pos_height)

            pos_panel = stdscr.subwin(pos_height, max_x - 2, header_lines, 1)
            dec_panel = stdscr.subwin(dec_height, max_x - 2, header_lines + pos_height, 1)
            momentum_panel = stdscr.subwin(momentum_panel_height, max_x - 2, header_lines + pos_height + dec_height, 1)
            debug_panel = stdscr.subwin(debug_panel_height, max_x - 2, header_lines + pos_height + dec_height + momentum_panel_height, 1)

            # Dibujar encabezado
            try:
                stdscr.addstr(0, 0, "EVALUADOR DE MERCADO - NeuroMarkets", curses.A_BOLD | curses.A_REVERSE)
                stdscr.addstr(1, 0, f"Modo actual: {mode} | Última actualización: {time.strftime('%H:%M:%S')}", curses.A_DIM)
                stdscr.addstr(2, 0, "Presiona 'q' para salir, 'm' para monitor, 'e' para evaluador", curses.A_DIM)
            except Exception:
                pass

            # Manejo de teclas no bloqueante
            try:
                key = stdscr.getch()
            except Exception:
                key = -1
            if key != -1:
                if key == ord('q'):
                    break
                elif key == ord('m'):
                    mode = "monitor"
                    evaluator_message = "Modo MONITOR: Evaluación desactivada"
                    logger.log(evaluator_message)
                elif key == ord('e'):
                    mode = "evaluador"
                    evaluator_message = "Modo EVALUADOR: Evaluación activada"
                    for pos in positions_list:
                        pos["reason"] = ""
                    logger.log(evaluator_message)

            # Actualizar datos periódicamente
            now = time.time()
            if now - last_update >= update_interval:
                try:
                    data = await asyncio.to_thread(get_positions, cst, security_token)
                    positions_list = data.get("positions") or data.get("data") or []
                    # Enviar último precio a MomentumHub si está disponible
                    last_price = None
                    source = None
                    if positions_list:
                        try:
                            p = positions_list[0]
                            market = p.get('market', {}) or {}
                            bid = market.get('bid')
                            offer = market.get('offer')
                            if bid is not None and offer is not None:
                                last_price = (float(bid) + float(offer)) / 2.0
                                source = 'market_mid'
                            elif bid is not None:
                                last_price = float(bid)
                                source = 'market_bid'
                            elif offer is not None:
                                last_price = float(offer)
                                source = 'market_offer'
                            if last_price is None:
                                pos_level = p.get('position', {}).get('level')
                                if pos_level is not None:
                                    last_price = float(pos_level)
                                    source = 'position_level'
                        except Exception:
                            last_price = None

                    if last_price is not None:
                        try:
                            logger.log(f"[DEBUG] MomentumHub recibe tick ({source}): {last_price}")
                            metrics = add_tick(last_price)
                            logger.log(f"[DEBUG] Momentum metrics: {metrics}")
                        except Exception as ex:
                            logger.log(f"[ERROR] MomentumHub add_tick failed: {ex}")

                    # 🌍 [MCTX] Market Context debug panel
                    try:
                        mctx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_context.json")
                        if os.path.exists(mctx_path):
                            with open(mctx_path, "r") as _mf:
                                mctx = json.load(_mf)
                            _st = mctx.get("state", "?").upper()
                            _bbl = mctx.get("bb_lower", 0)
                            _bbu = mctx.get("bb_upper", 0)
                            _ema = mctx.get("ema200", 0)
                            _pvs = mctx.get("price_vs_ema200_pct", 0)
                            _sqz = mctx.get("squeeze_pct", 0)
                            logger.log(f"[MCTX] 📊 {_st}  | BB ${_bbl}-${_bbu} | EMA200 ${_ema} ({_pvs:+.1f}%) | Squeeze {_sqz}%")
                    except Exception:
                        pass

                    else:
                        # Logear la ausencia de precio (limitado cada 30s)
                        if now - last_momentum_update > 30:
                            logger.log("[WARN] Momentum: no price available to add tick")
                            last_momentum_update = now

                    # Calcular horas abiertas y otros campos para visualización
                    for pos in positions_list:
                        pos_details = pos.get("position", {})
                        created_str = pos_details.get("createdDateUTC") or pos_details.get("createdDate")
                        pos["hours_open"] = get_hours_open(created_str) if created_str else "N/A"
                        pos["dealId"] = pos_details.get("dealId")
                        pos["direction"] = pos_details.get("direction")
                        pos["size"] = pos_details.get("size")
                        pos["upl"] = pos_details.get("upl")
                    last_update = now
                except Exception as e:
                    positions_list = []
                    logger.log(f"Error al obtener posiciones: {e}")

            # Si estamos en modo evaluador, ejecutar evaluación y cierres
            if mode == "evaluador":
                try:
                    features = {"RSI": 55, "MACD": 1, "VolumeChange": 1}

                    # 🎯 Cargar HTF para sistema de zonas (cache 60s)
                    historical_data = None
                    if time.time() - _dl_cache['time'] > 60:
                        try:
                            from DataLoader import DataLoader
                            loader = DataLoader()
                            _htf, _ltf = loader.load_historical_data()
                            _dl_cache['htf'] = _htf
                            _dl_cache['ltf'] = _ltf
                            _dl_cache['time'] = time.time()
                            historical_data = _htf
                            if _htf is not None and not _htf.empty:
                                logger.log(f"[INFO] 📊 HTF cargado para zonas: {len(_htf)} velas")
                        except Exception as e:
                            logger.log(f"[WARNING] No se pudo cargar HTF para zonas: {e}")
                    else:
                        historical_data = _dl_cache['htf']

                    actions = evaluate_positions(
                        positions_list,
                        features,
                        profittracker,
                        logger.log,
                        historical_data=historical_data
                    )
                    if actions:
                        logger.log(f"Modo EVALUADOR activado | Posiciones a cerrar: {len(actions)}")
                        for action in actions:
                            # ⚡ POST PRIMERO - sin delay
                            result = await asyncio.to_thread(close_position, action, cst, security_token)
                            if result:
                                # ✅ POST exitoso, ahora logging y sonido
                                log_closed_position(action)
                                logger.log(f"✅ Posición {action.get('dealId')} cerrada correctamente.")
                                # 🎵 Sonido DESPUÉS del POST exitoso
                                play_sound('close_position', logger.log)

                                # 📊 Registrar en web_closed_positions.json para dashboard
                                try:
                                    _deal_id = action.get('dealId', 'N/A')
                                    _close_inds = action.get('close_indicators', {}) or {}
                                    _last_inds = action.get('last_indicators', {}) or {}
                                    if _close_inds:
                                        _last_inds.update(_close_inds)

                                    _web_json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_closed_positions.json")
                                    try:
                                        with open(_web_json_path, 'r') as _wf:
                                            _web_cls = json.load(_wf)
                                    except (FileNotFoundError, json.JSONDecodeError):
                                        _web_cls = []

                                    _existing_idx = None
                                    for _wi, _wr in enumerate(_web_cls):
                                        if _wr.get('dealId') == _deal_id:
                                            _existing_idx = _wi
                                            break

                                    _dash_rec = {
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                        "dealId": _deal_id,
                                        "epic": action.get('epic', 'ETHUSD'),
                                        "direction": action.get('direction', 'N/A'),
                                        "size": action.get('size', 0),
                                        "entry_price": action.get('entry_price'),
                                        "last_upl": action.get('last_upl', 0),
                                        "last_upl_pct": action.get('last_upl_pct'),
                                        "max_profit_pct": action.get('max_profit_pct', 0),
                                        "hours_open": action.get('hours_open'),
                                        "last_seen_time": action.get('last_seen_time', datetime.now(timezone.utc).isoformat()),
                                        "last_indicators": _last_inds,
                                        "open_indicators": action.get('open_indicators', {}),
                                        "open_reason": action.get('open_reason', ''),
                                        "open_datetime": action.get('open_datetime', ''),
                                        "exit_price": action.get('exit_price'),
                                        "reason": action.get('reason', 'Bot closure'),
                                        "source": "bot"
                                    }

                                    if _existing_idx is not None:
                                        _web_cls[_existing_idx] = _dash_rec
                                    else:
                                        _web_cls.append(_dash_rec)

                                    with open(_web_json_path, 'w') as _wf:
                                        json.dump(_web_cls, _wf, indent=2)
                                    logger.log(f"[DASHBOARD] ✅ Cierre registrado: {_deal_id[-8:]}")
                                except Exception as _we:
                                    logger.log(f"[WARNING] Dashboard registro falló: {_we}")

                                # 🎯 Detectar winners y activar fast re-entry si aplica
                                try:
                                    deal_id = action.get('dealId')
                                    direction = action.get('direction', '').upper()

                                    # Leer profittracker para obtener max_profit_pct
                                    tracker = profittracker.get(deal_id, {})
                                    max_profit_pct = tracker.get('max_profit_pct', 0.0)

                                    # Obtener señal actual del mercado desde archivos IPC
                                    current_signal = get_current_market_signal()

                                    check_and_activate_fast_reentry(
                                        deal_id=deal_id,
                                        direction=direction,
                                        max_profit_pct=max_profit_pct,
                                        current_signal=current_signal,
                                        debug_callback=logger.log
                                    )
                                except Exception as e:
                                    logger.log(f"[WARN] Winner detection failed: {e}")
                            else:
                                logger.log(f"[ERROR] Al cerrar posición {action.get('dealId')}")
                    else:
                        logger.log("Modo EVALUADOR activado | Ninguna posición cumple criterios para cierre.")
                except Exception as e:
                    logger.log(f"[ERROR] Error en evaluador: {e}")

            # Dibujar paneles
            draw_positions_table(pos_panel, positions_list, mode, previous_upl)
            draw_decisions_table(dec_panel, positions_list, max_x - 2, mode)
            try:
                metrics = get_metrics()
            except Exception:
                metrics = {}

            # Si no hay ticks recopilados (probable caso: procesos separados), usar DataLoader como fallback
            try:
                tick_count = int(metrics.get('tick_count', 0) if metrics else 0)
            except Exception:
                tick_count = 0
            if tick_count == 0:
                # 1) Intentar leer IPC file escrito por EthBoy
                try:
                    if os.path.exists(TICK_IPC_PATH):
                        with open(TICK_IPC_PATH, 'r') as _f:
                            ipc = json.load(_f)
                        p = ipc.get('price')
                        ts = ipc.get('ts')
                        # Aceptar tick si es reciente (<= 300s)
                        if p is not None and (ts is None or (time.time() - float(ts)) < 300):
                            try:
                                add_tick(float(p))
                                metrics = get_metrics()
                                tick_count = int(metrics.get('tick_count', 0))
                            except Exception:
                                pass
                except Exception:
                    pass

                # 2) Si aún no hay ticks, fallback a DataLoader cache (último precio LTF)
                if tick_count == 0:
                    try:
                        if time.time() - _dl_cache['time'] > 60:
                            loader = DataLoader()
                            _htf, _ltf = loader.load_historical_data()
                            _dl_cache['htf'] = _htf
                            _dl_cache['ltf'] = _ltf
                            _dl_cache['time'] = time.time()
                        ltf = _dl_cache['ltf']
                        if ltf is not None and not ltf.empty:
                            # Intentar obtener precio de cierre/last
                            last_row = ltf.iloc[-1]
                            price_candidate = None
                            for key in ('Close', 'close', 'mid', 'price'):
                                if key in last_row.index:
                                    price_candidate = last_row.get(key)
                                    break
                            if price_candidate is None:
                                # intentar columnas comunes Open/High/Low
                                for key in ('Close', 'close', 'Open', 'open'):
                                    if key in last_row.index:
                                        price_candidate = last_row.get(key)
                                        break
                            if price_candidate is not None:
                                try:
                                    pval = float(price_candidate)
                                    add_tick(pval)
                                    metrics = get_metrics()
                                except Exception:
                                    pass
                    except Exception:
                        pass
            draw_momentum_panel(momentum_panel, metrics)
            log_debug_message(debug_panel, debug_messages)

            stdscr.refresh()
            await asyncio.sleep(0.1)
    finally:
        # Restaurar print original
        try:
            builtins.print = original_print
        except Exception:
            pass

def curses_main(stdscr, cst, security_token, auto_mode=False):
    asyncio.run(curses_main_async(stdscr, cst, security_token, auto_mode))

def main(auto_mode=False):
    try:
        auth_data, resp_headers = authenticate()
        ui = globals().get('ui', None)
        if ui:
            ui.add_log("✅ Autenticación exitosa. Sistema listo para operar.")
            ui.add_log("📥 Valores extraídos: BUY=1 | SELL=1")
            ui.add_log("Selecciona una cuenta para monitorear o presiona 'q' para salir.")

        # Extraer tokens de cabeceras (CST y X-SECURITY-TOKEN)
        cst = resp_headers.get('CST') or resp_headers.get('cst') or resp_headers.get('Cst')
        security_token = resp_headers.get('X-SECURITY-TOKEN') or resp_headers.get('x-security-token') or resp_headers.get('X-Security-Token')
        if not cst or not security_token:
            # Intentar obtener desde auth_data si las cabeceras no están presentes
            cst = cst or auth_data.get('CST') or auth_data.get('cst')
            security_token = security_token or auth_data.get('securityToken') or auth_data.get('security_token')

        if not cst or not security_token:
            raise KeyError("No se encontró CST o X-SECURITY-TOKEN en la respuesta de autenticación.")

        # Lanzar la UI curses con los tokens correctos
        while True:
            curses.wrapper(curses_main, cst, security_token, auto_mode)
    except Exception as e:
        import traceback
        print(f"[ERROR FATAL] Evaluador falló al iniciar: {e}")
        print(traceback.format_exc())
        ui = globals().get('ui', None)
        if ui:
            ui.add_log(f"[ERROR] Ocurrió un problema: {e}")

if __name__ == "__main__":
    # SINGLE INSTANCE CHECK: evitar múltiples copias
    lock_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Evaluador.lock")
    lock_file = open(lock_file_path, 'w')
    try:
        if sys.platform == "win32":
            import msvcrt
            lock_file.write(str(os.getpid()))
            lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, len(str(os.getpid())))
        else:
            import fcntl
            fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(f"[INFO] Instance Lock adquirido: {lock_file_path}")
    except (IOError, OSError):
        print(f"[CRITICAL] 🛑 ERROR FATAL: Otra instancia de Evaluador ya está corriendo.")
        print("[INFO] 🔄 Matando proceso existente y reiniciando...")
        import psutil
        current_pid = os.getpid()
        others = []
        for proc in psutil.process_iter(['pid', 'ppid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline')
                if cmdline and any('Evaluador.py' in c for c in cmdline) and proc.info['pid'] != current_pid:
                    others.append(proc)
            except Exception:
                continue

        parents = {}
        for proc in others:
            ppid = proc.info.get('ppid') or 0
            parents.setdefault(ppid, []).append(proc)

        for ppid, procs in parents.items():
            try:
                if ppid == 0 or ppid == current_pid:
                    for p in procs:
                        try:
                            print(f"[INFO] 🛑 Matando hijo PID: {p.pid}")
                            p.kill()
                        except Exception:
                            pass
                    continue

                parent = psutil.Process(ppid)
                parent_name = parent.name().lower()
                if parent_name in ('bash', 'sh', 'zsh', 'tmux', 'screen', 'python', 'python3') or len(procs) > 1:
                    try:
                        print(f"[INFO] 🔧 Terminando padre PID {ppid} ({parent_name}) responsable de {len(procs)} instancias...")
                        parent.terminate()
                        try:
                            parent.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            print(f"[WARN] Padre {ppid} no respondió a terminate, forzando kill")
                            parent.kill()
                    except Exception as e:
                        print(f"[WARN] No se pudo terminar padre {ppid}: {e}")
                        for p in procs:
                            try:
                                print(f"[INFO] 🛑 Matando hijo PID fallback: {p.pid}")
                                p.kill()
                            except Exception:
                                pass
                else:
                    for p in procs:
                        try:
                            print(f"[INFO] 🛑 Matando hijo PID: {p.pid}")
                            p.kill()
                        except Exception:
                            pass
            except psutil.NoSuchProcess:
                continue
            except Exception as e:
                print(f"[WARN] Error procesando padre {ppid}: {e}")

        remaining = []
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline')
                if cmdline and any('Evaluador.py' in c for c in cmdline) and proc.info['pid'] != current_pid:
                    remaining.append(proc.info['pid'])
            except Exception:
                continue

        if remaining:
            print(f"[CRITICAL] 🛑 No se pudo detener todas las instancias. PIDs restantes: {remaining}")
            sys.exit(1)

    # Si llegamos aquí, adquirimos el lock o terminamos instancias previas
    auto_mode = "--auto" in sys.argv
    main(auto_mode=auto_mode)
