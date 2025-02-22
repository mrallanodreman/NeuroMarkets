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
from VisorTecnico import TechnicalAnalysis  # Usamos el cálculo de RSI correcto

# Configuración
ticker = "ETHUSD"
interval = "HOUR"  # Capital.com usa "HOUR", "MINUTE", "DAY"
period_days = 365              # Días finales que nos interesan para exportar
buffer_days = 30               # Buffer adicional para cálculos de indicadores
total_days = period_days + buffer_days  # Total de días a descargar (395 en este ejemplo)
segment_days = 10  # Segmentos de descarga

# Inicializar API Capital.com
capital_ops = CapitalOP()
capital_ops.ensure_authenticated()

def get_epic(symbol):
    """
    Obtiene el EPIC correspondiente a un símbolo de mercado (ej. ETH-EUR).
    """
    print(f"[INFO] Buscando EPIC para {symbol} en Capital.com...")
    markets_url = f"{capital_ops.base_url}/api/v1/markets?searchTerm={symbol}"
    headers = {
        "Content-Type": "application/json",
        "X-CAP-API-KEY": capital_ops.api_key,
        "CST": capital_ops.session_token,
        "X-SECURITY-TOKEN": capital_ops.x_security_token
    }
    response = requests.get(markets_url, headers=headers)
    if response.status_code == 200:
        markets = response.json().get("markets", [])
        if markets:
            epic = markets[0].get("epic")
            print(f"[INFO] EPIC encontrado: {epic}")
            return epic
        else:
            print("[ERROR] No se encontró un EPIC para este símbolo.")
            return None
    else:
        print(f"[ERROR] Fallo en la búsqueda de EPIC: {response.status_code} - {response.text}")
        return None

def download_data_capital(epic, interval, start_date, end_date):
    """
    Descarga datos históricos desde Capital.com.
    """
    all_data = []
    current_date = start_date
    while current_date < end_date:
        seg_end_date = min(current_date + timedelta(days=segment_days), end_date)
        print(f"[INFO] Descargando datos: {current_date.strftime('%Y-%m-%d')} - {seg_end_date.strftime('%Y-%m-%d')}")
        prices_url = f"{capital_ops.base_url}/api/v1/prices/{epic}?resolution={interval}&from={current_date.strftime('%Y-%m-%dT%H:%M:%S')}&to={seg_end_date.strftime('%Y-%m-%dT%H:%M:%S')}"
        headers = {
            "Content-Type": "application/json",
            "X-CAP-API-KEY": capital_ops.api_key,
            "CST": capital_ops.session_token,
            "X-SECURITY-TOKEN": capital_ops.x_security_token
        }
        response = requests.get(prices_url, headers=headers)
        if response.status_code == 200:
            data = response.json().get("prices", [])
            if data:
                all_data.extend(data)
            else:
                print(f"[WARNING] No se encontraron datos para {current_date} - {seg_end_date}")
        else:
            print(f"[ERROR] Fallo en la descarga: {response.status_code} - {response.text}")
        current_date = seg_end_date

    if all_data:
        df = pd.DataFrame(all_data)
        df.rename(columns={
            'snapshotTimeUTC': 'Datetime',
            'openPrice': 'Open',
            'highPrice': 'High',
            'lowPrice': 'Low',
            'closePrice': 'Close',
            'lastTradedVolume': 'Volume'
        }, inplace=True)
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        df.set_index("Datetime", inplace=True)
        df.sort_index(inplace=True)

        # Convert the last hour's data to minute intervals
        last_hour = df.index[-1]
        minute_prices_url = f"{capital_ops.base_url}/api/v1/prices/{epic}?resolution=MINUTE&from={last_hour.strftime('%Y-%m-%dT%H:%M:%S')}&to={(last_hour + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')}"
        response = requests.get(minute_prices_url, headers=headers)
        if response.status_code == 200:
            minute_data = response.json().get("prices", [])
            if minute_data:
                minute_df = pd.DataFrame(minute_data)
                minute_df.rename(columns={
                    'snapshotTimeUTC': 'Datetime',
                    'openPrice': 'Open',
                    'highPrice': 'High',
                    'lowPrice': 'Low',
                    'closePrice': 'Close',
                    'lastTradedVolume': 'Volume'
                }, inplace=True)
                minute_df["Datetime"] = pd.to_datetime(minute_df["Datetime"])
                minute_df.set_index("Datetime", inplace=True)
                minute_df.sort_index(inplace=True)

                # Remove the last row from the hourly data
                df = df.iloc[:-1]

                # Append the minute-resolution data using concat
                df = pd.concat([df, minute_df])

        return df
    else:
        return pd.DataFrame()

def calculate_indicators(data, buffer_days=30, recent_days=total_days):
    """
    Calcula indicadores técnicos esenciales y los agrega a los datos.
    Se realiza sobre los últimos (period_days + buffer_days) días para que el buffer
    garantice que el primer día de los últimos period_days tenga valores completos.
    """
    print("[INFO] Calculando indicadores esenciales...")
    # Usamos los últimos 'total_days' (395 días) para calcular los indicadores
    cutoff_date = data.index.max() - pd.Timedelta(days=recent_days)
    data = data.loc[data.index >= cutoff_date].copy()
    
    # Si los valores son diccionarios, extraer la media
    for col in ["Close", "Open", "High", "Low"]:
        if isinstance(data[col].iloc[0], dict):
            print(f"[INFO] Extrayendo valores medios de precios en {col}...")
            data[col] = data[col].apply(lambda x: (x["bid"] + x["ask"]) / 2 if isinstance(x, dict) else x)
    
    # --- 1️⃣ RSI ---
    # Calculamos el RSI utilizando el método de VisorTecnico (se usa period=5 y smooth_factor=3)
    data["RSI"] = TechnicalAnalysis.calculate_rsi(data, period=5, smooth_factor=3)
    
    # --- 2️⃣ MACD ---
    fast_period, slow_period, signal_period = 12, 26, 9
    data["EMA_12"] = data["Close"].ewm(span=fast_period, adjust=False).mean()
    data["EMA_26"] = data["Close"].ewm(span=slow_period, adjust=False).mean()
    data["MACD"] = data["EMA_12"] - data["EMA_26"]
    data["MACD_Signal"] = data["MACD"].ewm(span=signal_period, adjust=False).mean()
    
    # --- 3️⃣ ATR ---
    atr_period = 14
    high_low = data["High"] - data["Low"]
    high_close_prev = abs(data["High"] - data["Close"].shift(1))
    low_close_prev = abs(data["Low"] - data["Close"].shift(1))
    tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
    data["ATR"] = tr.rolling(window=atr_period, min_periods=1).mean()
    
    # --- 4️⃣ VolumeChange ---
    data["VolumeChange"] = data["Volume"].pct_change().replace([np.inf, -np.inf], 0).fillna(0)
    
    # Limpiar NaN y valores extremos
    data.replace([np.inf, -np.inf], 0, inplace=True)
    data.fillna(0, inplace=True)
    
    # Calcular log_return
    data['log_return'] = np.log(data['Close'] / data['Close'].shift(1))
    
    # Calcular STOCH (usando ta.momentum.StochasticOscillator)
    stoch = StochasticOscillator(high=data['High'], low=data['Low'], close=data['Close'], window=14, smooth_window=3)
    data['STOCH'] = stoch.stoch()
    
    # Calcular EMA de 50 periodos
    data['EMA_50'] = data['Close'].ewm(span=50, adjust=False).mean()
    
    # Calcular ancho de Bandas de Bollinger (BB_width)
    bb = BollingerBands(close=data['Close'], window=20, window_dev=2)
    data['BB_width'] = bb.bollinger_wband()
    
    print("[INFO] Indicadores esenciales calculados correctamente.")
    print("[DEBUG] Primeros 10 registros después de calcular indicadores:")
    print(data[["RSI", "MACD", "ATR", "VolumeChange", "Close"]].head(10))
    return data


def prepare_for_export(data):
    """
    Prepara los datos antes de exportarlos a JSON.
    Convierte la columna 'Datetime' a un timestamp en milisegundos.
    """
    print("[INFO] Preparando datos para exportación...")
    if 'Datetime' in data.columns:
        data['Datetime'] = data['Datetime'].apply(lambda x: int(x.timestamp() * 1000))
    print("[INFO] Datos listos para exportar.")
    return data

# Obtener EPIC
epic = get_epic(ticker)
if epic:
    # Descargar datos de los últimos días
    end_date = datetime.now(pytz.UTC)
    start_date = end_date - timedelta(days=total_days)
    print(f"[INFO] Descargando datos desde {start_date.strftime('%Y-%m-%d')} hasta {end_date.strftime('%Y-%m-%d')}")

    data = download_data_capital(epic, interval, start_date, end_date)
    if data.empty:
        print("[ERROR] No se obtuvieron datos de la API de Capital.com.")
    else:
        # Calcular indicadores
        data = calculate_indicators(data, buffer_days=buffer_days, recent_days=total_days)
        
        # Filtrar datos de los últimos period_days
        start_filter_date = end_date - timedelta(days=period_days)
        start_filter_date = pd.Timestamp(start_filter_date).tz_localize(None)
        print(f"[INFO] Filtrando datos desde {start_filter_date.strftime('%Y-%m-%d')}")
        data = data[data.index >= start_filter_date]
        
        # Preparar datos para exportación
        data = prepare_for_export(data)

        # Guardar archivo JSON con clave 'data'
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Reports")
        os.makedirs(output_dir, exist_ok=True)

        output_file = os.path.join(output_dir, "ETHUSD_CapitalData.json")
        json_data = {"data": data.to_dict(orient="records")}

        with open(output_file, 'w') as f:
            json.dump(json_data, f, indent=4)

        if os.path.exists(output_file):
            print(f"[INFO] ✅ Datos guardados correctamente en {output_file}")
        else:
            print(f"[ERROR] ❌ No se pudo guardar el archivo en {output_file}")
