from rich.live import Live
from RichScanUI import RichScanUI
# PyQt5 no se usa - interfaz de terminal con rich/curses
# from PyQt5.QtWidgets import QApplication
# from PyQt5.QtCore import QObject, pyqtSignal
from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from datetime import datetime, timezone, timedelta, UTC
from EthSession import CapitalOP
from EthStrategy import Strategia
from TimingHelper import TimingOptimizer  # 🔹 NUEVO: Timing preciso con 1M
from threading import Lock
from state import BotState
from DataLoader import DataLoader  # 🔹 NUEVO: Loader híbrido Parquet + JSON
from MomentumHub import add_tick, get_metrics
import os
# Intentar importar el cliente de streaming JSON
try:
    from lightstream_minimal import LightMinimal
except Exception:
    LightMinimal = None

# Cache para DataLoader (recargar cada 60s)
_dl_cache = {'time': 0, 'htf': None, 'ltf': None}

# IPC file path para compartir último tick entre procesos
TICK_IPC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "momentum_tick.json")
 
import subprocess
import threading
import itertools
import pandas as pd
import numpy as np
import textwrap
import json
import time
import sys
import os
import io
import contextlib
import numbers
import logging
import logging.handlers


# ═══════════════════════════════════════════════════════════════════════════
# 📝 ROTATING LOG (rollback a 10MB, conserva 5 backups) en logs/
# ═══════════════════════════════════════════════════════════════════════════
def setup_rotating_log():
    """Configura el logger raíz para escribir en logs/ethboy.log,
    rotando (rollback) cuando el archivo alcanza 10MB y conservando 5 backups."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(script_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "ethboy.log")

    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)
    return handler


# ═══════════════════════════════════════════════════════════════════════════
# 🔄 AUTO-UPDATE DESDE REPOSITORIO GITHUB
# ═══════════════════════════════════════════════════════════════════════════
def auto_update_from_github():
    """
    Verifica y descarga automáticamente cambios desde el repositorio GitHub.
    Se ejecuta al inicio de EthBoy para mantener el código actualizado.
    
    Features:
    - Verifica si hay actualizaciones disponibles
    - Descarga cambios automáticamente (git pull)
    - Muestra resumen de archivos actualizados
    - No interrumpe ejecución si falla (fallback silencioso)
    - Compatible con branch main
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        logging.info("\n╔═══════════════════════════════════════════════════════════════╗")
        logging.info("║         🔄 AUTO-UPDATE: Verificando actualizaciones...       ║")
        logging.info("╚═══════════════════════════════════════════════════════════════╝\n")
        
        # Verificar si estamos en un repositorio git
        git_check = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if git_check.returncode != 0:
            logging.info("[INFO] ⚠️  No estamos en un repositorio Git. Auto-update deshabilitado.")
            return False
        
        # Obtener branch actual
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        current_branch = branch_result.stdout.strip() or "main"
        
        # Obtener hash actual (antes del pull)
        hash_before = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        commit_before = hash_before.stdout.strip()[:7]
        
        logging.info(f"[INFO] 📂 Directorio: {script_dir}")
        logging.info(f"[INFO] 🌿 Branch: {current_branch}")
        logging.info(f"[INFO] 📌 Commit actual: {commit_before}")
        
        # Fetch para verificar actualizaciones
        logging.info("\n[INFO] 🔍 Consultando GitHub...")
        fetch_result = subprocess.run(
            ["git", "fetch", "origin", current_branch],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=15
        )
        
        if fetch_result.returncode != 0:
            logging.warning(f"[WARNING] ⚠️  Fetch falló: {fetch_result.stderr.strip()}")
            logging.info("[INFO] ➡️  Continuando con versión actual...")
            return False
        
        # Verificar si hay cambios
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", f"HEAD..origin/{current_branch}"],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        changed_files = [f for f in diff_result.stdout.strip().split('\n') if f]
        
        if not changed_files:
            logging.info("[INFO] ✅ Ya estás en la última versión. No hay actualizaciones.")
            return False
        
        # Hay cambios disponibles
        logging.info(f"\n[UPDATE] 🆕 {len(changed_files)} archivo(s) con cambios disponibles:")
        for i, file in enumerate(changed_files[:10], 1):  # Mostrar max 10
            logging.info(f"  {i}. {file}")
        if len(changed_files) > 10:
            logging.info(f"  ... y {len(changed_files) - 10} más")
        
        # Hacer git pull
        logging.info("\n[UPDATE] 📥 Descargando actualizaciones...")
        pull_result = subprocess.run(
            ["git", "pull", "origin", current_branch],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if pull_result.returncode != 0:
            logging.error(f"[ERROR] ❌ Pull falló: {pull_result.stderr.strip()}")
            logging.info("[INFO] ➡️  Continuando con versión actual...")
            return False
        
        # Hash después del pull
        hash_after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        commit_after = hash_after.stdout.strip()[:7]
        
        # Mostrar último commit
        log_result = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%s"],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=5
        )
        last_commit_msg = log_result.stdout.strip()
        
        logging.info("\n╔═══════════════════════════════════════════════════════════════╗")
        logging.info("║              ✅ ACTUALIZACIÓN COMPLETADA                      ║")
        logging.info("╚═══════════════════════════════════════════════════════════════╝")
        logging.info(f"\n[SUCCESS] 📌 Commit: {commit_before} → {commit_after}")
        logging.info(f"[SUCCESS] 📝 Último cambio: {last_commit_msg}")
        logging.info(f"[SUCCESS] 📦 Archivos actualizados: {len(changed_files)}")
        logging.info("\n[INFO] 🚀 Iniciando EthBoy con código actualizado...\n")
        
        return True
        
    except subprocess.TimeoutExpired:
        logging.error("[ERROR] ⏱️  Timeout durante auto-update. Continuando con versión actual...")
        return False
    except FileNotFoundError:
        logging.warning("[WARNING] ⚠️  Git no encontrado. Auto-update requiere Git instalado.")
        return False
    except Exception as e:
        logging.error(f"[ERROR] ❌ Auto-update falló: {e}")
        logging.info("[INFO] ➡️  Continuando con versión actual...")
        return False


class TradingOperator:
    def set_ui(self, ui):
        self.ui = ui

    def is_legacy(self, position):
        """Determina si una posición es legacy (abierta hace más de 200 horas). Usa createdDate, created u open_time."""
        created = position.get('createdDate') or position.get('created') or position.get('open_time')
        if not created:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[LEGACY-DEBUG] Posición sin campo de fecha: {position}")
            return False
        try:
            # Si es string tipo fecha, convertir a timestamp
            if isinstance(created, str):
                # Si es string tipo fecha (ej: 2026-01-14T16:02:18.101)
                if 'T' in created:
                    created_dt = pd.to_datetime(created, utc=True)
                    created_ts = created_dt.timestamp()
                else:
                    created_ts = float(created)
            else:
                created_ts = float(created)
            now_ts = time.time()
            hours_open = (now_ts - created_ts) / 3600
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[LEGACY-DEBUG] ID: {position.get('dealId', 'N/A')} | Fecha apertura: {created} | Timestamp: {created_ts} | Horas abiertas: {hours_open:.2f}")
            # Cambiado: considerar legacy si está abierta >= 24 horas (antes 200h)
            return hours_open >= 24
        except Exception as e:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[LEGACY] Error evaluando legacy: {e} | Posición: {position}")
            return False
 
    # positions_updated = pyqtSignal(list)
 
    def __init__(self, features, strategy, saldo_update_callback):
        # super().__init__()  # Eliminado - no hereda de QObject
        self.features = [f.strip() for f in features]  # Características definidas (para validaciones o logs)
        self.strategy = strategy
        self.log_open_positions = []
        self.log_process_data = []
        # Se elimina el uso de estados y escalado/desescalado
        self.capital_ops = CapitalOP()
        self.account_id = self.capital_ops.account_id
        self.capital_ops.max_buy_positions = 3   # Francia: hasta 3 BUY
        self.capital_ops.max_sell_positions = 1
        self.max_total_positions = 4
        self.last_processed_minute = None  # 🛡️ Tracker para evitar procesar el mismo minuto múltiples veces
        self.capital_ops.authenticate()  # 🔹 Autenticar DESPUÉS de configurar account_id
        if self.capital_ops.session_token:
            self.capital_ops.ensure_correct_account()  # Verificar cuenta correcta
        # light client will be started later when UI is available
        self.positions = []
        self.saldo_update_callback = saldo_update_callback
        self.last_processed_index = -1
        self.balance = 0
        self.position_tracker = {}
        self.data_lock = Lock()
        self.historical_data = None
        self.timing_optimizer = TimingOptimizer()  # 🔹 NUEVO: Optimizador de timing
        # Timestamp del último tick recibido (epoch seconds)
        self._last_tick_ts = 0
        # Cache de última ejecución de DataEth.py (evita llamadas excesivas)
        self.last_dataeth_run = None
        # Archivo de salud de DataEth (registro de cada ejecución)
        self.dataeth_health_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataeth_health.json")
        # Thread para actualizar HTF periódicamente
        self.htf_updater_thread = None
        self.htf_update_interval = 7200  # 2 horas en segundos

        # 🔹 COOLDOWN LOCAL PERSISTENTE
        # Archivo para guardar la última operación y evitar duplicados por lag
        self.cooldown_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eth_trade_cooldown.json")
        self.cooldown_minutes = 1  # ⚡ REDUCIDO: 1 minuto para mayor frecuencia de trading

        # 🔹 REGISTRO LOCAL DE ÓRDENES PENDIENTES
        # Evita abrir múltiples operaciones mientras la API procesa la anterior
        self.pending_order = None  # Estructura: {"type": "BUY/SELL", "timestamp": time.time()}        

    def _persist_log_entry(self, entry):
        """Persistir cada log_entry en formato JSONL para trazabilidad."""
        try:
            # Auto-inyectar indicadores si el entry no los tiene todavía
            if 'values' not in entry and getattr(self, '_current_indicators', None):
                entry['values'] = self._current_indicators
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "process_data.jsonl")
            with open(filepath, 'a', encoding='utf-8') as fh:
                json.dump(entry, fh, ensure_ascii=False)
                fh.write("\n")
        except Exception as e:
            # 🔴 NO silenciar errores - registrar en consola siempre
            error_msg = f"[ERROR] Failed to persist log_entry: {e}"
            logging.error(error_msg)
            ui = getattr(self, 'ui', None)
            if ui:
                try:
                    ui.add_log(error_msg)
                except Exception:
                    pass

    def _save_entry_snapshot(self, deal_id, log_entry):
        """Guarda snapshot de indicadores y razón al abrir una posición (para el panel de UI)."""
        try:
            snap_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entry_snapshots.json")
            try:
                with open(snap_file, 'r', encoding='utf-8') as f:
                    snapshots = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                snapshots = {}
            values = log_entry.get('values', {})
            snapshots[deal_id] = {
                "open_datetime": log_entry.get('datetime', ''),
                "open_price": log_entry.get('current_price'),
                "direction": log_entry.get('decision'),
                "reason": log_entry.get('reason', ''),
                "strategy_score": log_entry.get('strategy_score'),
                "indicators": {
                    "RSI": values.get('RSI'),
                    "MACD": values.get('MACD'),
                    "ATR": values.get('ATR'),
                    "VolumeChange": values.get('VolumeChange'),
                    "MACD_Histogram": values.get('MACD_Histogram'),
                }
            }
            with open(snap_file, 'w', encoding='utf-8') as f:
                json.dump(snapshots, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.warning(f"[WARNING] No se pudo guardar entry snapshot: {e}")

    def check_trade_cooldown(self):
        """Verifica si ha pasado suficiente tiempo desde la última operación.
        BYPASS: Permite re-entrada inmediata si el último cierre fue un 'winner' con tendencia continuada.
        """
        if not os.path.exists(self.cooldown_file):
            return True, "No hay registro de cooldown previo."
        
        try:
            with open(self.cooldown_file, 'r') as f:
                data = json.load(f)
                last_trade_time = data.get('last_trade_time', 0)
                allow_fast_reentry = data.get('allow_fast_reentry', False)
                last_direction = data.get('last_direction', None)
            
            # 🚀 BYPASS: Si el último cierre fue un winner con tendencia continuada
            if allow_fast_reentry:
                # Limpiar el flag después de usarlo
                try:
                    data['allow_fast_reentry'] = False
                    with open(self.cooldown_file, 'w') as f:
                        json.dump(data, f)
                except Exception:
                    pass
                return True, f"🎯 Fast re-entry permitida: Último cierre fue winner con tendencia continuada ({last_direction})"
            
            elapsed_minutes = (time.time() - last_trade_time) / 60
            if elapsed_minutes < self.cooldown_minutes:
                return False, f"Cooldown activo: Pasaron {elapsed_minutes:.1f}m/{self.cooldown_minutes}m desde última orden."
            return True, "Cooldown expirado. Ready."
        except Exception as e:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[WARNING] Error leyendo cooldown file: {e}")
            return True, "Error leyendo archivo."

    def set_trade_cooldown(self, direction=None):
        """Marca el timestamp de la operación actual."""
        try:
            with open(self.cooldown_file, 'w') as f:
                json.dump({
                    'last_trade_time': time.time(),
                    'last_direction': direction,
                    'allow_fast_reentry': False  # Por defecto no permite reentry rápida
                }, f)
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log("[INFO] 🕒 Cooldown establecido correctamente.")
        except Exception as e:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[ERROR] No se pudo guardar el cooldown: {e}")
 
    def start_htf_updater(self):
        """
        Inicia thread que actualiza HTF cada 2 horas en background.
        No bloquea el loop principal.
        """
        def _htf_updater_loop():
            # 🔹 PRIMERA ACTUALIZACIÓN INMEDIATA (no esperar 2h)
            try:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log("[INFO] 🔄 Actualización inicial HTF...")
                self.update_historical_data()
            except Exception as e:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[ERROR] Error en actualización inicial HTF: {e}")
                    import traceback
                    ui.add_log(f"[DEBUG] {traceback.format_exc()}")
            
            # Loop de actualizaciones periódicas
            while True:
                try:
                    time.sleep(self.htf_update_interval)
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log("[INFO] 🔄 Actualización periódica HTF (cada 2h)...")
                    self.update_historical_data()
                except Exception as e:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"[ERROR] Error en HTF updater: {e}")
                        import traceback
                        ui.add_log(f"[DEBUG] {traceback.format_exc()}")
        
        self.htf_updater_thread = threading.Thread(target=_htf_updater_loop, daemon=True)
        self.htf_updater_thread.start()
        ui = getattr(self, 'ui', None)
        if ui:
            ui.add_log(f"[INFO] ✅ HTF updater iniciado (intervalo: {self.htf_update_interval/3600:.1f}h)")
    
    def _manual_export_data(self, htf_data, ltf_data, output_file):
        """Exportación manual de datos para evitar problemas con prepare_for_export"""
        import json
        import pandas as pd
        
        export_data = {
            'historical_data': [],
            'ltf_data': []
        }
        
        # Convertir HTF a lista de dicts con timestamps
        if not htf_data.empty:
            for idx, row in htf_data.iterrows():
                record = {
                    'timestamp': idx.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
                    'Open': float(row['Open']),
                    'High': float(row['High']),
                    'Low': float(row['Low']),
                    'Close': float(row['Close']),
                    'Volume': float(row['Volume'])
                }
                # Agregar indicadores si existen
                for col in row.index:
                    if col not in ['Open', 'High', 'Low', 'Close', 'Volume']:
                        try:
                            record[col] = float(row[col]) if pd.notna(row[col]) else 0.0
                        except:
                            record[col] = 0.0
                export_data['historical_data'].append(record)
        
        # Convertir LTF a lista de dicts con timestamps
        if not ltf_data.empty:
            for idx, row in ltf_data.iterrows():
                record = {
                    'timestamp': idx.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
                    'Open': float(row['Open']),
                    'High': float(row['High']),
                    'Low': float(row['Low']),
                    'Close': float(row['Close']),
                    'Volume': float(row['Volume'])
                }
                # Agregar indicadores si existen
                for col in row.index:
                    if col not in ['Open', 'High', 'Low', 'Close', 'Volume']:
                        try:
                            record[col] = float(row[col]) if pd.notna(row[col]) else 0.0
                        except:
                            record[col] = 0.0
                export_data['ltf_data'].append(record)
        
        # Guardar archivo
        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2)

    def _log_dataeth_health(self, run_type, duration_s, htf_rows, ltf_rows, status, error=None):
        """Persiste cada ejecución de DataEth en dataeth_health.json para el dashboard."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": run_type,
            "duration_s": round(duration_s, 1),
            "htf_rows": htf_rows,
            "ltf_rows": ltf_rows,
            "status": status,
        }
        if error:
            entry["error"] = str(error)[:300]
        try:
            try:
                with open(self.dataeth_health_file, "r", encoding="utf-8") as _f:
                    _log = json.load(_f)
            except Exception:
                _log = []
            _log.append(entry)
            _log = _log[-200:]  # Mantener las últimas 200 ejecuciones
            with open(self.dataeth_health_file, "w", encoding="utf-8") as _f:
                json.dump(_log, _f, ensure_ascii=False)
        except Exception:
            pass

    def update_historical_data(self, force=False):
        """
        Ejecuta DataEth.py para descargar/actualizar datos históricos.
        
        DataEth.py decide internamente si necesita actualizar según:
        - HTF: Actualiza si última vela > 2h antigüedad (ventana: 200 velas)
        - LTF: Actualiza si última vela > 5min antigüedad (ventana: 200 velas)
        
        Cache: No ejecuta DataEth.py si se corrió hace < 5 minutos.
        """
        _health_start = time.monotonic()
        try:
            # 🔹 CACHE: Evitar ejecutar DataEth.py si se corrió hace < 5min (salvo force=True)
            now = datetime.now(timezone.utc)
            if not force and self.last_dataeth_run is not None:
                elapsed = (now - self.last_dataeth_run).total_seconds() / 60
                if elapsed < 5.0:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"[INFO] ⏭️  DataEth.py ejecutado hace {elapsed:.1f}min. Saltando actualización.")
                    # Recargar desde cache DataLoader
                    if time.time() - _dl_cache['time'] > 60:
                        loader = DataLoader()
                        _dl_cache['htf'], _dl_cache['ltf'] = loader.load_historical_data()
                        _dl_cache['time'] = time.time()
                    self.historical_data = _dl_cache['htf']
                    return
            
            script_dir = os.path.dirname(os.path.abspath(__file__))
            dataeth_path = os.path.join(script_dir, "DataEth.py")
            output_file = os.path.join(script_dir, "Reports", "ETHUSD_CapitalData.json")
 
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[INFO] 🔄 DataEth: Poblando datos históricos...")
            else:
                logging.info(f"[INFO] 🔄 DataEth: Poblando datos históricos...")
 
            if not os.path.exists(dataeth_path):
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[ERROR] ❌ No se encontró DataEth.py en {dataeth_path}")
                else:
                    logging.error(f"[ERROR] ❌ No se encontró DataEth.py en {dataeth_path}")
                return
 
            # Ejecutar DataEth directamente en lugar de subprocess para mejor control
            try:
                import DataEth
                from datetime import datetime, timezone, timedelta
                import json
                
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[INFO] 📊 DataEth: Descargando datos HTF (5 años)...")
                else:
                    logging.info(f"[INFO] 📊 DataEth: Descargando datos HTF (5 años)...")
                
                # Configurar fechas como en DataEth.py
                end_date = datetime.now(timezone.utc)
                htf_start = end_date - timedelta(days=5*365)  # 5 años para HTF
                ltf_start = end_date - timedelta(days=7)      # 7 días para LTF
                
                # Descargar HTF
                htf_data, htf_meta = DataEth.download_data_capital('ETHUSD', 'HOUR', htf_start, end_date)
                if ui:
                    ui.add_log(f"[INFO] ✅ HTF descargado: {len(htf_data)} registros")
                else:
                    logging.info(f"[INFO] ✅ HTF descargado: {len(htf_data)} registros")
                
                # Descargar LTF
                if ui:
                    ui.add_log(f"[INFO] 📊 DataEth: Descargando datos LTF (7 días)...")
                else:
                    logging.info(f"[INFO] 📊 DataEth: Descargando datos LTF (7 días)...")
                    
                ltf_data, ltf_meta = DataEth.download_data_capital('ETHUSD', 'MINUTE', ltf_start, end_date)
                if ui:
                    ui.add_log(f"[INFO] ✅ LTF descargado: {len(ltf_data)} registros")
                else:
                    logging.info(f"[INFO] ✅ LTF descargado: {len(ltf_data)} registros")
                
                # Validar que se descargaron datos
                if len(htf_data) == 0 and len(ltf_data) == 0:
                    if ui:
                        ui.add_log(f"[WARNING] ⚠️ No se descargaron datos")
                    else:
                        logging.warning(f"[WARNING] ⚠️ No se descargaron datos")
                    return
                
                # 🔹 CALCULAR INDICADORES (crucial para que prepare_for_export funcione)
                if ui:
                    ui.add_log(f"[INFO] 📊 Calculando indicadores técnicos...")
                else:
                    logging.info(f"[INFO] 📊 Calculando indicadores técnicos...")
                
                if len(htf_data) > 0:
                    htf_data = DataEth.calculate_indicators(htf_data)
                if len(ltf_data) > 0:
                    ltf_data = DataEth.calculate_ltf_indicators(ltf_data)
                
                # 🔹 EXPORTAR A PARQUET (usando función nativa de DataEth)
                if ui:
                    ui.add_log(f"[INFO] 📁 Exportando a Parquet...")
                else:
                    logging.info(f"[INFO] 📁 Exportando a Parquet...")
                
                DataEth.prepare_for_export(htf_data, ltf_data, mode="full")
                
                if ui:
                    ui.add_log(f"[INFO] ✅ Datos exportados a Parquet correctamente")
                else:
                    logging.info(f"[INFO] ✅ Datos exportados a Parquet correctamente")
                    
            except Exception as e:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[ERROR] ❌ Error ejecutando DataEth: {e}")
                else:
                    logging.error(f"[ERROR] ❌ Error ejecutando DataEth: {e}")
                import traceback
                if ui:
                    ui.add_log(f"[DEBUG] Traceback: {traceback.format_exc()}")
                else:
                    logging.debug(f"[DEBUG] Traceback: {traceback.format_exc()}")
                return
 
            # Marcar como exitoso
            self.last_dataeth_run = datetime.now(timezone.utc)  # Actualizar cache
 
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[INFO] 📂 Cargando datos actualizados con DataLoader...")
 
            # 🔹 USAR DataLoader (fuerza recarga post-DataEth)
            loader = DataLoader()
            _dl_cache['htf'], _dl_cache['ltf'] = loader.load_historical_data()
            _dl_cache['time'] = time.time()
            self.historical_data = _dl_cache['htf']
            
            if self.historical_data.empty:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log("[ERROR] ❌ DataLoader no pudo cargar datos actualizados")
                return

            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log("[INFO] ✅ Datos históricos cargados exitosamente.")
            _htf_count = len(self.historical_data) if self.historical_data is not None and not self.historical_data.empty else 0
            self._log_dataeth_health("full", time.monotonic() - _health_start, _htf_count, 0, "ok")
 
        except Exception as e:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[ERROR] ❌ Error al actualizar datos históricos: {e}")
            self._log_dataeth_health("full", time.monotonic() - _health_start, 0, 0, "error", str(e))
 
    def run_main_loop(self, data_frame, interval=30):
        """
        Loop principal del bot que ejecuta el ciclo de trading y actualiza la UI RichScanUI.
        """
        ui = getattr(self, 'ui', None)
        if ui is None:
            ui = RichScanUI()
            self.set_ui(ui)
            try:
                ui.add_log("[INFO] RichScanUI creado y asignado a TradingOperator.")
            except Exception:
                pass
            # Redirigir todas las llamadas a print() hacia la UI log
            try:
                import builtins
                self._orig_print = builtins.print
                def _ui_print(*args, **kwargs):
                    try:
                        s = " ".join(str(a) for a in args)
                        ui.add_log(s)
                    except Exception:
                        try:
                            self._orig_print(*args, **kwargs)
                        except Exception:
                            pass
                builtins.print = _ui_print
                # Añadir handler para el módulo `logging` que reenvíe a la UI
                try:
                    import logging
                    class _UIHandler(logging.Handler):
                        def emit(self, record):
                            try:
                                msg = self.format(record)
                                ui.add_log(f"[{record.levelname}] {msg}")
                            except Exception:
                                pass
                    ui_handler = _UIHandler()
                    ui_handler.setLevel(logging.DEBUG)
                    logging.getLogger().addHandler(ui_handler)
                    self._ui_log_handler = ui_handler
                except Exception:
                    self._ui_log_handler = None
            except Exception:
                pass
            # Iniciar cliente de streaming ahora que la UI existe para recibir logs
            try:
                if LightMinimal is not None and not getattr(self, '_light_started', False):
                    try:
                        # Pasar callback de tick para actualizar UI en tiempo real (precio tick-a-tick)
                        def _tick_cb(p, ts):
                            try:
                                ui.update_account(getattr(self, 'balance', 0.0), float(p))
                            except Exception:
                                pass
                            try:
                                # Alimentar MomentumHub directamente desde el WebSocket (tick-a-tick real)
                                add_tick(float(p), timestamp=ts)
                                metrics = get_metrics()
                                ui_ref = getattr(self, 'ui', None)
                                if ui_ref:
                                    ui_ref.update_momentum(metrics)
                            except Exception:
                                pass
                            try:
                                # Registrar último tick y convertir timestamp a segundos
                                tsv = float(ts)
                                if tsv > 1e11:  # probablemente milisegundos
                                    tsv = tsv / 1000.0
                                self._last_tick_ts = tsv
                            except Exception:
                                pass
                            # No registrar ticks en el log de UI (demasiado ruidoso)
                        # Usar el epic reconocido por el stream (ETHUSD) para asegurar ticks
                        self.light_client = LightMinimal(epic="ETHUSD", host=None, log_fn=ui.add_log, tick_fn=_tick_cb)
                        t = threading.Thread(target=self.light_client.run, daemon=True)
                        t.start()
                        self._light_thread = t
                        self._light_started = True
                        try:
                            ui.add_log("[INFO] 🔌 Lightstream minimal iniciado en background (ETHEREUM, empujando ticks a MomentumHub).")
                        except Exception:
                            pass
                    except Exception as e:
                        try:
                            ui.add_log(f"[WARN] No se pudo iniciar LightMinimal: {e}")
                        except Exception:
                            pass
            except Exception:
                pass
        console = Console(force_terminal=True)
        with Live(ui.render(), refresh_per_second=2, console=console, screen=True) as live:
            # Exponer el objeto Live en la UI para permitir redraw desde callbacks
            try:
                setattr(ui, '_live', live)
            except Exception:
                pass
            try:
                # Hilo background: obtiene precio en tiempo real desde Binance ticker
                # (fallback al IPC JSON si falla la API)
                _BINANCE_TICKER = "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT"
                _KRAKEN_TICKER  = "https://api.kraken.com/0/public/Ticker?pair=ETHUSD"
                _last_live_price = [None]  # lista mutable para compartir entre scopes

                def tick_poller():
                    import requests as _req
                    _session = _req.Session()
                    _session.headers.update({"User-Agent": "EthBoy/1.0"})
                    while True:
                        price = None
                        try:
                            # Intento 1: Binance ticker (sin auth, ~50ms)
                            r = _session.get(_BINANCE_TICKER, timeout=2)
                            if r.status_code == 200:
                                price = float(r.json().get("price", 0))
                        except Exception:
                            pass
                        if not price:
                            try:
                                # Intento 2: Kraken ticker como fallback
                                r = _session.get(_KRAKEN_TICKER, timeout=2)
                                if r.status_code == 200:
                                    result = r.json().get("result", {})
                                    pair = next(iter(result.values()), {})
                                    price = float(pair.get("c", [0])[0])
                            except Exception:
                                pass
                        if not price:
                            try:
                                # Intento 3: IPC JSON como último recurso
                                if os.path.exists(TICK_IPC_PATH):
                                    with open(TICK_IPC_PATH, 'r') as _f:
                                        payload = json.load(_f)
                                    price = float(payload.get("price", 0)) if payload else None
                            except Exception:
                                pass
                        if price and price > 0:
                            # Solo alimentar si el precio cambió (evitar ticks duplicados)
                            if _last_live_price[0] != price:
                                _last_live_price[0] = price
                                now_ts = time.time()
                                try:
                                    setattr(self, '_last_tick_ts', now_ts)
                                except Exception:
                                    pass
                                try:
                                    add_tick(price, timestamp=now_ts)
                                except Exception:
                                    pass
                                try:
                                    metrics = get_metrics()
                                    ui_ref = getattr(self, 'ui', None)
                                    if ui_ref:
                                        ui_ref.update_momentum(metrics)
                                        try:
                                            ui_ref.update_account(getattr(self, 'balance', 0.0), price)
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                        time.sleep(1.0)

                poller_thread = threading.Thread(target=tick_poller, daemon=True)
                poller_thread.start()
                
                # Control de actualización DataEth: cada 30 minutos
                # Forzar primera ejecución inmediata en el primer ciclo
                last_dataeth_update = datetime.now(UTC) - timedelta(minutes=31)
                dataeth_update_interval_minutes = 30
                _dataeth_thread_running = [False]  # flag para evitar solapamiento

                while True:
                    now = datetime.now(UTC)
                    minutes_since_dataeth = (now - last_dataeth_update).total_seconds() / 60

                    # Cada 30 minutos: actualización incremental DataEth en background
                    if minutes_since_dataeth >= dataeth_update_interval_minutes and not _dataeth_thread_running[0]:
                        last_dataeth_update = now  # marcar antes de lanzar para no re-disparar
                        _dataeth_thread_running[0] = True

                        def _run_dataeth_incremental(ui_ref=ui, op=self):
                            _inc_start = time.monotonic()
                            try:
                                ui_ref.add_log("[DataEth] Actualizacion incremental iniciada (HTF 48h + LTF 7d)...")
                                import DataEth as _de
                                _end = datetime.now(UTC)
                                _htf_new, _ = _de.download_data_capital('ETHUSD', 'HOUR',  _end - timedelta(hours=48), _end)
                                _ltf_new, _ = _de.download_data_capital('ETHUSD', 'MINUTE', _end - timedelta(days=7),  _end)

                                if _htf_new is not None and not _htf_new.empty:
                                    _htf_new = _de.calculate_indicators(_htf_new, buffer_days=2)
                                if _ltf_new is not None and not _ltf_new.empty:
                                    _ltf_new = _de.calculate_ltf_indicators(_ltf_new)

                                # Cargar Parquet existente (fuerza recarga)
                                _loader = DataLoader()
                                _ex_htf, _ex_ltf = _loader.load_historical_data()
                                _dl_cache['htf'] = _ex_htf
                                _dl_cache['ltf'] = _ex_ltf
                                _dl_cache['time'] = time.time()

                                def _merge(existing, fresh):
                                    if fresh is None or (hasattr(fresh, 'empty') and fresh.empty):
                                        return existing
                                    if existing is None or (hasattr(existing, 'empty') and existing.empty):
                                        return fresh
                                    combined = pd.concat([existing, fresh])
                                    combined = combined[~combined.index.duplicated(keep='last')]
                                    return combined.sort_index()

                                _merged_htf = _merge(_ex_htf, _htf_new)
                                _merged_ltf = _merge(_ex_ltf, _ltf_new)

                                # Guardar Parquet actualizados
                                _de.prepare_for_export(_merged_htf, _merged_ltf)

                                # Recargar en memoria desde Parquet fresco (usa cache post-merge)
                                op.historical_data = _dl_cache['htf']
                                _ltf_loaded = _dl_cache['ltf']
                                _last = op.historical_data.index[-1].strftime('%Y-%m-%d %H:%M') if not op.historical_data.empty else 'N/A'
                                _htf_inc = len(op.historical_data) if not op.historical_data.empty else 0
                                _ltf_inc = len(_ltf_loaded) if _ltf_loaded is not None and not _ltf_loaded.empty else 0
                                ui_ref.add_log(f"[DataEth] OK | HTF {_htf_inc} velas | ultima: {_last}")
                                op._log_dataeth_health("incremental", time.monotonic() - _inc_start, _htf_inc, _ltf_inc, "ok")
                            except Exception as _e:
                                ui_ref.add_log(f"[DataEth] Error en actualizacion incremental: {_e}")
                                op._log_dataeth_health("incremental", time.monotonic() - _inc_start, 0, 0, "error", str(_e))
                            finally:
                                _dataeth_thread_running[0] = False

                        threading.Thread(target=_run_dataeth_incremental, daemon=True).start()
                    
                    # Cargar HTF desde Parquet (cacheado)
                    try:
                        if self.historical_data is None or self.historical_data.empty:
                            if time.time() - _dl_cache['time'] > 60:
                                loader = DataLoader()
                                _dl_cache['htf'], _dl_cache['ltf'] = loader.load_historical_data()
                                _dl_cache['time'] = time.time()
                            self.historical_data = _dl_cache['htf']
                        
                        if self.historical_data is not None and not self.historical_data.empty:
                            data_frame = self.historical_data
                            htf_last_timestamp = self.historical_data.index[-1]
                            # Asegurar timezone para cálculo de edad
                            if htf_last_timestamp.tz is None:
                                htf_last_timestamp = htf_last_timestamp.tz_localize('UTC')
                            htf_last = htf_last_timestamp.strftime('%Y-%m-%d %H:%M')
                            htf_age_minutes = (datetime.now(UTC) - htf_last_timestamp).total_seconds() / 60
                            htf_range = f"{self.historical_data.index[0].strftime('%Y-%m-%d')} → {htf_last}"
                            ui.add_log(f"✅ HTF (HOUR) disponible: {len(self.historical_data)} velas ({htf_range}) | Edad última vela: {htf_age_minutes:.0f} min")
                        else:
                            ui.add_log("⚠️ Los datos HTF están vacíos después de la carga.")
                            time.sleep(interval)
                            continue
                    except Exception as e:
                        ui.add_log(f"❌ Error cargando datos: {e}")
                        time.sleep(interval)
                        continue

                    # Validar el índice de tiempo
                    if not isinstance(data_frame.index, pd.DatetimeIndex):
                        data_frame.index = pd.to_datetime(data_frame.index, errors='coerce')
                    if data_frame.index.tz is None:
                        data_frame.index = data_frame.index.tz_localize("UTC")
                    if data_frame.index.hasnans:
                        data_frame = data_frame[~data_frame.index.isna()]
                    if data_frame.empty:
                        ui.add_log("⚠️ El DataFrame está vacío. No hay datos para procesar.")
                        time.sleep(interval)
                        continue

                    latest_row = self.get_latest_data(data_frame)
                    latest_timestamp = data_frame.index[-1]
                    if not isinstance(latest_timestamp, pd.Timestamp):
                        time.sleep(interval)
                        continue
                    if latest_timestamp.tz is None:
                        latest_timestamp = latest_timestamp.tz_localize("UTC")

                    try:
                        balance, positions = self.update_balance_and_positions()
                        # Actualizar precio local y alimentar MomentumHub
                        price_val = None
                        try:
                            if isinstance(latest_row, dict):
                                price_val = (latest_row.get('Close') or latest_row.get('close') or latest_row.get('mid') or latest_row.get('price'))
                            else:
                                # pd.Series
                                price_val = (latest_row.get('Close') if 'Close' in latest_row.index else (latest_row.get('close') if 'close' in latest_row.index else None))
                            if price_val is not None:
                                price_val = float(price_val)
                                self.price = price_val
                                try:
                                    add_tick(price_val)
                                    # Actualizar métricas de momentum en la UI rich si existe
                                    try:
                                        metrics = get_metrics()
                                        ui = getattr(self, 'ui', None)
                                        if ui:
                                            ui.update_momentum(metrics)
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                                # Escribir último tick a IPC (atomically)
                                try:
                                    tmp = TICK_IPC_PATH + ".tmp"
                                    with open(tmp, 'w') as _f:
                                        json.dump({"price": price_val, "ts": time.time()}, _f)
                                    os.replace(tmp, TICK_IPC_PATH)
                                except Exception:
                                    # No bloquear si falla IPC
                                    pass
                        except Exception:
                            price_val = getattr(self, 'price', 0.0)
                        # Priorizar precio de último tick si es reciente para evitar sobrescribirlo
                        try:
                            price_to_show = price_val if price_val is not None else (self.price if hasattr(self, 'price') else 0.0)
                            recent_tick_price = None
                            if hasattr(self, '_last_tick_ts') and self._last_tick_ts:
                                # si el último tick fue en los últimos 10s, preferir ese precio
                                if time.time() - float(self._last_tick_ts) < 10:
                                    try:
                                        metrics = get_metrics()
                                        recent_tick_price = metrics.get('price')
                                    except Exception:
                                        recent_tick_price = None
                            if recent_tick_price is not None:
                                ui.update_account(balance, float(recent_tick_price))
                            else:
                                ui.update_account(balance, float(price_to_show))
                        except Exception:
                            try:
                                ui.update_account(balance, price_val if price_val is not None else (self.price if hasattr(self, 'price') else 0.0))
                            except Exception:
                                pass
                        # Unificar posiciones en una lista para la UI
                        all_positions = positions.get("BUY", []) + positions.get("SELL", [])
                        ui.update_positions(all_positions)
                        # Actualizar panel de gestión de capital
                        ui.update_capital(
                            balance_total=self.balance_total,
                            balance_available=self.balance,
                            balance_deposit=self.balance_deposit,
                            balance_pnl=self.balance_profitloss,
                            capital_pct=self.capital_available_pct,
                            num_buy=len(positions.get("BUY", [])),
                            num_sell=len(positions.get("SELL", [])),
                            max_positions=self.max_total_positions
                        )
                        # Enviar indicadores calculados (toda la fila latest_row) al UI
                        try:
                            # latest_row puede ser un Series o dict-like
                            lr = latest_row.copy() if hasattr(latest_row, 'copy') else dict(latest_row)
                            # Excluir columnas base de precios para mostrar solo indicadores
                            base_cols = set(['Open', 'Close', 'High', 'Low', 'Volume'])
                            indicators = {}
                            for k, v in (lr.items() if isinstance(lr, dict) else lr.items()):
                                if k in base_cols:
                                    continue
                                # normalizar valores sencillos
                                try:
                                    if isinstance(v, (int, float, np.floating, np.integer)):
                                        indicators[k] = float(v)
                                    else:
                                        indicators[k] = v
                                except Exception:
                                    indicators[k] = str(v)
                            ui.update_indicators(indicators)
                        except Exception:
                            try:
                                # Fallback: intentar sacar de latest_row como dict
                                ui.update_indicators({})
                            except Exception:
                                pass
                    except Exception as e:
                        ui.add_log(f"❌ Error al actualizar saldo y posiciones: {e}")
                        time.sleep(interval)
                        continue

                    # 🔥 PASO: Obtener velas 1M frescas desde API antes de procesar
                    fresh_df_with_indicators = None
                    try:
                        ui.add_log("🕯️ Obteniendo LTF (MINUTE) fresco desde API...")
                        fresh_candles = self.capital_ops.get_1m_candles("ETHUSD", limit=40)
                        
                        if fresh_candles and len(fresh_candles) > 0:
                            from DataEth import calculate_ltf_indicators
                            
                            fresh_df = pd.DataFrame(fresh_candles)
                            fresh_df['timestamp'] = pd.to_datetime(fresh_df['timestamp'])
                            fresh_df.set_index('timestamp', inplace=True)
                            fresh_df = fresh_df.sort_index()
                            
                            # Calcular indicadores
                            fresh_df_with_indicators = calculate_ltf_indicators(fresh_df)
                            
                            if not fresh_df_with_indicators.empty:
                                # Actualizar latest_row con última vela fresca
                                latest_series = fresh_df_with_indicators.iloc[-1]
                                latest_row = latest_series.to_dict()
                                latest_row['Datetime'] = fresh_df_with_indicators.index[-1]
                                ltf_range = f"{fresh_df_with_indicators.index[0].strftime('%H:%M')} → {fresh_df_with_indicators.index[-1].strftime('%H:%M')}"
                                ui.add_log(f"✅ LTF (MINUTE) API: {len(fresh_df_with_indicators)} velas ({ltf_range}) | Close: ${latest_row.get('Close', 0):.2f} | RSI: {latest_row.get('RSI', 'N/A')}")
                            else:
                                ui.add_log("⚠️ Indicadores LTF no calculados, usando datos estáticos")
                        else:
                            ui.add_log("⚠️ No se obtuvieron velas de la API, usando datos estáticos")
                    except Exception as e:
                        ui.add_log(f"⚠️ Error obteniendo velas API: {e}, usando datos estáticos")

                    try:
                        bot_state = getattr(self, 'bot_state', None)
                        self.process_data(
                            row=latest_row, 
                            positions=positions, 
                            balance=balance, 
                            bot_state=bot_state, 
                            historical_data=data_frame,
                            data=fresh_df_with_indicators if fresh_df_with_indicators is not None else None,
                            row_timestamp=latest_timestamp
                        )
                        # Actualizar señal y razón en la UI
                        if bot_state:
                            ui.update_signal(getattr(bot_state, 'signal', 'HOLD ⚠️'), getattr(bot_state, 'reason', ''))
                    except Exception as e:
                        ui.add_log(f"❌ Error al procesar datos: {e}")

                    # Actualizar momentum si tienes datos (ejemplo)
                    # ui.update_momentum({"velocity": 0.01, "acceleration": 0.001, "momentum_score": 50, "direction": "BULLISH", "tick_count": 10, "price": self.price})

                    ui.add_log("✅ Fila procesada exitosamente.")
                    live.update(ui.render())
                    time.sleep(interval)
            except KeyboardInterrupt:
                ui.add_log("🛑 Bucle de trading detenido manualmente por el usuario.")
                ui.add_log("👋 Cerrando bot EthBoy...")
                # Stop background light client if running
                try:
                    if hasattr(self, 'light_client') and self.light_client:
                        try:
                            self.light_client.stop()
                        except Exception:
                            pass
                except Exception:
                    pass
                # Restaurar print original si fue sobreescrito y remover logging handler
                try:
                    if hasattr(self, '_orig_print'):
                        import builtins
                        builtins.print = self._orig_print
                except Exception:
                    pass
                try:
                    if hasattr(self, '_ui_log_handler') and self._ui_log_handler is not None:
                        import logging
                        try:
                            logging.getLogger().removeHandler(self._ui_log_handler)
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    if hasattr(ui, '_live'):
                        try:
                            delattr(ui, '_live')
                        except Exception:
                            pass
                except Exception:
                    pass
                live.update(ui.render())
                sys.exit(0)
            except Exception as e:
                ui.add_log(f"❌ Error en el bucle principal: {e}")
                # Ensure background client is stopped
                try:
                    if hasattr(self, 'light_client') and self.light_client:
                        try:
                            self.light_client.stop()
                        except Exception:
                            pass
                except Exception:
                    pass
                # Restaurar print original si fue sobreescrito y remover logging handler
                try:
                    if hasattr(self, '_orig_print'):
                        import builtins
                        builtins.print = self._orig_print
                except Exception:
                    pass
                try:
                    if hasattr(self, '_ui_log_handler') and self._ui_log_handler is not None:
                        import logging
                        try:
                            logging.getLogger().removeHandler(self._ui_log_handler)
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    if hasattr(ui, '_live'):
                        try:
                            delattr(ui, '_live')
                        except Exception:
                            pass
                except Exception:
                    pass
                live.update(ui.render())
                sys.exit(1)
        """
        Loop principal del bot que ejecuta el ciclo de trading.
        
        FUNCIONAMIENTO:
        1. Actualiza datos históricos (HTF/LTF) mediante DataEth.py subprocess
        2. Obtiene precio tick actual y balance/posiciones
        3. Ejecuta análisis de estrategia con datos actualizados
        4. Toma decisiones de apertura/cierre de posiciones
        5. Aplica validaciones (cooldown, límites, balance)
        
        PARÁMETROS:
        - interval: Tiempo en segundos entre ciclos completos (defecto: 30s = 0.5 minuto)
        
        IMPORTANTE: Este loop se ejecuta independiente del precio tick polling en CLILive.
        CLILive mode actualiza precios cada ~1s, mientras este loop ejecuta estrategia
        completa cada 30s o cuando se detecta nueva vela 1M cerrada.
        """
        ui = getattr(self, 'ui', None)
        if ui:
            ui.add_log("[INFO] Iniciando bucle principal de TradingOperator (intervalo: 30s).")
        else:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log("[INFO] Iniciando bucle principal de TradingOperator (intervalo: 30s).")
            # else: print("[INFO] Iniciando bucle principal de TradingOperator (intervalo: 30s).")

        try:
            # ═══════════════════════════════════════════════════════════
            # CARGA INICIAL: Cargar HTF y LTF al inicio
            # ═══════════════════════════════════════════════════════════
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log("[INFO] 📊 Cargando datos históricos (HTF + LTF)...")
            
            try:
                # 🔹 CORRECCIÓN BUG HTF/LTF: Actualizar datos primero
                self.update_historical_data(force=True)
                
                # 🔹 Cargar ambos HTF y LTF desde DataLoader
                loader = DataLoader()
                _dl_cache['htf'], _dl_cache['ltf'] = loader.load_historical_data()
                _dl_cache['time'] = time.time()
                historical_data_htf, data_frame_ltf = _dl_cache['htf'], _dl_cache['ltf']
                
                # Validar que ambos se cargaron correctamente
                if historical_data_htf is None or historical_data_htf.empty:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log("[ERROR] ❌ No se pudo cargar HTF inicial. Abortando.")
                    return
                
                if data_frame_ltf is None or data_frame_ltf.empty:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log("[ERROR] ❌ No se pudo cargar LTF inicial. Abortando.")
                    return
                
                # Guardar HTF en self.historical_data para el thread updater
                self.historical_data = historical_data_htf
                
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[INFO] ✅ HTF cargado: {len(historical_data_htf)} velas (HOUR)")
                    ui.add_log(f"[INFO] ✅ LTF cargado: {len(data_frame_ltf)} velas (MINUTE)")
            except Exception as e:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[ERROR] ❌ Error cargando datos iniciales: {e}")
                return
            
            # ═══════════════════════════════════════════════════════════
            # THREAD ACTUALIZADOR: Actualizar HTF cada 2h en background
            # ═══════════════════════════════════════════════════════════
            self.start_htf_updater()
            
            while True:
                # ═══════════════════════════════════════════════════════════
                # LOOP PRINCIPAL: Procesar señales usando LTF (MINUTE data)
                # ═══════════════════════════════════════════════════════════
                # HTF se actualiza automáticamente cada 2h en thread separado.
                # Aquí procesamos LTF para microtendencias y pasamos HTF como contexto.

                # 🔹 RECARGAR LTF (cacheado 60s)
                try:
                    if time.time() - _dl_cache['time'] > 60:
                        loader = DataLoader()
                        _dl_cache['htf'], _dl_cache['ltf'] = loader.load_historical_data()
                        _dl_cache['time'] = time.time()
                    data_frame_ltf = _dl_cache['ltf']
                    
                    if data_frame_ltf is None or data_frame_ltf.empty:
                        ui = getattr(self, 'ui', None)
                        if ui:
                            ui.add_log("[WARNING] ⚠️ LTF vacío en recarga. Esperando...")
                        time.sleep(interval)
                        continue
                except Exception as e:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"[ERROR] ❌ Error recargando LTF: {e}")
                    time.sleep(interval)
                    continue

                # Validar el índice de tiempo de LTF
                if not isinstance(data_frame_ltf.index, pd.DatetimeIndex):
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log("[WARNING] ⚠️ Índice LTF no es DatetimeIndex. Convirtiendo...")
                    data_frame_ltf.index = pd.to_datetime(data_frame_ltf.index, errors='coerce')

                if data_frame_ltf.index.tz is None:
                    data_frame_ltf.index = data_frame_ltf.index.tz_localize("UTC")

                if data_frame_ltf.index.hasnans:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log("[WARNING] ⚠️ Valores NaT en índice LTF. Eliminando...")
                    data_frame_ltf = data_frame_ltf[~data_frame_ltf.index.isna()]

                if data_frame_ltf.empty:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log("[WARNING] ⚠️ LTF vacío después de limpieza. Esperando...")
                    time.sleep(interval)
                    continue

                # 🔹 Procesar la última fila de LTF (MINUTE data)
                latest_row = self.get_latest_data(data_frame_ltf)
                latest_timestamp = data_frame_ltf.index[-1]

                if not isinstance(latest_timestamp, pd.Timestamp):
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"[ERROR] ❌ Timestamp LTF inválido: {latest_timestamp}")
                    time.sleep(interval)
                    continue

                if latest_timestamp.tz is None:
                    latest_timestamp = latest_timestamp.tz_localize("UTC")

                try:
                    balance, positions = self.update_balance_and_positions()
                except Exception as e:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"[ERROR] ❌ Error al actualizar saldo y posiciones: {e}")
                    time.sleep(interval)
                    continue

                try:
                    bot_state = getattr(self, 'bot_state', None)
                    # 🌍 MARKET CONTEXT: Calcular BB/EMA200/Breakout cada ciclo
                    try:
                        tick_price = float(latest_row.get("Close", 0) if isinstance(latest_row, dict) else latest_row["Close"])
                        self.compute_and_save_market_context(self.historical_data, tick_price)
                    except Exception as e:
                        logging.warning(f"[WARNING] market_context computation failed: {e}")
                    # 🔹 CORRECCIÓN BUG: Pasar HTF como historical_data y LTF como data
                    # process_data() recibirá:
                    # - row: última fila LTF (MINUTE)
                    # - data: DataFrame LTF completo (MINUTE) con indicadores
                    # - historical_data: HTF completo (HOUR) para contexto
                    self.process_data(
                        row=latest_row, 
                        positions=positions, 
                        balance=balance, 
                        bot_state=bot_state, 
                        row_timestamp=latest_timestamp,
                        data=data_frame_ltf,  # LTF completo (MINUTE)
                        historical_data=self.historical_data  # HTF (HOUR)
                    )
                except Exception as e:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"[ERROR] ❌ Error al procesar datos: {e}")

                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log("[INFO] ✅ Fila LTF procesada exitosamente.")
                self.print_log()

                time.sleep(interval)

        except KeyboardInterrupt:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log("[INFO] 🛑 Bucle de trading detenido manualmente por el usuario.")
                ui.add_log("[INFO] 👋 Cerrando bot EthBoy...")
            # Restaurar print original si fue sobreescrito y remover logging handler
            try:
                if hasattr(self, '_orig_print'):
                    import builtins
                    builtins.print = self._orig_print
            except Exception:
                pass
            try:
                if hasattr(self, '_ui_log_handler') and self._ui_log_handler is not None:
                    import logging
                    try:
                        logging.getLogger().removeHandler(self._ui_log_handler)
                    except Exception:
                        pass
            except Exception:
                pass
            sys.exit(0)
        except Exception as e:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[ERROR] ❌ Error en el bucle principal: {e}")
            # Restaurar print original si fue sobreescrito y remover logging handler
            try:
                if hasattr(self, '_orig_print'):
                    import builtins
                    builtins.print = self._orig_print
            except Exception:
                pass
            try:
                if hasattr(self, '_ui_log_handler') and self._ui_log_handler is not None:
                    import logging
                    try:
                        logging.getLogger().removeHandler(self._ui_log_handler)
                    except Exception:
                        pass
            except Exception:
                pass
            sys.exit(1)

    def get_latest_data(self, data_frame):
        if data_frame.empty:
            raise ValueError("[ERROR] Los datos están vacíos.")
        ui = getattr(self, 'ui', None)
        if ui:
            ui.add_log(f"[INFO] Última fila cargada: {data_frame.iloc[-1].to_dict()}")
        return data_frame.iloc[-1]
 

 
    def update_balance_and_positions(self):
        """Actualiza el balance y las posiciones abiertas usando la cuenta activa configurada previamente."""
        try:
            account_info = self.capital_ops.get_account_summary()
            if not account_info or "accountId" not in account_info:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log("[ERROR] ❌ Información de cuenta inválida.")
                raise ValueError("Información de cuenta inválida o incompleta")
            
            # Usar la cuenta activa tal como viene de get_account_summary()
            self.account_name = account_info.get("accountName", "Desconocida")
            self.balance = account_info.get("available", 0)
            self.balance_total = account_info.get("balance", 0)  # Balance total (equity)
            self.balance_deposit = account_info.get("deposit", 0)  # Depósito original
            self.balance_profitloss = account_info.get("profitLoss", 0)  # P&L
            
            # Calcular porcentaje de capital disponible
            if self.balance_total > 0:
                self.capital_available_pct = (self.balance / self.balance_total) * 100
            else:
                self.capital_available_pct = 0
            
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[INFO] ✅ Balance actualizado: Disponible ${self.balance:.2f} de ${self.balance_total:.2f} ({self.capital_available_pct:.1f}%) | Cuenta: {self.account_name}")
            
            # Obtener posiciones abiertas (respuesta raw de la API)
            positions = self.capital_ops.get_open_positions()
            # Guardar la respuesta original cruda para diagnósticos y detección de legacy
            try:
                self.last_raw_positions = positions
            except Exception:
                self.last_raw_positions = None

            # Normalizar formato esperado: un diccionario con claves "BUY" y "SELL"
            if isinstance(positions, dict) and "BUY" in positions and "SELL" in positions:
                pass
            elif isinstance(positions, tuple) and len(positions) == 2:
                positions = {"BUY": positions[0], "SELL": positions[1]}
            else:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[ERROR] ❌ Formato inesperado en posiciones abiertas. Contenido recibido: {positions}")
                else:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"[ERROR] ❌ Formato inesperado en posiciones abiertas. Contenido recibido: {positions}")
                raise ValueError(f"Formato inesperado en posiciones: {positions}")

            # Conteos raw (incluye legacy) y conteos activos (excluye legacy)
            raw_buy = len(positions.get("BUY", []))
            raw_sell = len(positions.get("SELL", []))
            # Mantener la forma original de la API: cada item es un wrapper con clave 'position'
            buy_active_wrapped = [p for p in positions.get("BUY", []) if not self.is_legacy(p.get("position", p))]
            sell_active_wrapped = [p for p in positions.get("SELL", []) if not self.is_legacy(p.get("position", p))]
            active_buy = len(buy_active_wrapped)
            active_sell = len(sell_active_wrapped)

            # Log claro que muestra ambos conteos para evitar confusión
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[INFO] ✅ Posiciones para {self.account_id}: raw BUY={raw_buy}, raw SELL={raw_sell} | activas (sin legacy) BUY={active_buy}, SELL={active_sell}")
            
            # 🔍 DIAGNÓSTICO: Log en consola también para ScanMode
            logging.info(f"[UPDATE_POSITIONS] 📊 Account {self.account_id}: raw BUY={raw_buy}, raw SELL={raw_sell} | activas BUY={active_buy}, SELL={active_sell}")
            
            # 🔍 DIAGNÓSTICO: Si hay discrepancia entre raw y activas, mostrar detalles de legacy
            if raw_buy != active_buy or raw_sell != active_sell:
                legacy_buy = [p.get("position", {}).get("dealId", "?") for p in positions.get("BUY", []) if self.is_legacy(p.get("position", p))]
                legacy_sell = [p.get("position", {}).get("dealId", "?") for p in positions.get("SELL", []) if self.is_legacy(p.get("position", p))]
                if legacy_buy:
                    logging.info(f"[UPDATE_POSITIONS] 🗂️ Legacy BUY detectadas: {legacy_buy}")
                if legacy_sell:
                    logging.info(f"[UPDATE_POSITIONS] 🗂️ Legacy SELL detectadas: {legacy_sell}")
            
            # 💾 EXPORTAR DATOS PARA CAPITAL PANEL
            try:
                import json
                capital_data = {
                    "balance_total": self.balance_total,
                    "balance_available": self.balance,
                    "balance_deposit": self.balance_deposit,
                    "balance_pnl": self.balance_profitloss,
                    "capital_pct": self.capital_available_pct,
                    "num_buy": active_buy,
                    "num_sell": active_sell,
                    "max_positions": self.max_total_positions,
                    "timestamp": datetime.now().isoformat()
                }
                _cap_state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capital_state.json")
                with open(_cap_state_path, "w") as f:
                    json.dump(capital_data, f, indent=2)
            except Exception as e:
                logging.debug(f"[DEBUG] No se pudo exportar capital_state.json: {e}")

            # Escribir last_seen_positions.json para que Evaluador pueda detectar cierres
            try:
                _last_seen_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_seen_positions.json")
                _all_wrapped = buy_active_wrapped + sell_active_wrapped
                _tracking = {}
                for _w in _all_wrapped:
                    _pos = _w.get('position', _w)
                    _mkt = _w.get('market', {})
                    _did = _pos.get('dealId', '')
                    if not _did:
                        continue
                    _created = _pos.get('createdDateUTC') or _pos.get('createdDate')
                    _hours_open = 0.0
                    if _created:
                        try:
                            _cs = _created.replace('Z', '+00:00') if isinstance(_created, str) else str(_created)
                            _dt = datetime.fromisoformat(_cs)
                            if _dt.tzinfo is None:
                                from datetime import timezone as _tz
                                _dt = _dt.replace(tzinfo=_tz.utc)
                            _hours_open = (datetime.now(timezone.utc) - _dt).total_seconds() / 3600
                        except Exception:
                            pass
                    _tracking[_did] = {
                        'dealId': _did,
                        'epic': _mkt.get('epic', 'ETHUSD'),
                        'direction': _pos.get('direction', 'N/A'),
                        'size': _pos.get('size', 'N/A'),
                        'entry_price': _pos.get('level', 'N/A'),
                        'last_upl': _pos.get('upl', 0),
                        'last_upl_pct': None,
                        'max_profit_pct': 0,
                        'hours_open': _hours_open,
                        'last_seen_time': datetime.now(timezone.utc).isoformat(),
                        'last_indicators': {}
                    }
                with open(_last_seen_path, 'w') as _f:
                    json.dump(_tracking, _f, indent=2)
            except Exception as _e:
                logging.debug(f"[DEBUG] No se pudo escribir last_seen_positions.json: {_e}")

            return self.balance, {"BUY": buy_active_wrapped, "SELL": sell_active_wrapped}

        except Exception as e:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[ERROR] ❌ Error crítico al actualizar saldo y posiciones: {e}")
            else:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[ERROR] ❌ Error crítico al actualizar saldo y posiciones: {e}")
            # NO devolver valores vacíos falsos. Propagar el error para detener el ciclo actual.
            raise e

    def get_active_positions_wrapped(self, positions):
        """Devuelve un dict {'BUY': [...], 'SELL': [...]} con los wrappers originales (o creados)
        filtrando las posiciones legacy (no cuentan para límites). Acepta tanto wrappers API
        como posiciones directas.
        """
        result = {"BUY": [], "SELL": []}
        if not isinstance(positions, dict):
            return result

        for side in ("BUY", "SELL"):
            out = []
            for p in positions.get(side, []):
                if isinstance(p, dict) and 'position' in p and isinstance(p['position'], dict):
                    pos = p['position']
                    wrapped = True
                else:
                    pos = p
                    wrapped = False
                try:
                    if not self.is_legacy(pos):
                        out.append(p if wrapped else {"position": pos})
                except Exception:
                    # En caso de duda, excluir la posición para evitar bloquear operaciones por error
                    continue
            result[side] = out
        return result

    def normalize_raw_positions(self, raw):
        """Normaliza la respuesta raw de la API a un dict {'BUY': [...], 'SELL': [...]} donde
        cada item es un wrapper {'position': {...}, 'market': {...}}.
        Acepta tanto la forma ya procesada como la forma original {'positions': [...]}.
        """
        if not raw:
            return {"BUY": [], "SELL": []}

        # Si ya está en formato {'BUY':..., 'SELL':...}
        if isinstance(raw, dict) and 'BUY' in raw and 'SELL' in raw:
            return raw

        # Si viene en formato {'positions': [...]} (raw API)
        if isinstance(raw, dict) and 'positions' in raw and isinstance(raw['positions'], list):
            all_positions = raw['positions']
            buy_positions = [pos for pos in all_positions if pos.get('position', {}).get('direction', '').upper() == 'BUY']
            sell_positions = [pos for pos in all_positions if pos.get('position', {}).get('direction', '').upper() == 'SELL']
            return {"BUY": buy_positions, "SELL": sell_positions}

        # Si es una lista directa de wrappers
        if isinstance(raw, list):
            buy_positions = [pos for pos in raw if pos.get('position', {}).get('direction', '').upper() == 'BUY']
            sell_positions = [pos for pos in raw if pos.get('position', {}).get('direction', '').upper() == 'SELL']
            return {"BUY": buy_positions, "SELL": sell_positions}

        return {"BUY": [], "SELL": []}

    def get_legacy_positions_wrapped(self, raw_or_positions):
        """Devuelve wrappers legacy (con clave 'position') detectadas en la respuesta raw.
        """
        normalized = self.normalize_raw_positions(raw_or_positions)
        legacy = {"BUY": [], "SELL": []}
        for side in ("BUY", "SELL"):
            out = []
            for p in normalized.get(side, []):
                pos = p.get('position') if isinstance(p, dict) else p
                try:
                    if self.is_legacy(pos):
                        out.append(p if isinstance(p, dict) else {"position": pos})
                except Exception:
                    continue
            legacy[side] = out
        return legacy


    def compute_and_save_market_context(self, historical_data, current_price):
        """
        Calcula BB(20, 2σ), EMA200/50/20, ratio de volumen y detecta el estado del mercado.
        Usa columnas pre-calculadas del HTF cuando están disponibles (EMA_200, ADX, etc.).
        Mínimo 20 filas para BB(20). Escribe market_context.json para todos los módulos.
        Estados: squeeze | breakout_up | breakout_down | ranging | choppy
        """
        import numpy as np
        ctx = {
            "state": "ranging",
            "bb_lower": None,
            "bb_upper": None,
            "ema200": None,
            "ema50": None,
            "ema20": None,
            "price_vs_ema200_pct": None,
            "squeeze_pct": None,
            "vol_ratio": None,
            "adx": None,
            "di_plus": None,
            "di_minus": None,
            "bias": None,
            "price": current_price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            if historical_data is None or historical_data.empty or len(historical_data) < 20:
                self._save_market_context(ctx)
                return ctx

            close = historical_data["Close"].astype(float)
            last_row = historical_data.iloc[-1]
            n_rows = len(historical_data)

            # BB(20, 2σ) — solo necesita 20 filas
            bb_mid = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            bb_upper = (bb_mid + 2 * bb_std).iloc[-1]
            bb_lower = (bb_mid - 2 * bb_std).iloc[-1]
            bb_width = bb_upper - bb_lower

            # BB width histórica para squeeze (usa lo disponible, mín 20)
            bb_widths = (bb_mid + 2 * bb_std) - (bb_mid - 2 * bb_std)
            _sq_window = min(100, n_rows)
            bb_mean_width = bb_widths.tail(_sq_window).mean()
            squeeze_pct = round((bb_width / bb_mean_width) * 100, 1) if bb_mean_width > 0 else 100

            # EMAs — preferir columnas pre-calculadas del HTF
            ema200 = float(last_row["EMA_200"]) if "EMA_200" in historical_data.columns else close.ewm(span=200, adjust=False).mean().iloc[-1]
            ema50 = float(last_row["EMA_50"]) if "EMA_50" in historical_data.columns else close.ewm(span=50, adjust=False).mean().iloc[-1]
            ema20 = float(last_row["EMA_20"]) if "EMA_20" in historical_data.columns else close.ewm(span=20, adjust=False).mean().iloc[-1]

            price_vs_ema200 = round(((current_price - ema200) / ema200) * 100, 2) if ema200 > 0 else 0

            # Volume ratio — preferir pre-calculado
            if "Volume_Ratio" in historical_data.columns:
                vol_ratio = round(float(last_row["Volume_Ratio"]), 2)
            elif "Volume" in historical_data.columns:
                vol = historical_data["Volume"].astype(float)
                vol_recent = vol.tail(3).mean()
                vol_avg = vol.tail(min(30, n_rows)).mean()
                vol_ratio = round(vol_recent / vol_avg, 2) if vol_avg > 0 else 1.0
            else:
                vol_ratio = 1.0

            # ADX — preferir pre-calculado
            adx_val = None
            if "ADX" in historical_data.columns:
                _adx_raw = last_row.get("ADX", None)
                if _adx_raw is not None and not (isinstance(_adx_raw, float) and np.isnan(_adx_raw)):
                    adx_val = float(_adx_raw)

            # DI+/DI- — buscar varias posibles columnas, o calcular si hay suficientes filas
            di_plus = None
            di_minus = None
            for col_p, col_m in [("DI+", "DI-"), ("ADX_DI+", "ADX_DI-"), ("DI_plus", "DI_minus")]:
                if col_p in historical_data.columns and col_m in historical_data.columns:
                    _dp = last_row.get(col_p, None)
                    _dm = last_row.get(col_m, None)
                    if _dp is not None and _dm is not None:
                        di_plus = float(_dp)
                        di_minus = float(_dm)
                    break
            # Si no hay DI pre-calculado, intentar calcularlo con ta
            if di_plus is None and n_rows >= 14:
                try:
                    import ta
                    _adx_ind = ta.trend.ADXIndicator(
                        high=historical_data["High"].astype(float),
                        low=historical_data["Low"].astype(float),
                        close=close,
                        window=14
                    )
                    di_plus = float(_adx_ind.adx_pos().iloc[-1])
                    di_minus = float(_adx_ind.adx_neg().iloc[-1])
                    if adx_val is None:
                        adx_val = float(_adx_ind.adx().iloc[-1])
                except Exception:
                    pass

            # Market_Regime pre-calculado (fallback para state)
            precomputed_regime = str(last_row.get("Market_Regime", "")).upper() if "Market_Regime" in historical_data.columns else ""

            # Detectar estado
            state = "ranging"
            bias = None
            if current_price > bb_upper:
                state = "breakout_up"
            elif current_price < bb_lower:
                state = "breakout_down"
            elif squeeze_pct < 50:
                state = "squeeze"
            elif adx_val is not None and adx_val < 20:
                state = "choppy"
            elif precomputed_regime == "CHOPPY":
                state = "choppy"
            else:
                state = "ranging"

            # Bias basado en ADX + DI
            if adx_val is not None and adx_val >= 25:
                if di_plus is not None and di_minus is not None:
                    if di_plus > di_minus:
                        bias = "BULLISH"
                    elif di_minus > di_plus:
                        bias = "BEARISH"
            elif adx_val is not None and adx_val < 20:
                bias = "CHOPPY"

            ctx.update({
                "state": state,
                "bb_lower": round(float(bb_lower), 2),
                "bb_upper": round(float(bb_upper), 2),
                "ema200": round(float(ema200), 2),
                "ema50": round(float(ema50), 2),
                "ema20": round(float(ema20), 2),
                "price_vs_ema200_pct": price_vs_ema200,
                "squeeze_pct": squeeze_pct,
                "vol_ratio": vol_ratio,
                "adx": round(adx_val, 1) if adx_val else None,
                "di_plus": round(di_plus, 1) if di_plus else None,
                "di_minus": round(di_minus, 1) if di_minus else None,
                "bias": bias,
            })

            _adx_str = f"ADX {adx_val:.1f}" if adx_val else "ADX ?"
            _di_str = f"DI+ {di_plus:.1f} / DI- {di_minus:.1f}" if di_plus is not None else ""
            _bias_str = f"Bias: {bias}" if bias else ""
            logging.info(f"[MCTX] {state.upper()} | BB ${bb_lower:.0f}-${bb_upper:.0f} | EMA200 ${ema200:.0f} ({price_vs_ema200:+.1f}%) | {_adx_str} {_di_str} | Squeeze {squeeze_pct}% | {_bias_str}")

        except Exception as e:
            logging.warning(f"[WARNING] compute_market_context error: {e}")

        self._save_market_context(ctx)
        return ctx

    def _save_market_context(self, ctx):
        """Persiste market_context.json de forma atómica."""
        ctx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_context.json")
        tmp_path = ctx_path + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(ctx, f, indent=2)
            os.replace(tmp_path, ctx_path)
        except Exception as e:
            logging.warning(f"[WARNING] No se pudo guardar market_context.json: {e}")
        

    def process_data(self, row, positions, balance, bot_state: BotState = None, historical_data=None, data=None, row_timestamp=None):
        """
        Procesa los datos actuales usando la estrategia, validando las posiciones, registrando la tendencia 
        y abriendo nuevas posiciones según se reciba una señal de BUY o SELL, siempre respetando los máximos permitidos.
        """
        import pandas as pd  # Import al inicio de la función
        
        try:
            # 🔹 VERIFICACIÓN DE ÓRDENES PENDIENTES (LOCK LOCAL)
            if self.pending_order:
                elapsed = time.time() - self.pending_order["timestamp"]
                if elapsed < 30:  # Esperar hasta 30 segundos
                    logging.info(f"[INFO] ⏳ Esperando confirmación de orden {self.pending_order['type']} enviada hace {elapsed:.1f}s...")
                    # Verificar si la orden ya se reflejó en las posiciones actuales
                    pending_type = self.pending_order['type']
                    if pending_type in positions and len(positions[pending_type]) > 0:
                         # Comprobación simple: Si hay una nueva posición del tipo pendiente, asumimos éxito y limpiamos
                         # (Para mayor robustez se podría comparar IDs o timestamps más precisos)
                         logging.info(f"[INFO] ✅ Orden {pending_type} confirmada en posiciones activas. Limpiando bloqueo local.")
                         self.pending_order = None
                    else:
                        return  # Salir del ciclo y seguir esperando
                else:
                    logging.warning(f"[WARNING] ⚠️ Orden pendiente {self.pending_order['type']} expirada ({elapsed:.1f}s). Asumiendo fallo o timeout API. Desbloqueando.")
                    self.pending_order = None

            if row is None:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log("[ERROR] ❌ La fila de datos es None.")
                else:
                    logging.error("[ERROR] ❌ La fila de datos es None.")
                return

            # Convertir la fila a diccionario si es necesario
            if isinstance(row, pd.Series):
                # 🔹 CORRECCIÓN: usar el timestamp pasado como parámetro en lugar de row.name
                dt = row_timestamp if row_timestamp is not None else row.name  
                row = row.to_dict()
                row["Datetime"] = self.format_datetime(dt)
            elif not isinstance(row, dict):
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log("[ERROR] ❌ La fila de datos no es válida.")
                else:
                    logging.error("[ERROR] ❌ La fila de datos no es válida.")
                return

            # Verificar si faltan características esenciales en la fila
            missing_features = [f for f in self.features if f not in row]
            if missing_features:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[ERROR] ❌ Faltan estas características en `row`: {missing_features}")
                else:
                    logging.error(f"[ERROR] ❌ Faltan estas características en `row`: {missing_features}")
                return

            # 🔥 VALIDACIÓN: Si data es None o vacío, intentar crear un DataFrame mínimo desde row
            if data is None or (hasattr(data, 'empty') and data.empty):
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log("[WARNING] ⚠️ data vacío, creando DataFrame desde row actual...")
                else:
                    logging.warning("[WARNING] ⚠️ data vacío, creando DataFrame desde row actual...")
                
                # Crear DataFrame con la fila actual
                data = pd.DataFrame([row])
                if 'Datetime' in row:
                    data.index = pd.to_datetime([row['Datetime']])
                
                if data.empty:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log("[ERROR] ❌ No se pudo crear DataFrame LTF. Abortando.")
                    else:
                        logging.error("[ERROR] ❌ No se pudo crear DataFrame LTF. Abortando.")
                    return
            
            # Si historical_data es None o vacío, intentar cargar solo HTF (no LTF)
            if historical_data is None or (hasattr(historical_data, 'empty') and historical_data.empty):
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log("[WARNING] ⚠️ Cargando HTF desde archivo...")
                else:
                    logging.warning("[WARNING] ⚠️ Cargando HTF desde archivo...")
                
                if time.time() - _dl_cache['time'] > 60:
                    loader = DataLoader()
                    _dl_cache['htf'], _dl_cache['ltf'] = loader.load_historical_data()
                    _dl_cache['time'] = time.time()
                historical_data = _dl_cache['htf']
                
                if historical_data is None or (hasattr(historical_data, 'empty') and historical_data.empty):
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log("[ERROR] ❌ No se pudo cargar HTF. Abortando.")
                    else:
                        logging.error("[ERROR] ❌ No se pudo cargar HTF. Abortando.")
                    return

            # ─── SNAPSHOT DE INDICADORES (disponible para todos los log_entry del ciclo) ───────
            def _sf(v):
                try: return float(v)
                except Exception: return None
            _ind = {
                "L_Close":    _sf(row.get("Close")),
                "L_RSI":      _sf(row.get("RSI")),
                "L_RSI_7":    _sf(row.get("RSI_7")),
                "L_EMA_3":    _sf(row.get("EMA_3")),
                "L_EMA_9":    _sf(row.get("EMA_9")),
                "L_EMA_20":   _sf(row.get("EMA_20")),
                "L_EMA_50":   _sf(row.get("EMA_50")),
                "L_MACD":     _sf(row.get("MACD")),
                "L_MACD_Hist":_sf(row.get("MACD_Histogram")),
                "L_ADX":      _sf(row.get("ADX")),
                "L_ATR":      _sf(row.get("ATR")),
                "L_ATR_Pct": _sf(row.get("ATR_Pct")),
                "L_Volume":   _sf(row.get("Volume")),
                "L_STOCH":    _sf(row.get("STOCH")),
                "L_BB_width": _sf(row.get("BB_width")),
                "L_OBV_Trend": int(row.get("OBV_Trend", 0)) if row.get("OBV_Trend") is not None else None,
                "L_Market_Regime": str(row.get("Market_Regime", "")),
            }
            if historical_data is not None and not historical_data.empty:
                h = historical_data.iloc[-1]
                _ind.update({
                    "H_Close":    _sf(h.get("Close")),
                    "H_RSI":      _sf(h.get("RSI")),
                    "H_RSI_7":    _sf(h.get("RSI_7")),
                    "H_EMA_20":   _sf(h.get("EMA_20")),
                    "H_EMA_50":   _sf(h.get("EMA_50")),
                    "H_EMA_200":  _sf(h.get("EMA_200")),
                    "H_MACD":     _sf(h.get("MACD")),
                    "H_MACD_Hist":_sf(h.get("MACD_Histogram")),
                    "H_ADX":      _sf(h.get("ADX")),
                    "H_ATR":      _sf(h.get("ATR")),
                    "H_ATR_Pct":  _sf(h.get("ATR_Pct")),
                    "H_STOCH":    _sf(h.get("STOCH")),
                    "H_Volume":   _sf(h.get("Volume")),
                    "H_OBV_Trend": int(h.get("OBV_Trend", 0)) if h.get("OBV_Trend") is not None else None,
                    "H_Market_Regime": str(h.get("Market_Regime", "")),
                })
            self._current_indicators = _ind
            # ────────────────────────────────────────────────────────────────────────────────────

            # 🔹 PASO 1: Procesar posiciones y verificar límites PRIMERO
            # Solo se trabaja con una cuenta activa en EthBoy, por lo que no es necesario validar accountId en cada posición.
            if isinstance(positions, dict) and "BUY" in positions and "SELL" in positions:
                # Robustez: normalizar cada entrada recibida. Soportar ambos formatos:
                # - wrapper API: {"position": {...}, "market": {...}}
                # - posición directa: {...}
                def normalize(p):
                    if isinstance(p, dict) and 'position' in p and isinstance(p['position'], dict):
                        return p['position']
                    return p

                def is_valid_position(p):
                    pnorm = normalize(p)
                    return isinstance(pnorm, dict) and (pnorm.get('createdDate') or pnorm.get('created') or pnorm.get('open_time'))

                # Construir listas normalizadas para análisis (posiciones originales y sus wrappers)
                # Usar la respuesta raw guardada (si existe) y normalizarla para detectar legacy
                source_positions = self.normalize_raw_positions(getattr(self, 'last_raw_positions', None) or positions)
                buy_all_wrapped = [p for p in source_positions.get("BUY", []) if is_valid_position(p)]
                sell_all_wrapped = [p for p in source_positions.get("SELL", []) if is_valid_position(p)]
                # Extraer solo los dicts de 'position' para evaluar legacy/active
                buy_all = [normalize(p) for p in buy_all_wrapped]
                sell_all = [normalize(p) for p in sell_all_wrapped]
                buy_legacy = [p for p in buy_all if self.is_legacy(p)]
                buy_active = [p for p in buy_all if not self.is_legacy(p)]
                sell_legacy = [p for p in sell_all if self.is_legacy(p)]
                sell_active = [p for p in sell_all if not self.is_legacy(p)]
                # Para compatibilidad y consistencia forzamos el uso de wrappers activos
                # usando el helper centralizado que filtra legacy y preserva wrappers.
                active_wrapped = self.get_active_positions_wrapped(positions)
                buy_positions = active_wrapped.get("BUY", [])
                sell_positions = active_wrapped.get("SELL", [])
                # Mensajes claros sobre legacy
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[LEGACY-DEBUG SUMMARY] buy_all={len(buy_all)} buy_legacy={len(buy_legacy)} buy_active={len(buy_active)} | sell_all={len(sell_all)} sell_legacy={len(sell_legacy)} sell_active={len(sell_active)}")
                    if buy_legacy:
                        ui.add_log(f"[LEGACY-DEBUG] BUY legacy IDs: {[p.get('dealId') for p in buy_legacy]}")
                    if sell_legacy:
                        ui.add_log(f"[LEGACY-DEBUG] SELL legacy IDs: {[p.get('dealId') for p in sell_legacy]}")
                    if buy_legacy or sell_legacy:
                        ui.add_log(f"[LEGACY] BUY legacy detectadas: {len(buy_legacy)} | SELL legacy detectadas: {len(sell_legacy)} (no cuentan para límites)")
                        ui.add_log("[LEGACY] Operación legacy detectada: ajustando límites, solo las posiciones activas cuentan para el máximo de 1 BUY y 1 SELL.")
                    else:
                        ui.add_log("[LEGACY] No se detectaron posiciones legacy. Todas las posiciones son activas para el cálculo de límites.")
                else:
                    logging.info(f"[LEGACY-DEBUG SUMMARY] buy_all={len(buy_all)} buy_legacy={len(buy_legacy)} buy_active={len(buy_active)} | sell_all={len(sell_all)} sell_legacy={len(sell_legacy)} sell_active={len(sell_active)}")
                    if buy_legacy:
                        logging.info(f"[LEGACY-DEBUG] BUY legacy IDs: {[p.get('dealId') for p in buy_legacy]}")
                    if sell_legacy:
                        logging.info(f"[LEGACY-DEBUG] SELL legacy IDs: {[p.get('dealId') for p in sell_legacy]}")
                    if buy_legacy or sell_legacy:
                        logging.info(f"[LEGACY] BUY legacy detectadas: {len(buy_legacy)} | SELL legacy detectadas: {len(sell_legacy)} (no cuentan para límites)")
                        logging.info("[LEGACY] Operación legacy detectada: ajustando límites, solo las posiciones activas cuentan para el máximo de 1 BUY y 1 SELL.")
                    else:
                        logging.info("[LEGACY] No se detectaron posiciones legacy. Todas las posiciones son activas para el cálculo de límites.")
            else:
                logging.error(f"[ERROR] ❌ Formato inesperado en posiciones abiertas. Contenido recibido: {positions}")
                return
            # NOTA: El campo accountId no es necesario en cada posición, ya que la API solo devuelve posiciones de la cuenta activa.
            # Por eso, se elimina el warning sobre accountId faltante.

            num_buy_positions = len(buy_positions)
            num_sell_positions = len(sell_positions)
            total_positions = num_buy_positions + num_sell_positions
            max_buy_positions = self.capital_ops.max_buy_positions
            max_sell_positions = self.capital_ops.max_sell_positions

            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[INFO] 📊 Posiciones actuales: {total_positions}/{self.max_total_positions} total (BUY={num_buy_positions}/{max_buy_positions}, SELL={num_sell_positions}/{max_sell_positions})")
            else:
                logging.info(f"[INFO] 📊 Posiciones actuales: {total_positions}/{self.max_total_positions} total (BUY={num_buy_positions}/{max_buy_positions}, SELL={num_sell_positions}/{max_sell_positions})")

            # 🔹 BLOQUE 1: Verificar límite TOTAL
            if total_positions >= self.max_total_positions:
                logging.info(f"[INFO] 🔒 Limite TOTAL alcanzado ({total_positions}/{self.max_total_positions}). SKIP evaluación completa.")
                log_entry = {
                    "datetime": self.format_datetime(row["Datetime"]),
                    "current_price": float(row["Close"]),
                    "balance": float(self.balance),
                    "decision": "HOLD",
                    "reason": f"📊 Tengo {total_positions} posiciones, mi límite total es {self.max_total_positions}. HOLD ⏸️",
                    "trend": {"signal": "SKIP"}
                }
                self.log_process_data.append(log_entry)
                try:
                    self._persist_log_entry(log_entry)
                except Exception:
                    pass
                if bot_state is not None:
                    try:
                        bot_state.signal = log_entry.get('decision', 'HOLD ⚠️')
                        bot_state.reason = log_entry.get('reason', bot_state.reason)
                        ui = getattr(self, 'ui', None)
                        if ui:
                            ui.update_signal(bot_state.signal, bot_state.reason)
                    except Exception:
                        pass
                return

            # 🔹 BLOQUE 2: Verificar límites por DIRECCIÓN (ambos)
            # Si BUY y SELL están en límite, no tiene sentido detectar tendencia
            buy_at_limit = num_buy_positions >= max_buy_positions
            sell_at_limit = num_sell_positions >= max_sell_positions
            
            if buy_at_limit and sell_at_limit:
                logging.info(f"[INFO] 🔒 Límites BUY y SELL alcanzados. SKIP evaluación completa.")
                log_entry = {
                    "datetime": self.format_datetime(row["Datetime"]),
                    "current_price": float(row["Close"]),
                    "balance": float(self.balance),
                    "decision": "HOLD",
                    "reason": f"📊 Límites BUY ({num_buy_positions}/{max_buy_positions}) y SELL ({num_sell_positions}/{max_sell_positions}) alcanzados. HOLD ⏸️",
                    "trend": {"signal": "SKIP"}
                }
                self.log_process_data.append(log_entry)
                try:
                    self._persist_log_entry(log_entry)
                except Exception:
                    pass
                if bot_state is not None:
                    try:
                        bot_state.signal = log_entry.get('decision', 'HOLD ⚠️')
                        bot_state.reason = log_entry.get('reason', bot_state.reason)
                        ui = getattr(self, 'ui', None)
                        if ui:
                            ui.update_signal(bot_state.signal, bot_state.reason)
                    except Exception:
                        pass
                return

            # 🔹 BLOQUE 3: Detectar tendencia (solo si hay espacio para operar)
            trend = self.strategy.detect_trend(historical_data, data)
            trend_signal = trend.get("signal", "HOLD")

            # 🔸 COHERENCIA: permitir continuidad BUY/SELL si no hay nueva señal HOUR pero existe bias reciente
            # Esto no crea nuevas ideas, solo permite continuar una idea ya activa.
            if trend_signal == "HOLD ⚠️":
                try:
                    # Determinar vida del bias dinámicamente según HTF ADX
                    h_latest = historical_data.iloc[-1] if historical_data is not None and len(historical_data) > 0 else None
                    adx_htf = h_latest.get('ADX', 0) if h_latest is not None else 0
                    max_bias_age = 10 if adx_htf < 25 else 40
                    bias = getattr(self.strategy, 'market_bias', None)
                    bias_age = getattr(self.strategy, 'bias_age', 999)
                    if bias == "SELL" and bias_age <= max_bias_age:
                        logging.info(f"[INFO] ⚠️ Trend HOUR=HOLD pero `market_bias`=SELL (age={bias_age}) -> permitiendo SELL por continuidad (max_age={max_bias_age}).")
                        try:
                            trend['signal'] = "SELL ❌"
                            trend['reason'] = (trend.get('reason','') + " | Permitido SELL por market_bias (continuidad).").strip()
                        except Exception:
                            pass
                        trend_signal = trend.get("signal", "HOLD")
                    elif bias == "BUY" and bias_age <= max_bias_age:
                        logging.info(f"[INFO] ⚠️ Trend HOUR=HOLD pero `market_bias`=BUY (age={bias_age}) -> permitiendo BUY por continuidad (max_age={max_bias_age}).")
                        try:
                            trend['signal'] = "BUY ✅"
                            trend['reason'] = (trend.get('reason','') + " | Permitido BUY por market_bias (continuidad).").strip()
                        except Exception:
                            pass
                        trend_signal = trend.get("signal", "HOLD")
                except Exception:
                    pass
            
            # 🔹 VERIFICACIÓN INTELIGENTE: Si la tendencia indica BUY pero ya tenemos BUY,
            # marcar bloqueo y continuar para permitir que se evalúe la posibilidad
            # de abrir una operación opuesta (p.ej. SELL) en el mismo ciclo.
            buy_blocked = False
            sell_blocked = False
            # Flags para permitir sobreescribir límites cuando la señal es de DRENADO/ruptura o bias fuerte
            sell_overrode = False
            buy_overrode = False
            if "BUY" in trend_signal.upper() and buy_at_limit:
                # Solo bloquear BUY si hay SELL activo POR ENCIMA del precio actual (lógica corregida)
                sell_activos = [p for p in sell_positions if not self.is_legacy(p.get('position', p))]
                precio_actual = float(row["Close"])
                hay_sell_activo_cerca = False
                nivel_sell_cerca = None
                
                # Encontrar SELL más alta
                sell_levels = [float(p.get('position', p).get("level", 0)) for p in sell_activos]
                max_sell_level = max(sell_levels) if sell_levels else 0
                
                # Calcular distancia
                if max_sell_level > 0:
                    distance_pct = abs(precio_actual - max_sell_level) / max_sell_level * 100
                    
                    # BUY bloqueado solo si SELL está POR ENCIMA (no por debajo)
                    if max_sell_level > precio_actual and distance_pct < 2.0:
                        hay_sell_activo_cerca = True
                        nivel_sell_cerca = max_sell_level
                    
                    # ⚡ EXCEPCIÓN: Permitir si movimiento es OBVIO
                    elif max_sell_level < precio_actual and distance_pct > 3.0:
                        # SELL está por debajo y distancia > 3% → Permitir BUY (movimiento obvio)
                        try:
                            h_latest = historical_data.iloc[-1] if historical_data is not None and len(historical_data) > 0 else None
                            adx_htf = h_latest.get('ADX', 0) if h_latest is not None else 0
                            
                            if adx_htf > 30:
                                logging.info(f"[INFO] ⚡ MOVIMIENTO OBVIO: BUY permitido a ${precio_actual:.2f} (+{distance_pct:.1f}% sobre SELL ${max_sell_level:.2f}) | ADX={adx_htf:.1f}")
                                hay_sell_activo_cerca = False  # Forzar permiso
                        except Exception:
                            pass
                
                if hay_sell_activo_cerca:
                    logging.info(f"[INFO] 🔒 Señal BUY pero hay SELL activo cerca del precio (${nivel_sell_cerca:.2f}). SKIP evaluación.")
                    log_entry = {
                        "datetime": self.format_datetime(row["Datetime"]),
                        "current_price": float(row["Close"]),
                        "balance": float(self.balance),
                        "decision": "HOLD",
                        "reason": f"📊 No se puede BUY a ${precio_actual:.2f}. Hay SELL en ${nivel_sell_cerca:.2f} (por encima, distancia {distance_pct:.1f}%)",
                        "trend": trend
                    }
                    self.log_process_data.append(log_entry)
                    try:
                        self._persist_log_entry(log_entry)
                    except Exception:
                        pass
                    return
                # Evaluar posibilidad de sobreescribir el límite cuando bias BUY fuerte o señal de ruptura alcista
                allow_buy_override = False
                try:
                    reason_text = (trend.get('reason','') or '').lower() if isinstance(trend, dict) else ''
                    h_latest = historical_data.iloc[-1] if historical_data is not None and len(historical_data) > 0 else None
                    adx_htf = h_latest.get('ADX', 0) if h_latest is not None else 0
                    bias = getattr(self.strategy, 'market_bias', None)
                    bias_age = getattr(self.strategy, 'bias_age', 999)
                    max_bias_age = 10 if adx_htf < 25 else 40
                    if ('continuación alcista' in reason_text) or ('ruptura de resistencia' in reason_text) or (bias == 'BUY' and bias_age <= max_bias_age):
                        allow_buy_override = True
                except Exception:
                    allow_buy_override = False

                if allow_buy_override:
                    buy_overrode = True
                    logging.info(f"[OVERRIDE] ⚠️ BUY override permitido por condición impulso/bias (age={bias_age}). Ignorando límite BUY temporalmente.")
                else:
                    # Si no hay SELL activas cerca, marcar bloqueo de BUY pero permitir continuar
                    buy_blocked = True
                    logging.info(f"[INFO] 🔒 Señal BUY pero límite BUY alcanzado ({num_buy_positions}/{max_buy_positions}). Continuando evaluación para posibles SELL.")
                log_entry = {
                    "datetime": self.format_datetime(row["Datetime"]),
                    "current_price": float(row["Close"]),
                    "balance": float(self.balance),
                    "decision": "HOLD",
                    "reason": f"📊 Tengo {num_buy_positions} posiciones BUY, mi límite es {max_buy_positions}. HOLD ⏸️ (BUY bloqueado)",
                    "trend": trend
                }
                self.log_process_data.append(log_entry)
                try:
                    self._persist_log_entry(log_entry)
                except Exception:
                    pass

            # Solo bloquear SELL si hay BUY activo POR DEBAJO del precio actual (lógica corregida)
            if "SELL" in trend_signal.upper() and sell_at_limit:
                # Solo considerar BUY activos (no legacy) usando el helper central
                active_wrapped_for_check = self.get_active_positions_wrapped(positions)
                buy_activos = [p["position"] for p in active_wrapped_for_check.get("BUY", [])]
                hay_buy_activo_cerca = False
                precio_actual = float(row["Close"])
                nivel_buy_cerca = None
                
                # Encontrar BUY más baja
                buy_levels = [float(p.get("level", 0)) for p in buy_activos]
                min_buy_level = min(buy_levels) if buy_levels else 0
                
                # Calcular distancia
                if min_buy_level > 0:
                    distance_pct = abs(precio_actual - min_buy_level) / min_buy_level * 100
                    
                    # SELL bloqueado solo si BUY está POR DEBAJO (no por encima)
                    if min_buy_level < precio_actual and distance_pct < 2.0:
                        hay_buy_activo_cerca = True
                        nivel_buy_cerca = min_buy_level
                    
                    # ⚡ EXCEPCIÓN: Permitir si movimiento es OBVIO
                    elif min_buy_level > precio_actual and distance_pct > 3.0:
                        # BUY está por encima y distancia > 3% → Permitir SELL (movimiento obvio)
                        try:
                            h_latest = historical_data.iloc[-1] if historical_data is not None and len(historical_data) > 0 else None
                            adx_htf = h_latest.get('ADX', 0) if h_latest is not None else 0
                            
                            if adx_htf > 30:
                                logging.info(f"[INFO] ⚡ MOVIMIENTO OBVIO: SELL permitido a ${precio_actual:.2f} (-{distance_pct:.1f}% bajo BUY ${min_buy_level:.2f}) | ADX={adx_htf:.1f}")
                                hay_buy_activo_cerca = False  # Forzar permiso
                        except Exception:
                            pass
                
                if hay_buy_activo_cerca:
                    logging.info(f"[INFO] 🔒 Señal SELL pero límite SELL alcanzado ({num_sell_positions}/{max_sell_positions}) y hay BUY activo cerca del precio (${nivel_buy_cerca:.2f}). SKIP evaluación.")
                    log_entry = {
                        "datetime": self.format_datetime(row["Datetime"]),
                        "current_price": float(row["Close"]),
                        "balance": float(self.balance),
                        "decision": "HOLD",
                        "reason": f"📊 Tengo {num_sell_positions} posiciones SELL, mi límite es {max_sell_positions}. Hay BUY activo por debajo (distancia {distance_pct:.1f}%). HOLD ⏸️",
                        "trend": trend
                    }
                    self.log_process_data.append(log_entry)
                    return
                # Evaluar posibilidad de sobreescribir el límite cuando la señal indica drenado/ruptura
                allow_sell_override = False
                try:
                    reason_text = (trend.get('reason','') or '').lower() if isinstance(trend, dict) else ''
                    h_latest = historical_data.iloc[-1] if historical_data is not None and len(historical_data) > 0 else None
                    adx_htf = h_latest.get('ADX', 0) if h_latest is not None else 0
                    bias = getattr(self.strategy, 'market_bias', None)
                    bias_age = getattr(self.strategy, 'bias_age', 999)
                    max_bias_age = 10 if adx_htf < 25 else 40
                    if ('continuación bajista' in reason_text) or ('ruptura de soporte' in reason_text) or (bias == 'SELL' and bias_age <= max_bias_age):
                        allow_sell_override = True
                except Exception:
                    allow_sell_override = False

                if allow_sell_override:
                    sell_overrode = True
                    logging.info(f"[OVERRIDE] ⚠️ SELL override permitido por condición drenado/bias (age={bias_age}). Ignorando límite SELL temporalmente.")
                else:
                    # Si no hay BUY activo cerca, marcar bloqueo de SELL pero permitir continuar
                    sell_blocked = True
                    logging.info(f"[INFO] 🔒 Señal SELL pero límite SELL alcanzado ({num_sell_positions}/{max_sell_positions}). Continuando evaluación para posibles BUY.")
                log_entry = {
                    "datetime": self.format_datetime(row["Datetime"]),
                    "current_price": float(row["Close"]),
                    "balance": float(self.balance),
                    "decision": "HOLD",
                    "reason": f"📊 Tengo {num_sell_positions} posiciones SELL, mi límite es {max_sell_positions}. HOLD ⏸️ (SELL bloqueado)",
                    "trend": trend
                }
                self.log_process_data.append(log_entry)
                try:
                    self._persist_log_entry(log_entry)
                except Exception:
                    pass
            
            # 🔹 BLOQUE 3.5: Obtener precio tick actualizado para ScanMode y otros modos
            # IMPORTANTE: Esto se ejecuta ANTES del timing check para usar precio preciso
            try:
                tick_price = self.capital_ops.get_last_price("ETHUSD")
                if tick_price is not None and tick_price > 0:
                    original_price = row["Close"]
                    row["Close"] = tick_price  # Actualizar precio en row para todos los cálculos posteriores
                    
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"💲 Precio tick actualizado: ${tick_price:.2f} (histórico: ${original_price:.2f})")
                    else:
                        logging.debug(f"[DEBUG] 💲 Precio tick actualizado: ${tick_price:.2f} (histórico: ${original_price:.2f})")
                else:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"⚠️ get_last_price() falló, usando precio histórico: ${row['Close']:.2f}")
                    else:
                        logging.warning(f"[WARNING] ⚠️ get_last_price() falló, usando precio histórico: ${row['Close']:.2f}")
            except Exception as e:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"❌ Error obteniendo precio tick: {e}, usando histórico: ${row['Close']:.2f}")
                else:
                    logging.error(f"[ERROR] ❌ Error obteniendo precio tick: {e}, usando histórico: ${row['Close']:.2f}")

            # 🔹 BLOQUE 4: Verificar timing de 1M antes de ejecutar
            timing_check = self.timing_optimizer.should_enter_now(
                trend.get("signal", "HOLD ⚠️"),
                data,
                buy_positions=buy_positions
            )
            
            # 🔍 DEBUG: Mostrar detalles del timing check
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[DEBUG] 🎯 Timing check para señal '{trend.get('signal', 'HOLD ⚠️')}':")
                ui.add_log(f"[DEBUG]    - Execute: {timing_check['execute']}")
                ui.add_log(f"[DEBUG]    - Reason: {timing_check['reason']}")
                ui.add_log(f"[DEBUG]    - Confidence: {timing_check.get('confidence', 'N/A')}")
                ui.add_log(f"[DEBUG]    - Datos 1M disponibles: {len(data)} registros")
            
            if not timing_check["execute"]:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[INFO] ⏳ {timing_check['reason']}")
                log_entry = {
                    "datetime": self.format_datetime(row["Datetime"]),
                    "current_price": float(row["Close"]),
                    "balance": float(self.balance),
                    "decision": "HOLD",
                    "reason": timing_check["reason"],
                    "trend": trend
                }
                self.log_process_data.append(log_entry)
                try:
                    self._persist_log_entry(log_entry)
                except Exception:
                    pass
                if bot_state is not None:
                    try:
                        bot_state.signal = log_entry.get('decision', 'HOLD ⚠️')
                        bot_state.reason = log_entry.get('reason', bot_state.reason)
                        ui = getattr(self, 'ui', None)
                        if ui:
                            ui.update_signal(bot_state.signal, bot_state.reason)
                    except Exception:
                        pass
                return

            # Preparar los valores para la decisión (las posiciones ya fueron procesadas arriba)
            values = {
                "Datetime": self.format_datetime(row["Datetime"]),
                "Close": row["Close"],
                "RSI": row["RSI"],
                "MACD": row["MACD"],
                "MACD_Histogram": row.get("MACD_Histogram", 0),
                "ATR": row["ATR"],
                "VolumeChange": row.get("VolumeChange", 0),
            }

            # Se pasa la tupla (buy_positions, sell_positions) a la estrategia
            decision = self.strategy.decide(
                current_price=row["Close"],  # Ahora contiene precio tick actualizado
                balance=self.balance,
                features={
                    "RSI": row.get("RSI", 0),
                    "MACD": row.get("MACD", 0),
                    "ATR": row.get("ATR", 0),
                    "VolumeChange": row.get("VolumeChange", 0)
                },
                market_id="ETHUSD",
                historical_data=historical_data,
                data=data,
                open_positions=(buy_positions, sell_positions)
            )

            # Registro de la decisión
            # Sanitizar `trend` para evitar tipos no JSON-serializables (p.ej. numpy.bool_)
            def _make_json_safe(obj):
                if isinstance(obj, dict):
                    out = {}
                    for k, v in obj.items():
                        out[k] = _make_json_safe(v)
                    return out
                if isinstance(obj, list):
                    return [_make_json_safe(v) for v in obj]
                if isinstance(obj, (str, type(None))):
                    return obj
                if isinstance(obj, bool):
                    return obj
                if isinstance(obj, numbers.Number):
                    # convert numpy numbers to native python numbers
                    try:
                        return float(obj) if not isinstance(obj, int) else int(obj)
                    except Exception:
                        return float(obj)
                # Fallback a str
                try:
                    return bool(obj)
                except Exception:
                    return str(obj)

            safe_trend = _make_json_safe(trend) if isinstance(trend, (dict, list)) else trend

            log_entry = {
                "datetime": values["Datetime"],
                "current_price": float(row["Close"]),
                "balance": float(self.balance),
                "decision": decision["action"],
                "reason_decide": decision.get("reason", "Sin razón proporcionada"),
                "reason": decision.get("reason", "Sin razón proporcionada"),
                "strategy_score": decision.get("confianza_score"),
                "trend": safe_trend,
                "values": values
            }
            self.log_process_data.append(log_entry)
            # ⚠️ NO persistir aquí - esperar validaciones finales

            # Verificar el límite según el tipo de acción y ejecutar la operación
            if decision["action"] == "BUY":
                # 🔹 Check de Cooldown File
                is_ready, reason = self.check_trade_cooldown()
                if not is_ready:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"[INFO] ❄️ {reason}. HOLD forzoso.")
                    log_entry["decision"] = "HOLD"
                    log_entry["reason"] = reason
                    self._persist_log_entry(log_entry)  # ✅ Persistir HOLD por cooldown
                    return

                # 🔹 ACTUALIZAR BALANCE Y CAPITAL PRIMERO
                _, fresh_positions = self.update_balance_and_positions()
                
                # 🛡️ PROTECCIÓN DE CAPITAL: PRIORIDAD MÁXIMA - Bloquear si capital < 70%
                # ⚠️ ESTA VALIDACIÓN VA ANTES DE TODO - No importa si las posiciones son legacy
                if hasattr(self, 'capital_available_pct') and self.capital_available_pct < 70.0:
                    capital_msg = f"💰 CAPITAL COMPROMETIDO: Disponible ${self.balance:.2f} ({self.capital_available_pct:.1f}%) de ${self.balance_total:.2f}. "
                    capital_msg += f"🔄 Esperando recuperación de capital antes de nuevas operaciones."
                    logging.info(f"[CAPITAL_PROTECTION] 🛡️ PRIORIDAD: {capital_msg}")
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"[CAPITAL_PROTECTION] 🛡️ PRIORIDAD: {capital_msg}")
                    log_entry["decision"] = "HOLD"
                    log_entry["reason"] = f"CAPITAL_PROTECTION_PRIORITY: Disponible {self.capital_available_pct:.1f}% < 70%. {capital_msg}"
                    self._persist_log_entry(log_entry)  # ✅ Persistir HOLD por protección capital
                    return
                
                # 🔹 VALIDACIÓN DE LÍMITES: Calcular conteos actualizados (ya sin legacy)
                num_buy_positions_fresh = len(fresh_positions.get("BUY", []))
                num_sell_positions_fresh = len(fresh_positions.get("SELL", []))
                total_positions_fresh = num_buy_positions_fresh + num_sell_positions_fresh
                
                logging.info(f"[VALIDACIÓN BUY] Conteos FRESH: BUY={num_buy_positions_fresh}/{max_buy_positions}, SELL={num_sell_positions_fresh}, TOTAL={total_positions_fresh}/{self.max_total_positions}")
                
                # Verificar límite BUY
                if num_buy_positions_fresh >= max_buy_positions:
                    ui = getattr(self, 'ui', None)
                    critical_msg = f"🛑 BUY bloqueado: Límite alcanzado ({num_buy_positions_fresh}/{max_buy_positions})"
                    logging.critical(f"[CRITICAL] {critical_msg}")
                    if ui:
                        ui.add_log(f"[CRITICAL] {critical_msg}")
                    if bot_state:
                        bot_state.action = "HOLD"
                        bot_state.reason = f"CRITICAL: {critical_msg}"
                    log_entry["decision"] = "HOLD"
                    log_entry["reason"] = f"CRITICAL: Límite BUY alcanzado ({num_buy_positions_fresh}/{max_buy_positions})"
                    self._persist_log_entry(log_entry)  # ✅ Persistir HOLD por límite BUY
                    return
                
                # Verificar límite TOTAL
                if total_positions_fresh >= self.max_total_positions:
                    ui = getattr(self, 'ui', None)
                    critical_msg = f"🛑 BUY bloqueado: Límite TOTAL alcanzado ({total_positions_fresh}/{self.max_total_positions})"
                    logging.critical(f"[CRITICAL] {critical_msg}")
                    if ui:
                        ui.add_log(f"[CRITICAL] {critical_msg}")
                    if bot_state:
                        bot_state.action = "HOLD"
                        bot_state.reason = f"CRITICAL: {critical_msg}"
                    log_entry["decision"] = "HOLD"
                    log_entry["reason"] = f"CRITICAL: Límite TOTAL alcanzado ({total_positions_fresh}/{self.max_total_positions})"
                    self._persist_log_entry(log_entry)  # ✅ Persistir HOLD por límite TOTAL
                    return

                open_result = self.capital_ops.open_position(
                    market_id=decision["market_id"],
                    direction="BUY",
                    size=decision["size"],
                    stop_loss=decision.get("stop_loss"),
                    take_profit=decision.get("take_profit")
                )
                if open_result and (isinstance(open_result, dict) and open_result.get("error")):
                    logging.error(f"[ERROR] ❌ Error al abrir posición BUY: {open_result.get('message')}")
                    log_entry["decision"] = "HOLD"
                    log_entry["reason"] = f"Error al abrir posición: {open_result.get('message')}"
                    self._persist_log_entry(log_entry)  # ✅ Persistir HOLD por error API
                    return
                else:
                    logging.info(f"[INFO] ✅ open_position ejecutada correctamente. Respuesta: {open_result}")
                    # ✅ PERSISTIR BUY EXITOSO aquí
                    self._persist_log_entry(log_entry)
                    # � Snapshot de entrada para panel de posiciones
                    try:
                        buy_deal_id = open_result.get('dealId', '') if isinstance(open_result, dict) else ''
                        if buy_deal_id:
                            self._save_entry_snapshot(buy_deal_id, log_entry)
                    except Exception:
                        pass
                    # �🔊 Reproducir sonido de nueva posición
                    try:
                        from Evaluador import play_sound
                        ui_callback = lambda msg: logging.info(f"[SOUND] {msg}")
                        play_sound('open_position', ui_callback)
                    except Exception as e:
                        logging.warning(f"[WARNING] No se pudo reproducir sonido: {e}")
                    self.set_trade_cooldown(direction="BUY")  # 🕒 Activar cooldown persistente SOLO si fue exitosa
                    logging.info("[INFO] 🕒 Cooldown activado (20 min).")
                    # 🔹 BLOQUEO DE SEGURIDAD: ESPERAR CONFIRMACIÓN VISUAL EN API
                    logging.info("==================================================================")
                    logging.info("[SECURITY] 👁️ ESPERANDO QUE LA OPERACIÓN APAREZCA EN LA LISTA...")
                    logging.info("==================================================================")
                    confirmation_start = time.time()
                    while (time.time() - confirmation_start) < 45: # Esperar hasta 45 segundos
                        logging.info(f"[WAIT] ⏳ Verificando API... ({int(time.time() - confirmation_start)}s)")
                        time.sleep(3) # No spammear demasiado
                        try:
                            _, check_pos = self.update_balance_and_positions()
                            check_buy_count = len(check_pos.get("BUY", []))
                            if check_buy_count > num_buy_positions:
                                logging.info(f"[SUCCESS] ✅ Operación CONFIRMADA. Conteo BUY subió de {num_buy_positions} a {check_buy_count}.")
                                break
                            else:
                                logging.info(f"[PENDING] ⚠️ Aún no visible: {check_buy_count} posiciones (esperaba > {num_buy_positions})")
                        except Exception as e:
                            logging.error(f"[ERROR] Falló chequeo de confirmación: {e}")
                    logging.info("[INFO] 🚦 Continuando ciclo standard...")
                    # 🔹 REGISTRAR COMO PENDIENTE INMEDIATAMENTE SOLO si fue exitosa
                    self.pending_order = {"type": "BUY", "timestamp": time.time()}
            elif decision["action"] == "SELL":
                # 🔹 Check de Cooldown File
                is_ready, reason = self.check_trade_cooldown()
                if not is_ready:
                    logging.info(f"[INFO] ❄️ {reason}. HOLD forzoso.")
                    log_entry["decision"] = "HOLD"
                    log_entry["reason"] = reason
                    self._persist_log_entry(log_entry)  # ✅ Persistir HOLD por cooldown
                    return

                # 🔹 ACTUALIZAR BALANCE Y CAPITAL PRIMERO
                _, fresh_positions = self.update_balance_and_positions()
                
                # 🛡️ PROTECCIÓN DE CAPITAL: PRIORIDAD MÁXIMA - Bloquear si capital < 70%
                # ⚠️ ESTA VALIDACIÓN VA ANTES DE TODO - No importa si las posiciones son legacy
                if hasattr(self, 'capital_available_pct') and self.capital_available_pct < 70.0:
                    capital_msg = f"💰 CAPITAL COMPROMETIDO: Disponible ${self.balance:.2f} ({self.capital_available_pct:.1f}%) de ${self.balance_total:.2f}. "
                    capital_msg += f"🔄 Esperando recuperación de capital antes de nuevas operaciones."
                    logging.info(f"[CAPITAL_PROTECTION] 🛡️ PRIORIDAD: {capital_msg}")
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"[CAPITAL_PROTECTION] 🛡️ PRIORIDAD: {capital_msg}")
                    log_entry["decision"] = "HOLD"
                    log_entry["reason"] = f"CAPITAL_PROTECTION_PRIORITY: Disponible {self.capital_available_pct:.1f}% < 70%. {capital_msg}"
                    self._persist_log_entry(log_entry)  # ✅ Persistir HOLD por protección capital
                    return
                
                # 🔹 VALIDACIÓN DE LÍMITES: Calcular conteos actualizados (update_balance_and_positions ya filtra legacy)
                num_sell_positions_fresh = len(fresh_positions.get("SELL", []))
                num_buy_positions_fresh = len(fresh_positions.get("BUY", []))
                total_positions_fresh = num_sell_positions_fresh + num_buy_positions_fresh
                
                logging.info(f"[VALIDACIÓN SELL] Conteos FRESH: SELL={num_sell_positions_fresh}/{max_sell_positions}, BUY={num_buy_positions_fresh}, TOTAL={total_positions_fresh}/{self.max_total_positions}")
                
                # Verificar límite SELL
                if num_sell_positions_fresh >= max_sell_positions:
                    ui = getattr(self, 'ui', None)
                    critical_msg = f"🛑 SELL bloqueado: Límite alcanzado ({num_sell_positions_fresh}/{max_sell_positions})"
                    logging.critical(f"[CRITICAL] {critical_msg}")
                    if ui:
                        ui.add_log(f"[CRITICAL] {critical_msg}")
                    if bot_state:
                        bot_state.action = "HOLD"
                        bot_state.reason = f"CRITICAL: {critical_msg}"
                    log_entry["decision"] = "HOLD"
                    log_entry["reason"] = f"CRITICAL: Límite SELL alcanzado ({num_sell_positions_fresh}/{max_sell_positions})"
                    self._persist_log_entry(log_entry)  # ✅ Persistir HOLD por límite SELL
                    return
                
                # Verificar límite TOTAL
                if total_positions_fresh >= self.max_total_positions:
                    ui = getattr(self, 'ui', None)
                    critical_msg = f"🛑 SELL bloqueado: Límite TOTAL alcanzado ({total_positions_fresh}/{self.max_total_positions})"
                    logging.critical(f"[CRITICAL] {critical_msg}")
                    if ui:
                        ui.add_log(f"[CRITICAL] {critical_msg}")
                    if bot_state:
                        bot_state.action = "HOLD"
                        bot_state.reason = f"CRITICAL: {critical_msg}"
                    log_entry["decision"] = "HOLD"
                    log_entry["reason"] = f"CRITICAL: Límite TOTAL alcanzado ({total_positions_fresh}/{self.max_total_positions})"
                    self._persist_log_entry(log_entry)  # ✅ Persistir HOLD por límite TOTAL
                    return

                sell_result = self.capital_ops.open_position(
                    market_id=decision["market_id"],
                    direction="SELL",
                    size=decision["size"],
                    stop_loss=decision.get("stop_loss"),
                    take_profit=decision.get("take_profit")
                )
                # ✅ PERSISTIR SELL EXITOSO aquí
                self._persist_log_entry(log_entry)
                # 💾 Snapshot de entrada para panel de posiciones
                try:
                    sell_deal_id = sell_result.get('dealId', '') if isinstance(sell_result, dict) else ''
                    if sell_deal_id:
                        self._save_entry_snapshot(sell_deal_id, log_entry)
                except Exception:
                    pass
                # 🔊 Reproducir sonido de nueva posición
                try:
                    from Evaluador import play_sound
                    ui_callback = lambda msg: logging.info(f"[SOUND] {msg}")
                    play_sound('open_position', ui_callback)
                except Exception as e:
                    logging.warning(f"[WARNING] No se pudo reproducir sonido: {e}")
                self.set_trade_cooldown(direction="SELL")  # 🕒 Activar cooldown persistente SOLO si fue exitosa
                logging.info("[INFO] 🕒 Cooldown activado (20 min).")
                # 🔹 BLOQUEO DE SEGURIDAD: ESPERAR CONFIRMACIÓN VISUAL EN API
                logging.info("==================================================================")
                logging.info("[SECURITY] 👁️ ESPERANDO QUE LA OPERACIÓN APAREZCA EN LA LISTA...")
                logging.info("==================================================================")
                confirmation_start = time.time()
                while (time.time() - confirmation_start) < 45: # Esperar hasta 45 segundos
                    logging.info(f"[WAIT] ⏳ Verificando API... ({int(time.time() - confirmation_start)}s)")
                    time.sleep(3) # No spammear demasiado
                    try:
                        _, check_pos = self.update_balance_and_positions()
                        check_sell_count = len(check_pos.get("SELL", []))
                        if check_sell_count > num_sell_positions:
                            logging.info(f"[SUCCESS] ✅ Operación CONFIRMADA. Conteo SELL subió de {num_sell_positions} a {check_sell_count}.")
                            break
                        else:
                            logging.info(f"[PENDING] ⚠️ Aún no visible: {check_sell_count} posiciones (esperaba > {num_sell_positions})")
                    except Exception as e:
                        logging.error(f"[ERROR] Falló chequeo de confirmación: {e}")
                    logging.info("[INFO] 🚦 Continuando ciclo standard...")
                    # 🔹 REGISTRAR COMO PENDIENTE INMEDIATAMENTE SOLO si fue exitosa
                    self.pending_order = {"type": "SELL", "timestamp": time.time()}
                    logging.info("[INFO] 🔒 Bloqueo local activado para SELL. Esperando confirmación API...")
                logging.info("[INFO] 🛑 Pausa de seguridad post-trade (5s) para propagación API...")
                time.sleep(5)
            else:
                # Caso HOLD - persistir también
                logging.info("[INFO] ⏳ No se cumple ninguna condición para abrir una nueva posición.")
                self._persist_log_entry(log_entry)  # ✅ Persistir HOLD por estrategia

            logging.info(f"[INFO] Log actualizado desde Process Data:")
            logging.info(f"📈 TREND DETECTADO: {trend}")
            logging.info(json.dumps(log_entry, ensure_ascii=False, indent=4))
            # Si se suministró un BotState, actualizarlo para que la UI lo consuma
            if bot_state is not None:
                try:
                    bot_state.price = float(row.get("Close", bot_state.price))
                    bot_state.balance = float(self.balance or bot_state.balance)
                    bot_state.balance_total = float(getattr(self, 'balance_total', 0) or bot_state.balance_total)
                    bot_state.balance_deposit = float(getattr(self, 'balance_deposit', 0) or bot_state.balance_deposit)
                    bot_state.balance_profitloss = float(getattr(self, 'balance_profitloss', 0) or bot_state.balance_profitloss)
                    bot_state.capital_available_pct = float(getattr(self, 'capital_available_pct', 0) or bot_state.capital_available_pct)
                    bot_state.signal = trend.get("signal", bot_state.signal) if isinstance(trend, dict) else trend.get("signal", bot_state.signal) if isinstance(trend, dict) else log_entry.get('trend', bot_state.signal)
                except Exception:
                    pass
                # Llenar acción/razón/indicadores
                try:
                    bot_state.action = decision.get("action", bot_state.action)
                    bot_state.reason = decision.get("reason", bot_state.reason)
                    bot_state.trend = trend if isinstance(trend, str) else str(trend.get('trend', bot_state.trend)) if isinstance(trend, dict) else str(trend)
                    bot_state.micro_confirm = bool(trend.get("micro_confirm", True)) if isinstance(trend, dict) else True
                    bot_state.bias = getattr(self.strategy, 'market_bias', None)
                    bot_state.bias_age = getattr(self.strategy, 'bias_age', 0)
                    # indicadores
                    indicators = {}
                    for k in ["RSI", "RSI_7", "MACD", "MACD_Histogram", "EMA_3", "EMA_9", "EMA_20", "EMA_50", "ADX", "ATR"]:
                        try:
                            indicators[k] = float(row.get(k, historical_data.iloc[-1].get(k))) if k in row or (historical_data is not None and not historical_data.empty and k in historical_data.columns) else None
                        except Exception:
                            indicators[k] = None
                    bot_state.indicators = indicators
                    # log
                    if hasattr(bot_state, 'log'):
                        ts = self.format_datetime(row.get('Datetime') or row.get('Datetime'))
                        bot_state.log(f"{ts} | price={bot_state.price:.2f} | signal={bot_state.signal} | action={bot_state.action} | bias={bot_state.bias}")
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"[ERROR] ❌ Error en process_data: {e}")


 
    def save_position_tracker(self, filepath='eth_position_tracker.json'):
        try:
            with open(filepath, 'w') as file:
                json.dump(self.position_tracker, file, indent=4)
            logging.info("[INFO] eth_position_tracker guardado exitosamente.")
        except Exception as e:
            logging.error(f"[ERROR] Error al guardar eth_position_tracker: {e}")
 
    def load_position_tracker(self, filepath='eth_position_tracker.json'):
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as file:
                    self.position_tracker = json.load(file)
                logging.info("[INFO] eth_position_tracker cargado exitosamente.")
            except Exception as e:
                logging.error(f"[ERROR] Error al cargar eth_position_tracker: {e}")
                self.position_tracker = {}
        else:
            logging.info("[INFO] No se encontró eth_position_tracker.json. Inicializando vacío.")
            self.position_tracker = {}
 
    def format_datetime(self, timestamp):
        # Si es un objeto datetime o pd.Timestamp, formateamos directamente.
        if isinstance(timestamp, (pd.Timestamp, datetime)):
            return timestamp.strftime('%Y-%m-%d %H:%M:%S')
        # Si es un número (por ejemplo, epoch en milisegundos)
        elif isinstance(timestamp, (int, float)):
            return pd.to_datetime(timestamp, unit='ms').strftime('%Y-%m-%d %H:%M:%S')
        else:
            # Intentar convertir sin unidad, asumiendo que es una cadena legible
            try:
                return pd.to_datetime(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            except Exception as conv_e:
                logging.error(f"[ERROR] No se pudo convertir el timestamp: {timestamp}. Error: {conv_e}")
                return None
 
 
 
    def print_log(self):
        """Imprime el log detallado de las operaciones, formateado con Rich."""
        console = Console()
 
        console.print("[bold cyan][INFO] 📋 Registro de operaciones detallado:[/bold cyan]")
 
        if not self.log_open_positions and not self.log_process_data:
            console.print("[bold yellow][INFO] 🚫 Los logs están vacíos. No hay datos para imprimir.[/bold yellow]")
            return
 
 
       # 📌 📑 Logs desde `process_data` en dos columnas (usando una tabla sin bordes)
        if self.log_process_data:
            console.print("\n[bold magenta][INFO] 📑 Registro desde process_data:[/bold magenta]")
            for entry in self.log_process_data:
                trend_detected = entry.get("trend", "No disponible")
                # Usamos .strip() para eliminar espacios extra
                reason = entry.get("reason", "[❌] Razón no proporcionada.").strip()
 
                # En lugar de shortxen, usamos fill para envolver el texto en múltiples líneas
                trend_detected = textwrap.shorten(str(trend_detected), width=900, placeholder="...")
 
                reason = textwrap.shorten(str(reason), width=100, placeholder="...")
                trend_text = entry.get("trend", {}).get("trend", "No disponible")
 
                signal_text = entry.get("trend", {}).get("signal", "N/A")
 
 
                # Panel izquierdo: Información General sin incluir la Razón
                info_text = textwrap.dedent(f"""
                    [bold cyan]🏦 Cuenta Activa:[/bold cyan] {self.account_name}
                    [bold green]💰 Balance disponible:[/bold green] {entry.get('balance', 'N/A'):.2f}
                    [bold green]📉 Precio actual:[/bold green] {entry.get('current_price', 'N/A'):.2f}
                    [bold red]🔥 Decisión tomada:[/bold red] {entry.get('decision', 'N/A')}
                    [bold cyan]📝 Razón de decide:[/bold cyan] {entry.get('reason_decide', 'Sin razón proporcionada')}
 
                    [bold blue]📈 Tendencia detectada:[/bold blue]
                    {trend_text}
                    [bold yellow]🔔 Señal:[/bold yellow] {signal_text}
 
                """)
                panel_info = Panel(info_text, title="Información General")
 
                # Panel derecho: Tabla de valores de la decisión (limitando filas)
                tabla_valores = Table(title="📊 Valores de la Decisión", show_header=True, header_style="bold cyan")
                tabla_valores.add_column("Indicador", justify="left", style="dim")
                tabla_valores.add_column("Valor", justify="right")
                for key, value in itertools.islice(entry.get("values", {}).items(), 5):
                    if key != "Datetime":
                        tabla_valores.add_row(key, str(value))
                panel_detalles = Panel(tabla_valores, title="Detalles de la Decisión", height=10)
 
                # Distribuir en dos columnas sin bordes
                table_layout = Table(show_header=False, box=None, padding=(0,1))
                table_layout.add_column(justify="left")
                table_layout.add_column(justify="left")
                table_layout.add_row(panel_info, panel_detalles)
 
                # Panel para la Razón, que se muestra debajo
                panel_razon = Panel(f"[bold cyan]📝 Razón de la señal :[/bold cyan]\n{reason}", title="Razón", height=5)
 
                # Agrupar la parte superior (info y detalles) y el panel de Razón
                group_content = Group(table_layout, panel_razon)
                console.print(Panel(group_content, title="[bold yellow]📥 process_data[/bold yellow]", expand=False))
 
 
        # 🔹 Limpiar los registros después de imprimir
        self.log_open_positions = []
        self.log_process_data = []
 
 
if __name__ == "__main__":
    # 📝 Logging con rollback a 10MB en logs/ethboy.log
    setup_rotating_log()

    # ═══════════════════════════════════════════════════════════════════════
    # 🔄 AUTO-UPDATE: Verificar y descargar actualizaciones desde GitHub
    # ═══════════════════════════════════════════════════════════════════════
    auto_update_from_github()
    
    # 🔒 SINGLE INSTANCE CHECK (Nivel Sistema Operativo)
    # Esto evita que se ejecuten múltiples copias del bot al mismo tiempo.
    lock_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "EthBoy.lock")
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
        logging.info(f"[INFO] Instance Lock adquirido: {lock_file_path}")
    except (IOError, OSError):
        logging.critical(f"[CRITICAL] 🛑 ERROR FATAL: Otra instancia de EthBoy ya está corriendo.")
        logging.info("[INFO] 🔄 Matando proceso existente y reiniciando...")
        # Mejorado: intentar terminar el árbol responsable del respawn (padres)
        import psutil
        current_pid = os.getpid()
        # Recolectar procesos que contienen EthBoy.py (excepto éste)
        others = []
        for proc in psutil.process_iter(['pid', 'ppid', 'name', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline')
                if cmdline and any('EthBoy.py' in c for c in cmdline) and proc.info['pid'] != current_pid:
                    others.append(proc)
            except Exception:
                continue

        # Agrupar por PPID para detectar padres que respawnean
        parents = {}
        for proc in others:
            ppid = proc.info.get('ppid') or 0
            parents.setdefault(ppid, []).append(proc)

        # Primero intentar terminar a los padres responsables (si son shells u ordenadores de proceso)
        for ppid, procs in parents.items():
            try:
                if ppid == 0 or ppid == current_pid:
                    # No hay padre válido, matar hijos directamente
                    for p in procs:
                        try:
                            logging.info(f"[INFO] 🛑 Matando hijo PID: {p.pid}")
                            p.kill()
                        except Exception:
                            pass
                    continue

                parent = psutil.Process(ppid)
                parent_name = parent.name().lower()
                # Si el padre es una shell/u otro lanzador, preferimos terminarlo para evitar respawn
                if parent_name in ('bash', 'sh', 'zsh', 'tmux', 'screen', 'python', 'python3') or len(procs) > 1:
                    try:
                        logging.info(f"[INFO] 🔧 Terminando padre PID {ppid} ({parent_name}) responsable de {len(procs)} instancias...")
                        parent.terminate()
                        try:
                            parent.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            logging.warning(f"[WARN] Padre {ppid} no respondió a terminate, forzando kill")
                            parent.kill()
                    except Exception as e:
                        logging.warning(f"[WARN] No se pudo terminar padre {ppid}: {e}")
                        # como fallback, matar hijos
                        for p in procs:
                            try:
                                logging.info(f"[INFO] 🛑 Matando hijo PID fallback: {p.pid}")
                                p.kill()
                            except Exception:
                                pass
                else:
                    # Padre no es un lanzador obvio; matar hijos directamente
                    for p in procs:
                        try:
                            logging.info(f"[INFO] 🛑 Matando hijo PID: {p.pid}")
                            p.kill()
                        except Exception:
                            pass
            except psutil.NoSuchProcess:
                # Padre ya muerto, continuar
                continue
            except Exception as e:
                logging.warning(f"[WARN] Error procesando padre {ppid}: {e}")

        # Verificar si aún quedan instancias y fallar si no se pudieron eliminar
        remaining = []
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmdline = proc.info.get('cmdline')
                if cmdline and any('EthBoy.py' in c for c in cmdline) and proc.info['pid'] != current_pid:
                    remaining.append(proc.info['pid'])
            except Exception:
                continue

        if remaining:
            logging.critical(f"[CRITICAL] 🛑 No se pudo detener todas las instancias. PIDs restantes: {remaining}")
            sys.exit(1)

    try:
        logging.info("[INFO] Inicializando operador de trading...")
 
        features = ["RSI", "MACD", "ATR", "VolumeChange", "Close", "Datetime"]
 
        # 🔹 INICIALIZACIÓN: Crear operador primero para mostrar información de cuenta
        logging.info("[INFO] 🏦 Inicializando conexión con Capital.com...")
 
        capital_ops = CapitalOP()
        strategy = Strategia(capital_ops=capital_ops, threshold_buy=0, threshold_sell=2)
 
        trading_operator = TradingOperator(
            features=features,
            strategy=strategy,
            saldo_update_callback=None
        )
        
        # 🔹 MOSTRAR INFORMACIÓN DE CUENTA PRIMERO
        try:
            balance, positions = trading_operator.update_balance_and_positions()
            
            # Información básica
            logging.info(f"[INFO] 🏦 Cuenta conectada: {getattr(trading_operator, 'account_name', 'Desconocida')}")
            
            # 💰 GESTIÓN DE CAPITAL
            balance_total = getattr(trading_operator, 'balance_total', 0)
            balance_available = getattr(trading_operator, 'balance', 0)
            balance_deposit = getattr(trading_operator, 'balance_deposit', 0)
            balance_pnl = getattr(trading_operator, 'balance_profitloss', 0)
            capital_pct = getattr(trading_operator, 'capital_available_pct', 0)
            
            logging.info("="*70)
            logging.info("💰 GESTIÓN DE CAPITAL")
            logging.info("="*70)
            logging.info(f"  💰 Balance Total:      ${balance_total:.2f}")
            logging.info(f"  ✅ Disponible:         ${balance_available:.2f}")
            logging.info(f"  📊 Capital Libre:      {capital_pct:.1f}%")
            logging.info(f"  🔒 Comprometido:       ${balance_total - balance_available:.2f}")
            logging.info(f"  💵 Depósito Original:  ${balance_deposit:.2f}")
            
            # P&L con emoji
            pnl_emoji = "📈" if balance_pnl >= 0 else "📉"
            logging.info(f"  📊 P&L:                {pnl_emoji} ${balance_pnl:+.2f}")
            
            # Estado de protección
            if capital_pct < 70:
                logging.info(f"  🛡️  Estado:            🛡️  PROTECCIÓN ACTIVA (<70%)")
            else:
                logging.info(f"  🛡️  Estado:            ✅ Operativo Normal")
            logging.info("="*70)
            
            # Contar posiciones activas (no legacy)
            active_positions = trading_operator.get_active_positions_wrapped(positions)
            num_buy = len(active_positions.get('BUY', []))
            num_sell = len(active_positions.get('SELL', []))
            logging.info(f"[INFO] 📊 Posiciones activas: {num_buy + num_sell} total (BUY={num_buy}, SELL={num_sell})")
        except Exception as e:
            logging.warning(f"[WARNING] ⚠️ No se pudo obtener información de cuenta: {e}")
            logging.info("[INFO] Continuando con la inicialización...")
        
        # 🔹 CARGA DE DATOS: Intentar cargar, si falla ejecutar DataEth.py automáticamente
        logging.info("[INFO] 📊 Cargando datos históricos...")
        loader = DataLoader()
        _dl_cache['htf'], _dl_cache['ltf'] = loader.load_historical_data()
        _dl_cache['time'] = time.time()
        historical_data_htf, data_frame = _dl_cache['htf'], _dl_cache['ltf']
        
        # Si no hay datos HTF, ejecutar DataEth.py automáticamente
        if historical_data_htf.empty:
            logging.warning("[WARNING] ⚠️ No hay datos HTF disponibles. Ejecutando DataEth.py automáticamente...")
            try:
                trading_operator.update_historical_data(force=True)
                # Recargar después de ejecutar DataEth.py
                _dl_cache['htf'], _dl_cache['ltf'] = loader.load_historical_data()
                _dl_cache['time'] = time.time()
                historical_data_htf, data_frame = _dl_cache['htf'], _dl_cache['ltf']
                if historical_data_htf.empty:
                    logging.error("[ERROR] ❌ DataEth.py no pudo generar datos HTF. Verifique la conexión.")
                    logging.info("[INFO] ℹ️ Continuando con datos limitados...")
            except Exception as e:
                logging.error(f"[ERROR] ❌ Error ejecutando DataEth.py: {e}")
                logging.info("[INFO] ℹ️ Continuando con datos limitados...")
            
        if not historical_data_htf.empty:
            logging.info(f"[INFO] ✅ HTF cargado: {len(historical_data_htf)} velas ({historical_data_htf.index.min()} → {historical_data_htf.index.max()})")
        
        if data_frame.empty:
            logging.warning("[WARNING] ⚠️ LTF vacío - se poblará con get_1m_candles() en tiempo real")
            # Crear DataFrame vacío con columnas esperadas
            data_frame = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume'])
            data_frame.index = pd.DatetimeIndex([], name='Datetime')
        else:
            logging.info(f"[INFO] ✅ LTF cargado: {len(data_frame)} velas")

        # Crear BotState compartido para que la UI externa lo consuma
        bot_state = BotState()
        bot_state.account = "EthOperator"
        trading_operator.bot_state = bot_state

        # Iniciar Lightstream minimal dentro del mismo proceso para empujar ticks
        try:
            from lightstream_minimal import LightMinimal
            stream_client = LightMinimal(epic="ETHUSD")
            stream_thread = threading.Thread(target=stream_client.run, daemon=True)
            stream_thread.start()
            logging.info("[INFO] 🔌 Lightstream minimal iniciado en background (empujando ticks a MomentumHub).")

            # Registrar handlers para detener el stream en exit
            def _stop_stream(sig, frame):
                try:
                    stream_client.stop()
                except Exception:
                    pass
            try:
                import signal as _signal
                _signal.signal(_signal.SIGINT, _stop_stream)
                _signal.signal(_signal.SIGTERM, _stop_stream)
            except Exception:
                pass
        except Exception as e:
            logging.warning(f"[WARNING] No se pudo iniciar Lightstream minimal: {e}")
 
        # ═══════════════════════════════════════════════════════════
        # 📊 DASHBOARD SERVER: Lanzar en background
        # ═══════════════════════════════════════════════════════════
        try:
            dashboard_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard_server.py")
            if os.path.exists(dashboard_script):
                dashboard_proc = subprocess.Popen(
                    [sys.executable, dashboard_script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logging.info(f"[INFO] 📊 Dashboard server lanzado (PID {dashboard_proc.pid}) → http://localhost:8765")

                def _kill_dashboard():
                    try:
                        dashboard_proc.terminate()
                        dashboard_proc.wait(timeout=5)
                    except Exception:
                        try:
                            dashboard_proc.kill()
                        except Exception:
                            pass
                import atexit as _atexit
                _atexit.register(_kill_dashboard)
            else:
                logging.warning(f"[WARNING] dashboard_server.py no encontrado en {dashboard_script}")
        except Exception as e:
            logging.warning(f"[WARNING] No se pudo lanzar dashboard server: {e}")

        # ═══════════════════════════════════════════════════════════
        # MODO SCAN: Único modo de operación (automático, sin inputs)
        # ═══════════════════════════════════════════════════════════
        logging.info("[INFO] 🚀 Iniciando EthBoy en modo SCAN automático...")
        
        # Parámetros de ejecución (valores por defecto)
        iters = 0  # Continuo
        delay = 30.0  # 30 segundos entre ciclos
        
        logging.info(f"[INFO] ⚙️ Configuración: iterations={iters} (continuo), delay={delay}s")
        
        # Si se quiere configurar desde variables de entorno (opcional):
        try:
            import os
            if os.getenv("ETHBOY_ITERATIONS"):
                iters = int(os.getenv("ETHBOY_ITERATIONS"))
                logging.info(f"[INFO] 🔧 Iterations sobreescrito por env: {iters}")
            if os.getenv("ETHBOY_DELAY"):
                delay = float(os.getenv("ETHBOY_DELAY"))
                logging.info(f"[INFO] 🔧 Delay sobreescrito por env: {delay}s")
        except Exception:
            pass  # Usar valores por defecto ya establecidos
        
        logging.info(f"[INFO] ScanMode -> iterations={iters if iters > 0 else 'continuo'}, delay={delay}s")
        
        # Ejecutar loop principal
        try:
            if iters <= 0:
                # Loop continuo usando run_main_loop
                trading_operator.run_main_loop(data_frame, interval=int(delay))
            else:
                # Ejecutar N iteraciones manualmente
                count = 0
                while count < iters:
                    fresh_df_with_indicators = None  # Inicializar
                    latest = None
                    
                    try:
                        # 🔹 PASO 1: Actualizar datos históricos periódicamente (cada 5 min)
                        # Esto actualiza tanto HTF como LTF desde la API
                        
                        # 🔹 PASO 1.1: Verificar si datos están MUY desactualizados
                        force_update = False
                        try:
                            if time.time() - _dl_cache['time'] > 60:
                                loader = DataLoader()
                                _dl_cache['htf'], _dl_cache['ltf'] = loader.load_historical_data()
                                _dl_cache['time'] = time.time()
                            temp_htf, temp_ltf = _dl_cache['htf'], _dl_cache['ltf']
                            now = pd.Timestamp.now(tz='UTC')
                            
                            if temp_ltf is not None and not temp_ltf.empty:
                                ltf_age_min = (now - temp_ltf.index.max()).total_seconds() / 60
                                if ltf_age_min > 30:  # Más de 30 min desactualizado
                                    force_update = True
                                    logging.warning(f"[WARNING] ⚠️ LTF desactualizado por {ltf_age_min:.0f} minutos. Forzando actualización...")
                            
                            if temp_htf is not None and not temp_htf.empty:
                                htf_age_hours = (now - temp_htf.index.max()).total_seconds() / 3600
                                if htf_age_hours > 3:  # Más de 3 horas desactualizado
                                    force_update = True
                                    logging.warning(f"[WARNING] ⚠️ HTF desactualizado por {htf_age_hours:.1f} horas. Forzando actualización...")
                        except Exception as e:
                            logging.debug(f"[DEBUG] No se pudo verificar edad de datos: {e}")
                        
                        # 🔹 PASO 1.2: Ejecutar actualización
                        try:
                            trading_operator.update_historical_data(force=force_update)
                        except Exception as e:
                            logging.warning(f"[WARNING] ⚠️ Error actualizando datos históricos: {e}")
                        
                        # 🔹 PASO 1.5: Cargar datos HTF base (cacheado)
                        if time.time() - _dl_cache['time'] > 60:
                            loader = DataLoader()
                            _dl_cache['htf'], _dl_cache['ltf'] = loader.load_historical_data()
                            _dl_cache['time'] = time.time()
                        trading_operator.historical_data = _dl_cache['htf']
                        if trading_operator.historical_data is not None and not trading_operator.historical_data.empty:
                            df = trading_operator.historical_data
                        else:
                            df = data_frame
                        
                        # 🔹 PASO 2: Obtener velas 1M FRESCAS desde API (obligatorio)
                        logging.info(f"[ScanMode] 🕯️ Obteniendo velas 1M actuales desde API...")
                        
                        fresh_candles = trading_operator.capital_ops.get_1m_candles("ETHUSD", limit=40)
                        
                        if not fresh_candles or len(fresh_candles) == 0:
                            logging.info(f"[ScanMode] ❌ No se obtuvieron velas de la API - saltando este ciclo")
                            count += 1
                            time.sleep(delay)
                            continue
                        
                        logging.info(f"[ScanMode] ✅ Obtenidas {len(fresh_candles)} velas 1M desde API")
                        
                        # Convertir a DataFrame
                        import pandas as pd
                        from DataEth import calculate_ltf_indicators
                        
                        fresh_df = pd.DataFrame(fresh_candles)
                        fresh_df['timestamp'] = pd.to_datetime(fresh_df['timestamp'])
                        fresh_df.set_index('timestamp', inplace=True)
                        fresh_df = fresh_df.sort_index()
                        
                        # 🔥 CALCULAR INDICADORES sobre datos frescos
                        fresh_df_with_indicators = calculate_ltf_indicators(fresh_df)
                        
                        logging.info(f"[ScanMode] 📊 Indicadores calculados: {len(fresh_df_with_indicators)} velas")
                        logging.info(f"[ScanMode] 📊 Columnas: {list(fresh_df_with_indicators.columns)[:10]}...")
                        
                        if fresh_df_with_indicators.empty:
                            logging.info(f"[ScanMode] ❌ Error calculando indicadores - DataFrame vacío")
                            count += 1
                            time.sleep(delay)
                            continue
                        
                        # Última vela con indicadores - convertir a dict
                        latest_series = fresh_df_with_indicators.iloc[-1]
                        last_ts = fresh_df_with_indicators.index[-1]
                        
                        # 🔥 Convertir Series a dict e incluir timestamp
                        latest = latest_series.to_dict()
                        latest['Datetime'] = last_ts
                        
                        logging.info(f"[ScanMode] 💹 Última vela: {last_ts}")
                        logging.info(f"[ScanMode] 💹 Close: ${latest.get('Close', 0):.2f}, RSI: {latest.get('RSI', 0):.1f}, MACD: {latest.get('MACD', 0):.2f}")
                        
                        # 🔹 PASO 3: Actualizar balance y posiciones FRESCOS desde API
                        bal, pos = trading_operator.update_balance_and_positions()
                        
                        # 🔍 DIAGNÓSTICO: Conteo detallado de posiciones ANTES de process_data
                        num_buy_current = len(pos.get("BUY", []))
                        num_sell_current = len(pos.get("SELL", []))
                        logging.info(f"[ScanMode] 📊 Posiciones ACTUALES después de update: BUY={num_buy_current}, SELL={num_sell_current}, Total={num_buy_current + num_sell_current}")
                        logging.info(f"[ScanMode] 💰 Balance actual: ${bal:.2f}")
                        logging.info(f"[ScanMode] 🔍 Pasando a process_data: df HTF={len(df)} velas, df LTF={len(fresh_df_with_indicators)} velas")
                        
                        trading_operator.process_data(
                            row=latest, 
                            positions=pos, 
                            balance=bal, 
                            bot_state=bot_state, 
                            historical_data=df, 
                            data=fresh_df_with_indicators  # 🔥 SIEMPRE datos frescos
                        )
                        
                        # 🔍 DIAGNÓSTICO: Re-verificar conteo DESPUÉS de process_data
                        bal_after, pos_after = trading_operator.update_balance_and_positions()
                        num_buy_after = len(pos_after.get("BUY", []))
                        num_sell_after = len(pos_after.get("SELL", []))
                        logging.info(f"[ScanMode] 📊 Posiciones DESPUÉS de process_data: BUY={num_buy_after}, SELL={num_sell_after}, Total={num_buy_after + num_sell_after}")
                        if num_buy_after != num_buy_current or num_sell_after != num_sell_current:
                            logging.info(f"[ScanMode] 🚨 CAMBIO DETECTADO: BUY {num_buy_current}→{num_buy_after}, SELL {num_sell_current}→{num_sell_after}")
                        
                        # 📋 RESUMEN FINAL del ciclo
                        logging.info("=" * 80)
                        logging.info(f"[ScanMode] 📊 RESUMEN CICLO {count + 1}:")
                        logging.info("-" * 80)
                        
                        # 💰 Gestión de Capital
                        balance_total_after = getattr(trading_operator, 'balance_total', 0)
                        balance_available_after = bal_after
                        balance_pnl_after = getattr(trading_operator, 'balance_profitloss', 0)
                        capital_pct_after = getattr(trading_operator, 'capital_available_pct', 0)
                        capital_committed = balance_total_after - balance_available_after
                        
                        logging.info(f"  💰 GESTIÓN DE CAPITAL:")
                        logging.info(f"     Balance Total:      ${balance_total_after:.2f}")
                        logging.info(f"     Disponible:         ${balance_available_after:.2f}")
                        logging.info(f"     Capital Libre:      {capital_pct_after:.1f}%")
                        logging.info(f"     Comprometido:       ${capital_committed:.2f}")
                        pnl_emoji = "📈" if balance_pnl_after >= 0 else "📉"
                        logging.info(f"     P&L:                {pnl_emoji} ${balance_pnl_after:+.2f}")
                        
                        if capital_pct_after < 70:
                            logging.info(f"     Estado:             🛡️  PROTECCIÓN ACTIVA (<70%)")
                        else:
                            logging.info(f"     Estado:             ✅ Operativo Normal")
                        
                        logging.info(f"  📊 POSICIONES:")
                        logging.info(f"     BUY activas:        {num_buy_after}/{trading_operator.capital_ops.max_buy_positions}")
                        logging.info(f"     SELL activas:       {num_sell_after}/{trading_operator.capital_ops.max_sell_positions}")
                        logging.info(f"     Total posiciones:   {num_buy_after + num_sell_after}/{trading_operator.max_total_positions}")
                        
                        logging.info(f"  ⏰ Próximo ciclo en {delay}s...")
                        logging.info("=" * 80)
                    except KeyboardInterrupt:
                        logging.info("[INFO] Interrupción por usuario. Saliendo ScanMode.")
                        break
                    except Exception as e:
                        logging.error(f"[ERROR] Error en ScanMode iteración: {e}")
                    
                    count += 1
                    time.sleep(delay)
        except Exception as e:
            logging.error(f"[ERROR] No se pudo iniciar ScanMode: {e}")
            sys.exit(1)
 
    except Exception as e:
        logging.error(f"[ERROR] Error en la ejecución principal: {e}")
