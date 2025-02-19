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

def add_scaled_features(data, scaler_stats, model_features):
    """
    Para cada característica que el modelo requiere, agrega una nueva columna 'scaled_<feature>'
    con el valor escalado, dejando intactos los valores crudos.
    """
    for i, feature in enumerate(model_features):
        if feature in data.columns:
            data[f"scaled_{feature}"] = (data[feature] - scaler_stats["mean"][i]) / scaler_stats["scale"][i]
        else:
            print(f"[WARNING] La característica {feature} no se encuentra en los datos.")
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

# Cargar modelo y estadísticas del escalador (usado en el modelo de Markov)
MODEL_FILE = "msm_model.pkl"
with open(MODEL_FILE, 'rb') as f:
    model_data = pickle.load(f)
scaler_stats = model_data['scaler_stats']
model_features = model_data['features']

# Obtener EPIC
epic = get_epic(ticker)
if epic:
    # Para el cálculo correcto, descargamos datos para total_days (395 días)
    # Nota: buffer_months se mantiene solo para la descarga si se requiere (en este caso usamos total_days directamente)
    end_date = datetime.now(pytz.UTC)
    start_date = end_date - timedelta(days=total_days)
    print(f"[INFO] Descargando datos desde {start_date.strftime('%Y-%m-%d')} hasta {end_date.strftime('%Y-%m-%d')}")
    data = download_data_capital(epic, interval, start_date, end_date)
    if data.empty:
        print("[ERROR] No se obtuvieron datos de la API de Capital.com.")
    else:
        # Calcular indicadores usando el conjunto completo de total_days (395 días)
        data = calculate_indicators(data, buffer_days=buffer_days, recent_days=total_days)
        
        # Filtrar para quedarnos únicamente con los últimos period_days (365 días)
        start_filter_date = end_date - timedelta(days=period_days)
        start_filter_date = pd.Timestamp(start_filter_date).tz_localize(None)
        print(f"[INFO] Filtrando datos a partir de {start_filter_date.strftime('%Y-%m-%d')}")
        data = data[data.index >= start_filter_date]
        
        # Preparar datos para exportación (convertir 'Datetime' a timestamp en milisegundos)
        data = prepare_for_export(data)

        # Crear la carpeta "Reports" dentro del directorio actual, si no existe
        current_directory = os.getcwd()
        reports_dir = os.path.join(current_directory, "Reports")
        if not os.path.exists(reports_dir):
            os.makedirs(reports_dir)

        # Definir la ruta del archivo JSON de salida usando la ruta relativa
        output_file = os.path.join(reports_dir, f'{ticker.replace("-", "_")}_CapitalData.json')

        # Exportar en un único documento JSON
        with open(output_file, 'w') as f:
            json.dump({"data": data.to_dict(orient="records")}, f, indent=4)
        print(f"[INFO] Archivo generado: {output_file}")
