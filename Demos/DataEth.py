import os
import pandas as pd
import numpy as np
import json
import requests
from datetime import datetime, timedelta
import pytz
import pickle
from ta.momentum import StochasticOscillator
from ta.trend import MACD, EMAIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from EthSession import CapitalOP  # Importar autenticación desde EthSession
from ta.momentum import RSIIndicator, StochasticOscillator
import time

# ========== CONSTANTES DE VENTANA DE DATOS ==========
HTF_WINDOW = 43800    # ~5 años de velas HOUR (5 * 365 * 24)
LTF_WINDOW = 10080    # 7 días de velas MINUTE (7 * 24 * 60)
ATTEMPT_COOLDOWN_HOURS = 4   # Cooldown entre intentos de descarga fallidos
MAX_ATTEMPTS_PER_RANGE = 3   # Máximo intentos por rango antes de marcar permanente

# ========== SISTEMA DE ROTACIÓN DE APIs ==========
# Rotador global para balancear carga entre APIs gratuitas
class APIRotator:
    """Rotador de APIs para distribuir carga entre Binance, Kraken y CryptoCompare"""
    def __init__(self):
        self.apis = ['binance', 'kraken', 'cryptocompare']
        self.current_index = 0
        self.request_count = {'binance': 0, 'kraken': 0, 'cryptocompare': 0}
        self.error_count = {'binance': 0, 'kraken': 0, 'cryptocompare': 0}

    def get_next_api(self):
        """Obtiene la siguiente API en rotación"""
        api = self.apis[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.apis)
        return api

    def record_request(self, api, success=True):
        """Registra una petición a una API"""
        self.request_count[api] += 1
        if not success:
            self.error_count[api] += 1

    def get_stats(self):
        """Obtiene estadísticas de uso"""
        return {
            'requests': self.request_count.copy(),
            'errors': self.error_count.copy()
        }

# Instancia global del rotador

# ========== FUNCIONES DE DESCARGA POR API ==========
def download_binance(start_date, end_date, interval='1h'):
    """Descarga datos desde Binance Spot API"""
    try:
        url = "https://api.binance.com/api/v3/klines"

        start_ms = int(start_date.timestamp() * 1000)
        end_ms = int(end_date.timestamp() * 1000)

        params = {
            'symbol': 'ETHUSDT',
            'interval': interval,
            'startTime': start_ms,
            'endTime': end_ms,
            'limit': 1000
        }

        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()

            if not data:
                return None

            df = pd.DataFrame(data, columns=[
                'timestamp', 'Open', 'High', 'Low', 'Close', 'Volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])

            df['Datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df = df[['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']]
            df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
            df.set_index('Datetime', inplace=True)
            df.sort_index(inplace=True)

            # api_rotator.record_request('binance', success=True)
            return df
        else:
            # api_rotator.record_request('binance', success=False)
            return None
    except Exception as e:
        print(f"[WARNING] Error en Binance: {e}")
        # api_rotator.record_request('binance', success=False)
        return None

def download_kraken(start_date, end_date, interval=60):
    """Descarga datos desde Kraken API"""
    try:
        url = "https://api.kraken.com/0/public/OHLC"

        params = {
            'pair': 'ETHUSD',
            'interval': interval,
            'since': int(start_date.timestamp())
        }

        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()

            if 'error' in data and data['error']:
                # api_rotator.record_request('kraken', success=False)
                return None

            result = data.get('result', {})
            pair_key = next(iter([k for k in result.keys() if 'ETH' in k]), None)

            if not pair_key:
                # api_rotator.record_request('kraken', success=False)
                return None

            ohlc_data = result[pair_key]

            if not ohlc_data:
                # api_rotator.record_request('kraken', success=False)
                return None

            df = pd.DataFrame(ohlc_data, columns=[
                'timestamp', 'Open', 'High', 'Low', 'Close', 'vwap', 'Volume', 'count'
            ])
            df['Datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
            df = df[['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']]
            df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)

            # Filtrar por rango
            df = df[(df['Datetime'] >= start_date) & (df['Datetime'] <= end_date)]
            df.set_index('Datetime', inplace=True)
            df.sort_index(inplace=True)

            # api_rotator.record_request('kraken', success=True)
            return df
        else:
            # api_rotator.record_request('kraken', success=False)
            return None
    except Exception as e:
        print(f"[WARNING] Error en Kraken: {e}")
        # api_rotator.record_request('kraken', success=False)
        return None

def download_cryptocompare(start_date, end_date, interval='hour'):
    """Descarga datos desde CryptoCompare API"""
    try:
        url = "https://min-api.cryptocompare.com/data/v2/histohour" if interval == 'hour' else "https://min-api.cryptocompare.com/data/v2/histominute"

        params = {
            'fsym': 'ETH',
            'tsym': 'USD',
            'limit': 2000,
            'toTs': int(end_date.timestamp())
        }

        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()

            if data.get('Response') != 'Success':
                # api_rotator.record_request('cryptocompare', success=False)
                return None

            ohlc_data = data['Data']['Data']

            if not ohlc_data:
                # api_rotator.record_request('cryptocompare', success=False)
                return None

            df = pd.DataFrame(ohlc_data)
            df['Datetime'] = pd.to_datetime(df['time'], unit='s', utc=True)
            df = df[['Datetime', 'open', 'high', 'low', 'close', 'volumefrom']]
            df.rename(columns={
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volumefrom': 'Volume'
            }, inplace=True)

            # Filtrar por rango
            df = df[(df['Datetime'] >= start_date) & (df['Datetime'] <= end_date)]
            df.set_index('Datetime', inplace=True)
            df.sort_index(inplace=True)

            # api_rotator.record_request('cryptocompare', success=True)
            return df if len(df) > 0 else None
        else:
            # api_rotator.record_request('cryptocompare', success=False)
            return None
    except Exception as e:
        print(f"[WARNING] Error en CryptoCompare: {e}")
        # api_rotator.record_request('cryptocompare', success=False)
        return None

def download_with_rotation(start_date, end_date, interval='HOUR'):
    """Descarga datos rotando entre las 3 APIs gratuitas con fallback"""
    # Mapeo de intervalos
    interval_map = {
        'HOUR': {'binance': '1h', 'kraken': 60, 'cryptocompare': 'hour'},
        'MINUTE': {'binance': '1m', 'kraken': 1, 'cryptocompare': 'minute'}
    }

    if interval not in interval_map:
        print(f"[ERROR] Intervalo {interval} no soportado")
        return None

    # Crear instancia del rotador de APIs
    api_rotator = APIRotator()

    # Intentar con las 3 APIs en orden rotativo
    attempts = 0
    max_attempts = 3

    while attempts < max_attempts:
        api = api_rotator.get_next_api()
        print(f"[INFO] 🔄 Descargando desde {api.upper()} ({start_date.strftime('%Y-%m-%d %H:%M')} → {end_date.strftime('%Y-%m-%d %H:%M')})")

        df = None
        api_interval = interval_map[interval][api]

        if api == 'binance':
            df = download_binance(start_date, end_date, api_interval)
        elif api == 'kraken':
            df = download_kraken(start_date, end_date, api_interval)
        elif api == 'cryptocompare':
            df = download_cryptocompare(start_date, end_date, api_interval)

        if df is not None and not df.empty:
            print(f"[INFO] ✅ {api.upper()}: {len(df)} velas obtenidas")
            time.sleep(0.5)  # Rate limiting cortés
            return df

        attempts += 1
        print(f"[WARNING] {api.upper()} no devolvió datos. Intentando siguiente API...")
        time.sleep(1)  # Esperar antes de reintentar

    print(f"[ERROR] ❌ Ninguna API devolvió datos para {start_date} → {end_date}")
    return None

# ========== CONFIGURACIÓN DE VENTANAS MÓVILES ==========

# 🎯 Ventanas móviles optimizadas (solo mantener lo necesario)

# 🔄 Thresholds de actualización automática

# 📦 Configuración legacy (compatibilidad)

# Política de backfill y reintentos

# ========== MODO DE OPERACIÓN: APIs GRATUITAS ==========
# Ya no necesitamos Capital.com - usamos rotación de APIs gratuitas

# ========== PERSISTENCIA DE TRAMOS SIN DATOS ==========
def _load_missing_ranges():
    """Carga el registro de tramos sin datos desde Reports/missing_ranges.json"""
    missing_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Reports', 'missing_ranges.json')
    if not os.path.exists(missing_file):
        return {}
    try:
        with open(missing_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARNING] Error al leer missing_ranges.json: {e}")
        return {}

def _save_missing_ranges(missing):
    """Guarda el registro de tramos sin datos en Reports/missing_ranges.json"""
    reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Reports')
    os.makedirs(reports_dir, exist_ok=True)
    missing_file = os.path.join(reports_dir, 'missing_ranges.json')
    try:
        with open(missing_file, 'w') as f:
            json.dump(missing, f, indent=2, default=str)
    except Exception as e:
        print(f"[ERROR] Error al guardar missing_ranges.json: {e}")

def _should_skip_range(start, end, missing):
    """Verifica si un rango debe ser saltado según missing_ranges.json
    Retorna (skip: bool, reason: str)
    """
    key = f"{start.isoformat()}->{end.isoformat()}"
    if key not in missing:
        return False, ""

    entry = missing[key]
    attempts = entry.get('attempts', 0)
    last_attempt = entry.get('last_attempt')

    # Si ya se intentó >= MAX_ATTEMPTS_PER_RANGE veces, marcar como permanente
    if attempts >= MAX_ATTEMPTS_PER_RANGE:
        return True, f"max_attempts ({MAX_ATTEMPTS_PER_RANGE}) alcanzados"

    # Verificar cooldown
    if last_attempt:
        try:
            last_dt = datetime.fromisoformat(last_attempt).replace(tzinfo=pytz.UTC)
            now = datetime.now(pytz.UTC)
            elapsed_hours = (now - last_dt).total_seconds() / 3600
            if elapsed_hours < ATTEMPT_COOLDOWN_HOURS:
                return True, f"cooldown activo ({int(ATTEMPT_COOLDOWN_HOURS - elapsed_hours)}h restantes)"
        except Exception:
            pass

    return False, ""

def _register_missing_range(start, end, reason="no-data"):
    """Registra un tramo sin datos en missing_ranges.json"""
    missing = _load_missing_ranges()
    key = f"{start.isoformat()}->{end.isoformat()}"
    now = datetime.now(pytz.UTC)

    if key in missing:
        missing[key]['attempts'] = missing[key].get('attempts', 0) + 1
        missing[key]['last_attempt'] = now.isoformat()
        missing[key]['reason'] = reason
    else:
        missing[key] = {
            'start': start.isoformat(),
            'end': end.isoformat(),
            'attempts': 1,
            'last_attempt': now.isoformat(),
            'reason': reason
        }

    _save_missing_ranges(missing)
    attempts = missing[key]['attempts']
    print(f"[INFO] 📝 Rango {key} registrado en missing_ranges.json (intento {attempts}/{MAX_ATTEMPTS_PER_RANGE}, motivo: {reason})")

def _clear_missing_range(start, end):
    """Remueve un tramo de missing_ranges.json si ahora tiene datos"""
    missing = _load_missing_ranges()
    key = f"{start.isoformat()}->{end.isoformat()}"
    if key in missing:
        missing.pop(key)
        _save_missing_ranges(missing)
        print(f"[INFO] ✅ Rango {key} removido de missing_ranges.json (datos obtenidos)")
# =======================================================

def get_epic(symbol):
    """
    Retorna el símbolo directamente (ya no necesitamos EPIC de Capital.com).
    Mantenida por compatibilidad con código legacy.
    """
    return symbol

def download_data_capital(epic, interval, start_date, end_date):
    """
    Descarga datos históricos usando rotación de APIs gratuitas.
    Mantiene dos DataFrames:
    1. historical_data -> Contiene los datos históricos en la resolución original.
    2. data -> Contiene los datos a 1 minuto con un buffer adecuado.
    """
    all_data = []
    current_date = start_date
    segment_days = 10  # Descarga en segmentos

    # Para intervalos HOUR usar ventanas más grandes (Binance permite 1000 velas)
    # Para MINUTE usar ventanas cortas
    if interval == "HOUR":
        chunk = timedelta(days=30)  # ~720 horas < 1000 límite Binance
    elif interval == "MINUTE":
        chunk = timedelta(days=1)  # ~1440 minutos < límite
    else:
        chunk = timedelta(days=segment_days)

    while current_date < end_date:
        seg_end_date = min(current_date + chunk, end_date)

        # Descargar usando rotación de APIs
        df_segment = download_with_rotation(current_date, seg_end_date, interval)

        if df_segment is not None and not df_segment.empty:
            # Convertir de vuelta a formato de lista de dicts para compatibilidad
            df_segment_reset = df_segment.reset_index()
            segment_dicts = df_segment_reset.to_dict('records')
            all_data.extend(segment_dicts)
        else:
            print(f"[WARNING] No se encontraron datos para {current_date} - {seg_end_date}")

        current_date = seg_end_date
        time.sleep(0.3)  # Rate limiting cortés entre segmentos

    if all_data:
        # 📌 Crear DataFrame con datos históricos (HOUR, DAY, etc.)
        df = pd.DataFrame(all_data)
        # Los datos ya vienen con columnas normalizadas (Datetime, Open, High, Low, Close, Volume)
        if 'Datetime' in df.columns:
            df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
            df.set_index("Datetime", inplace=True)
        df.sort_index(inplace=True)
        # Eliminar duplicados
        df = df[~df.index.duplicated(keep='last')]
        historical_data = df.copy()

        # ✅ Descargar últimos N días de datos en resolución MINUTE (por defecto 7d)
        data = pd.DataFrame()
        if interval == 'MINUTE':
            last_hour = df.index[-1]
            data_minute = []

            # Segmentar la descarga usando rotación de APIs
            now_utc = datetime.now(pytz.UTC)
            minute_days = 7  # 7 días de datos MINUTE
            start_minute = last_hour - timedelta(days=minute_days)
            current_start = start_minute

            while current_start < last_hour:
                if current_start >= now_utc:
                    break
                seg_end = min(current_start + timedelta(days=1), last_hour, now_utc)

                # Usar rotación de APIs para MINUTE
                df_minute_segment = download_with_rotation(current_start, seg_end, 'MINUTE')

                if df_minute_segment is not None and not df_minute_segment.empty:
                    df_minute_reset = df_minute_segment.reset_index()
                    segment_dicts = df_minute_reset.to_dict('records')
                    data_minute.extend(segment_dicts)
                else:
                    print(f"[WARNING] No se encontraron datos 1M para {current_start} - {seg_end}")

                current_start = seg_end + timedelta(seconds=1)
                time.sleep(0.3)  # Rate limiting

            if data_minute:
                minute_df = pd.DataFrame(data_minute)
                if 'Datetime' in minute_df.columns:
                    minute_df["Datetime"] = pd.to_datetime(minute_df["Datetime"], utc=True)
                    minute_df.set_index("Datetime", inplace=True)
                minute_df.sort_index(inplace=True)
                minute_df = minute_df[~minute_df.index.duplicated(keep='last')]
                data = minute_df.copy()

        print(f"[INFO] ✅ Datos descargados correctamente: {len(historical_data)} registros históricos, {len(data)} registros a 1M.")
        return historical_data, data

    print("[ERROR] ❌ No se obtuvieron datos.")
    return pd.DataFrame(), pd.DataFrame()


def _load_existing_reports():
    """
    Carga el JSON existente si está presente y devuelve dos DataFrames (htf, ltf).
    """
    reports_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Reports", "ETHUSD_CapitalData.json")
    if not os.path.exists(reports_path):
        return pd.DataFrame(), pd.DataFrame()
    try:
        with open(reports_path, 'r') as f:
            j = json.load(f)

        def _parse_records(records):
            if not records:
                return pd.DataFrame()
            df = pd.DataFrame(records)
            # Normalize possible timestamp fields into `Datetime` tz-aware UTC
            if 'Datetime' in df.columns:
                try:
                    # handle numeric epoch ms vs ISO strings
                    if pd.api.types.is_integer_dtype(df['Datetime']):
                        df['Datetime'] = pd.to_datetime(df['Datetime'], unit='ms', utc=True)
                    else:
                        df['Datetime'] = pd.to_datetime(df['Datetime'], utc=True, errors='coerce')
                except Exception:
                    df['Datetime'] = pd.to_datetime(df['Datetime'], utc=True, errors='coerce')
            elif 'snapshotTime' in df.columns:
                try:
                    if pd.api.types.is_integer_dtype(df['snapshotTime']):
                        df['Datetime'] = pd.to_datetime(df['snapshotTime'], unit='ms', utc=True)
                    else:
                        df['Datetime'] = pd.to_datetime(df['snapshotTime'], utc=True, errors='coerce')
                except Exception:
                    df['Datetime'] = pd.to_datetime(df['snapshotTime'], utc=True, errors='coerce')

            # If we have Datetime column, set it as index and ensure tz-aware
            if 'Datetime' in df.columns:
                try:
                    df['Datetime'] = pd.to_datetime(df['Datetime'], utc=True, errors='coerce')
                    df = df.dropna(subset=['Datetime'])
                    df.set_index('Datetime', inplace=True)
                    df.sort_index(inplace=True)
                except Exception:
                    pass
            return df

        htf = _parse_records(j.get('historical_data', []))
        ltf = _parse_records(j.get('data', []))
        return htf, ltf

    except Exception as e:
        print(f"[WARNING] Error cargando Reports existente: {e}")
        return pd.DataFrame(), pd.DataFrame()


def _merge_and_write_reports(existing_htf, existing_ltf, new_htf, new_ltf, recalc=True):
    """
    Fusiona DataFrames (elimina duplicados por Datetime/snapshotTime) y reescribe el JSON de Reports.
    """
    # Normalizar columnas de tiempo a 'Datetime' para ambos
    def _ensure_dt(df):
        if df is None or df.empty:
            return pd.DataFrame()
        # Ensure we always have a column called 'Datetime' (avoid mixing index vs column representations)
        # If Datetime exists as index, reset it into a column so concatenation is consistent.
        try:
            if isinstance(df.index, pd.DatetimeIndex):
                # reset index to get 'Datetime' column
                df = df.reset_index()
        except Exception:
            pass

        if 'Datetime' in df.columns:
            try:
                df['Datetime'] = pd.to_datetime(df['Datetime'], utc=True, errors='coerce')
            except Exception:
                df['Datetime'] = pd.to_datetime(df['Datetime'], unit='ms', utc=True, errors='coerce')
        elif 'snapshotTime' in df.columns:
            try:
                df['Datetime'] = pd.to_datetime(df['snapshotTime'], utc=True, errors='coerce')
            except Exception:
                df['Datetime'] = pd.to_datetime(df['snapshotTime'], unit='ms', utc=True, errors='coerce')
        return df


    # Concatenate as records with a consistent 'Datetime' column

        # Normalize Datetime column and timezone
        # Report duplicates for debugging


    # Antes de serializar, recalcular indicadores sobre los DataFrames fusionados
    # Recalcular indicadores sólo si se solicita (evita recálculos costosos en merges incrementales)

    # 🧹 TRUNCAR a ventanas móviles (mantener solo últimas N velas)


    # Convertir a registros (JSON serializable) y normalizar Datetime a ISO+UTC
    def _to_serializable(df):
        if df is None or df.empty:
            return []
        r = df.reset_index().copy()
        if 'Datetime' in r.columns:
            def _fmt(x):
                try:
                    if isinstance(x, pd.Timestamp):
                        return x.isoformat()
                    else:
                        return pd.to_datetime(x, utc=True).isoformat()
                except Exception:
                    return str(x)


    # 💾 GUARDAR EN FORMATO PARQUET (eficiente, rápido)


    # 💾 GUARDAR EN FORMATO JSON (legacy, compatibilidad)


def download_range_and_merge(epic, interval, s, e, existing_htf, existing_ltf):
    """Descarga el rango s->e y lo fusiona inmediatamente con los existentes.

    Esto permite reanudar si el proceso se interrumpe, evitando repetir rangos ya descargados.
    """
    # Convertir s, e a tz-aware para comparación
    try:
        s_aware = pd.Timestamp(s).tz_localize(pytz.UTC) if pd.Timestamp(s).tz is None else pd.Timestamp(s).tz_convert(pytz.UTC)
        e_aware = pd.Timestamp(e).tz_localize(pytz.UTC) if pd.Timestamp(e).tz is None else pd.Timestamp(e).tz_convert(pytz.UTC)
    except Exception:
        s_aware = s
        e_aware = e

    # Verificar si este rango debe ser saltado por missing_ranges
    skip, reason = _should_skip_range(s_aware, e_aware, _load_missing_ranges())
    if skip:
        print(f"[INFO] ⏭️  Saltando rango {s} -> {e}: {reason}")
        return existing_htf, existing_ltf

    print(f"[INFO] Descargando rango y mergeando: {s} -> {e}")
    hnew, lnew = download_data_capital(epic, interval, s, e)

    # Verificar si se obtuvieron datos
    got_data = False
    if hnew is not None and not (hasattr(hnew, 'empty') and hnew.empty):
        got_data = True
    if lnew is not None and not (hasattr(lnew, 'empty') and lnew.empty):
        got_data = True

    if not got_data:
        print(f"[WARNING] No se obtuvieron datos para el rango {s} -> {e}")
        _register_missing_range(s_aware, e_aware, reason="no-data")
        return existing_htf, existing_ltf
    else:
        # Si ahora tenemos datos, limpiar de missing_ranges
        _clear_missing_range(s_aware, e_aware)

    # Asegurar que las nuevas tablas tienen Datetime como índice tz-aware
    try:
        if not (hnew is None) and not hnew.empty:
            if 'Datetime' in hnew.columns:
                hnew['Datetime'] = pd.to_datetime(hnew['Datetime'], utc=True)
                hnew.set_index('Datetime', inplace=True)
            elif isinstance(hnew.index, pd.DatetimeIndex) and hnew.index.tz is None:
                hnew.index = hnew.index.tz_localize(pytz.UTC)
    except Exception:
        pass

    try:
        if not (lnew is None) and not lnew.empty:
            if 'Datetime' in lnew.columns:
                lnew['Datetime'] = pd.to_datetime(lnew['Datetime'], utc=True)
                lnew.set_index('Datetime', inplace=True)
            elif isinstance(lnew.index, pd.DatetimeIndex) and lnew.index.tz is None:
                lnew.index = lnew.index.tz_localize(pytz.UTC)
    except Exception:
        pass

    # Cuando hacemos merges incrementales no forzamos el recálculo completo de indicadores
    merged_htf, merged_ltf = _merge_and_write_reports(existing_htf, existing_ltf, hnew, lnew, recalc=False)
    return merged_htf, merged_ltf



def calculate_indicators(data, buffer_days=30, recent_days=None):
    """
    Calcula indicadores técnicos esenciales y los agrega a los datos.
    Se realiza sobre los últimos (recent_days + buffer_days) días para asegurar que
    el primer día de recent_days tenga valores completos.
    """

    print("[INFO] Calculando indicadores esenciales...")

    if data is None or data.empty:
        print("[WARNING] DataFrame vacío, no se calculan indicadores.")
        return data

    data = data.copy()

    # ------------------ Robust timestamp normalization ------------------
    if not isinstance(data.index, pd.DatetimeIndex):
        if 'Datetime' in data.columns:
            data['Datetime'] = pd.to_datetime(data['Datetime'], utc=True, errors='coerce')
            data = data.dropna(subset=['Datetime']).set_index('Datetime')
        else:
            try:
                coerced = pd.to_datetime(data.index, utc=True, errors='coerce')
                data.index = coerced
                data = data[~data.index.isna()]
            except Exception:
                pass

    if isinstance(data.index, pd.DatetimeIndex) and data.index.tz is None:
        try:
            data.index = data.index.tz_localize(pytz.UTC)
        except Exception:
            try:
                data.index = data.index.tz_convert(pytz.UTC)
            except Exception:
                pass

    if data.empty:
        print("[ERROR] No hay datos válidos tras normalizar timestamps; se omiten indicadores.")
        return data

    # Calcular cutoff_date de forma segura (evitar NaT)
    idx_max = data.index.max()
    if recent_days is not None:
        if pd.isna(idx_max):
            print("[WARNING] data.index.max() es NaT; se omite el filtrado por cutoff_date.")
        else:
            cutoff_date = idx_max - pd.Timedelta(days=recent_days + buffer_days)
            data = data.loc[data.index >= cutoff_date].copy()

    # Convertir precios de diccionario a valores medios (si es necesario)
    def _extract_price(x):
        if isinstance(x, dict):
            bid = x.get('bid')
            ask = x.get('ask')
            if bid is not None and ask is not None:
                try:
                    return (float(bid) + float(ask)) / 2.0
                except Exception:
                    return np.nan
            for k in ('close', 'price', 'last'):
                if k in x:
                    try:
                        return float(x.get(k))
                    except Exception:
                        return np.nan
            return np.nan
        try:
            return float(x)
        except Exception:
            return np.nan

    # Normalizar precios
    for col in ['Close', 'Open', 'High', 'Low']:
        if col in data.columns:
            data[col] = data[col].apply(_extract_price)

    if 'Close' in data.columns:
        data = data.dropna(subset=['Close']).copy()

    if len(data) < 20:
        print(f"[WARNING] Solo {len(data)} registros, insuficientes para indicadores completos.")
        return data

    # --- 1️⃣ RSI ---
    print("  Calculando RSI...")
    data['RSI'] = RSIIndicator(data['Close'], window=10).rsi()
    data['RSI_5'] = RSIIndicator(data['Close'], window=5).rsi()
    data['RSI_7'] = RSIIndicator(data['Close'], window=7).rsi()

    # --- 2️⃣ EMAs y MACD ---
    print("  Calculando EMAs y MACD...")
    data['EMA_3'] = data['Close'].ewm(span=3, adjust=False).mean()
    data['EMA_6'] = data['Close'].ewm(span=6, adjust=False).mean()
    data['EMA_9'] = data['Close'].ewm(span=9, adjust=False).mean()
    data['EMA_14'] = data['Close'].ewm(span=14, adjust=False).mean()
    data['EMA_20'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA_50'] = data['Close'].ewm(span=50, adjust=False).mean()
    data['EMA_200'] = data['Close'].ewm(span=200, adjust=False).mean()

    data['MACD'] = data['EMA_6'] - data['EMA_14']
    data['MACD_Signal'] = data['MACD'].ewm(span=5, adjust=False).mean()
    data['MACD_Histogram'] = data['MACD'] - data['MACD_Signal']

    # --- 3️⃣ ATR ---
    print("  Calculando ATR...")
    high_low = data['High'] - data['Low']
    high_close_prev = (data['High'] - data['Close'].shift(1)).abs()
    low_close_prev = (data['Low'] - data['Close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
    data['ATR'] = tr.rolling(window=10, min_periods=1).mean()
    data['ATR_Pct'] = (data['ATR'] / data['Close']) * 100  # ATR como % del precio

    # --- 4️⃣ VolumeChange ---
    data['VolumeChange'] = data['Volume'].pct_change().replace([np.inf, -np.inf], 0).fillna(0)

    # --- 5️⃣ Log Returns ---
    data['log_return'] = np.log(data['Close'] / data['Close'].shift(1))

    # --- 6️⃣ STOCH (Estocástico) ---
    print("  Calculando Estocástico...")
    stoch = StochasticOscillator(high=data['High'], low=data['Low'], close=data['Close'], window=14, smooth_window=3)
    data['STOCH'] = stoch.stoch()

    # --- 7️⃣ Bandas de Bollinger ---
    print("  Calculando Bollinger Bands...")
    bb = BollingerBands(close=data['Close'], window=20, window_dev=2)
    data['BB_width'] = bb.bollinger_wband()

    # --- 8️⃣ ADX (Average Directional Index) ---
    print("  Calculando ADX...")
    from ta.trend import ADXIndicator
    adx = ADXIndicator(high=data['High'], low=data['Low'], close=data['Close'], window=14)
    data['ADX'] = adx.adx()

    # --- 9️⃣ OBV (On-Balance Volume) ---
    print("  Calculando OBV...")
    from ta.volume import OnBalanceVolumeIndicator
    obv = OnBalanceVolumeIndicator(close=data['Close'], volume=data['Volume'])
    data['OBV'] = obv.on_balance_volume()
    data['OBV_Trend'] = np.where(data['OBV'] > data['OBV'].shift(1), 1,
                                   np.where(data['OBV'] < data['OBV'].shift(1), -1, 0))

    # --- 🔟 Volume_Ratio ---
    data['Volume_Ratio'] = data['Volume'] / data['Volume'].rolling(window=20, min_periods=1).mean()

    # --- 1️⃣1️⃣ Market_Regime ---
    data['Market_Regime'] = np.where(data['ADX'] > 25, 'TRENDING',
                                      np.where(data['ADX'] > 20, 'RANGING', 'CHOPPY'))

    # Limpiar NaN y valores extremos
    data.replace([np.inf, -np.inf], 0, inplace=True)
    data.fillna(0, inplace=True)

    print(f"[INFO] ✅ Indicadores calculados para {len(data)} registros")
    return data


def prepare_for_export(historical_data, data, mode=None):
    """
    Prepara y exporta ambos DataFrames: históricos y de 1 minuto.
    Trunca a las ventanas móviles especificadas para mantener archivo ligero.
    El parámetro mode es ignorado internamente (siempre sobreescribe).
    """
    print("[INFO] Preparando datos para exportación...")

    # 🔧 TRUNCAR a ventanas móviles (mantener solo últimas N velas)
    if not historical_data.empty:
        original_htf = len(historical_data)
        historical_data = historical_data.tail(HTF_WINDOW)
        if original_htf > HTF_WINDOW:
            print(f"[INFO] 📊 HTF truncado: {original_htf} → {HTF_WINDOW} velas (últimas {HTF_WINDOW/24:.1f} días)")

    if not data.empty:
        original_ltf = len(data)
        data = data.tail(LTF_WINDOW)
        if original_ltf > LTF_WINDOW:
            print(f"[INFO] 📊 LTF truncado: {original_ltf} → {LTF_WINDOW} velas (últimas {LTF_WINDOW/60:.1f}h)")

    # Convertir índice Datetime a columna y luego a milisegundos
    htf_for_json = historical_data.reset_index()
    ltf_for_json = data.reset_index() if not data.empty else pd.DataFrame()

    if 'Datetime' in htf_for_json.columns:
        htf_for_json['Datetime'] = htf_for_json['Datetime'].apply(lambda x: int(x.timestamp() * 1000) if pd.notna(x) else 0)
    if not ltf_for_json.empty and 'Datetime' in ltf_for_json.columns:
        ltf_for_json['Datetime'] = ltf_for_json['Datetime'].apply(lambda x: int(x.timestamp() * 1000) if pd.notna(x) else 0)

    json_data = {
        "historical_data": htf_for_json.to_dict(orient="records"),
        "data": ltf_for_json.to_dict(orient="records") if not ltf_for_json.empty else []
    }

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Reports")
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, "ETHUSD_CapitalData.json")

    # 💾 GUARDAR EN FORMATO PARQUET (eficiente, rápido) ANTES de convertir a JSON
    try:
        if not historical_data.empty:
            htf_parquet = os.path.join(output_dir, 'ethusd_htf_immutable.parquet')
            historical_data.to_parquet(htf_parquet, compression='snappy', index=True)
            print(f"[INFO] ✅ Parquet HTF guardado: {len(historical_data)} velas")

        if not data.empty:
            ltf_parquet = os.path.join(output_dir, 'ethusd_ltf_7d.parquet')
            data.to_parquet(ltf_parquet, compression='snappy', index=True)
            print(f"[INFO] ✅ Parquet LTF guardado: {len(data)} velas")
    except Exception as e:
        print(f"[WARNING] ⚠️ No se pudo guardar Parquet en prepare_for_export: {e}")

    # 💾 GUARDAR JSON (legacy)
    with open(output_file, 'w') as f:
        json.dump(json_data, f, indent=4)

    print(f"[INFO] ✅ Datos guardados correctamente en {output_file}")


def calculate_ltf_indicators(data):
    """
    Función específica para calcular indicadores en LTF (Low Time Frame - 1M candles).
    Optimizada para datos de minutos con parámetros más rápidos.
    """
    # Para LTF usamos buffer mínimo ya que son datos de corto plazo
    return calculate_indicators(data, buffer_days=2, recent_days=None)

# Función principal para ejecución como script
if __name__ == "__main__":
    import pandas as pd
    from datetime import datetime, timezone, timedelta

    print("=== EJECUTANDO DATAETH.PY ===")

    try:
        # Configurar fechas
        end_date = datetime.now(timezone.utc)
        htf_start = end_date - timedelta(days=5*365)  # 5 años para HTF (HOUR)
        ltf_start = end_date - timedelta(days=7)      # 7 días para LTF (MINUTE)

        print(f'HTF: {htf_start.date()} → {end_date.date()} (HOUR)')
        print(f'LTF: {ltf_start.date()} → {end_date.date()} (MINUTE)')

        # Descargar datos
        print('1. Descargando datos HTF (HOUR)...')
        htf_data, htf_meta = download_data_capital('ETHUSD', 'HOUR', htf_start, end_date)
        print(f'   ✅ HTF: {len(htf_data)} registros descargados')

        print('2. Descargando datos LTF (MINUTE)...')
        ltf_data, ltf_meta = download_data_capital('ETHUSD', 'MINUTE', ltf_start, end_date)
        print(f'   ✅ LTF: {len(ltf_data)} registros descargados')

        # 🔥 CALCULAR INDICADORES (lo que faltaba!)
        print('\n3. Calculando indicadores HTF...')
        htf_data = calculate_indicators(htf_data, buffer_days=30, recent_days=None)
        print(f'   ✅ HTF con indicadores: {len(htf_data)} registros')

        print('4. Calculando indicadores LTF...')
        ltf_data = calculate_indicators(ltf_data, buffer_days=2, recent_days=None)
        print(f'   ✅ LTF con indicadores: {len(ltf_data)} registros')

        # Exportar manualmente
        print('\n5. Exportando datos...')
        import json

        export_data = {
            'historical_data': [],
            'ltf_data': []
        }

        # Convertir HTF
        for idx, row in htf_data.iterrows():
            record = {
                'timestamp': idx.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
                'Open': float(row['Open']),
                'High': float(row['High']),
                'Low': float(row['Low']),
                'Close': float(row['Close']),
                'Volume': float(row['Volume'])
            }
            for col in row.index:
                if col not in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    try:
                        record[col] = float(row[col]) if pd.notna(row[col]) else 0.0
                    except:
                        record[col] = 0.0
            export_data['historical_data'].append(record)

        # Convertir LTF
        for idx, row in ltf_data.iterrows():
            record = {
                'timestamp': idx.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
                'Open': float(row['Open']),
                'High': float(row['High']),
                'Low': float(row['Low']),
                'Close': float(row['Close']),
                'Volume': float(row['Volume'])
            }
            for col in row.index:
                if col not in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    try:
                        record[col] = float(row[col]) if pd.notna(row[col]) else 0.0
                    except:
                        record[col] = 0.0
            export_data['ltf_data'].append(record)

        # Guardar JSON (legacy)
        output_path = os.path.join(os.path.dirname(__file__), "Reports", "ETHUSD_CapitalData.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)

        print(f'✅ JSON exportado: {len(export_data["historical_data"])} HTF + {len(export_data["ltf_data"])} LTF')

        # 🔥 GUARDAR PARQUET (principal)
        print('\n6. Guardando archivos Parquet...')
        reports_dir = os.path.join(os.path.dirname(__file__), "Reports")

        # HTF Parquet
        htf_parquet_path = os.path.join(reports_dir, "ethusd_htf_immutable.parquet")
        htf_data.to_parquet(htf_parquet_path, engine='pyarrow', compression='snappy')
        print(f'   ✅ HTF guardado: {htf_parquet_path} ({len(htf_data)} velas)')

        # LTF Parquet
        ltf_parquet_path = os.path.join(reports_dir, "ethusd_ltf_7d.parquet")
        ltf_data.to_parquet(ltf_parquet_path, engine='pyarrow', compression='snappy')
        print(f'   ✅ LTF guardado: {ltf_parquet_path} ({len(ltf_data)} velas)')

        print('\n🚀 DATAETH COMPLETADO EXITOSAMENTE')

    except Exception as e:
        print(f'❌ Error en DataEth.py: {e}')
        import traceback
        traceback.print_exc()
        exit(1)
