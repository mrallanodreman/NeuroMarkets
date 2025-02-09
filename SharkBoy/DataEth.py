import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import BollingerBands
from ta.momentum import StochasticOscillator


from ta.trend import MACD
from ta.volatility import AverageTrueRange
import json
import yfinance as yf
import pytz
import pickle

# Variables configurables
ticker = "ETH-EUR"
interval = "1h"
# Para el período de interés se definirá period_days y además buffer_days para los cálculos de indicadores.
period_days = 365      # Período final deseado
buffer_days = 14       # Días adicionales para cálculos de indicadores (ventanas móviles, etc.)
# Total de días a descargar será la suma
total_days = period_days + buffer_days

# Límite por segmento debido a restricciones de Yahoo Finance
segment_days = 10

def download_data_in_segments(ticker, interval, start_date, end_date, segment_days):
    """
    Descarga datos de Yahoo Finance en segmentos (por ejemplo, de 10 días) y los concatena.
    """
    current_date = start_date
    all_data = []
    while current_date < end_date:
        seg_end_date = min(current_date + timedelta(days=segment_days), end_date)
        print(f"[INFO] Descargando segmento: {current_date.strftime('%Y-%m-%d')} - {seg_end_date.strftime('%Y-%m-%d')}")
        seg_data = yf.download(ticker,
                               interval=interval,
                               start=current_date.strftime('%Y-%m-%d'),
                               end=seg_end_date.strftime('%Y-%m-%d'))
        if not seg_data.empty:
            all_data.append(seg_data)
        else:
            print(f"[WARNING] Segmento vacío: {current_date.strftime('%Y-%m-%d')} - {seg_end_date.strftime('%Y-%m-%d')}")
        current_date = seg_end_date
    if all_data:
        data = pd.concat(all_data)
        data = data[~data.index.duplicated()]
        return data
    else:
        return pd.DataFrame()

def process_data(data, ticker):
    """
    Procesa los datos descargados y genera un DataFrame limpio.
    """
    # Depuración para verificar estructura inicial
    print(data.head())
    # Aplanar columnas si tienen MultiIndex
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = ['_'.join(map(str, col)).strip() for col in data.columns]

    # Generar dinámicamente el column_map basado en el ticker
    def generate_column_map(ticker):
        base_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        return {f"{col}_{ticker}": col for col in base_columns}

    # Generar el column_map específico para el ticker actual
    column_map = generate_column_map(ticker)
    
    # Renombrar las columnas usando el column_map
    data.rename(columns=column_map, inplace=True)

    # Detectar y convertir la clave de tiempo correcta
    if 'Datetime' in data.columns:
        time_column = 'Datetime'
    elif 'Date' in data.columns:
        time_column = 'Date'
    elif isinstance(data.index, pd.DatetimeIndex):
        print("[INFO] Usando el índice como clave de tiempo.")
        data = data.reset_index()  # Convertir índice a columna
        time_column = 'Datetime'
    else:
        raise ValueError("[ERROR] No se encontró una clave de tiempo válida.")

    # Uniformar la columna de tiempo a 'Datetime'
    data['Datetime'] = pd.to_datetime(data[time_column], errors='coerce')

    # Asegurar que 'Datetime' sea tz-aware
    if data['Datetime'].dt.tz is None:
        data['Datetime'] = data['Datetime'].dt.tz_localize('UTC')

    # Eliminar duplicados y valores inválidos
    data = data[~data['Datetime'].duplicated()]
    data.dropna(subset=['Datetime'], inplace=True)

    # Restablecer índice
    data.reset_index(drop=True, inplace=True)

    # Corregir volúmenes
    data = correct_volumes(data)

    print("[INFO] Datos procesados correctamente.")
    return data


def correct_volumes(data):
    """
    Corrige los volúmenes en 0 mediante interpolación basada en valores válidos anteriores y posteriores.
    """
    if 'Volume' not in data.columns:
        print("[WARNING] Columna 'Volume' no encontrada. Saltando corrección.")
        return data
    zero_indices = data[data['Volume'] == 0].index
    for idx in zero_indices:
        prev_value = data.loc[:idx, 'Volume'][data['Volume'] != 0].last_valid_index()
        next_value = data.loc[idx:, 'Volume'][data['Volume'] != 0].first_valid_index()
        prev_volume = data.loc[prev_value, 'Volume'] if prev_value is not None else 0
        next_volume = data.loc[next_value, 'Volume'] if next_value is not None else 0
        corrected_volume = int((prev_volume + next_volume) / 2)
        data.at[idx, 'Volume'] = corrected_volume
    print("[INFO] Volúmenes corregidos.")
    return data

def calculate_indicators(data, period_days=365, buffer_days=14):
    print("[INFO] Calculando indicadores técnicos...")

    # Calcular RSI
    rsi_indicator = RSIIndicator(close=data['Close'], window=14)
    data['RSI'] = rsi_indicator.rsi()

    # Calcular MACD
    macd = MACD(close=data['Close'])
    data['MACD'] = macd.macd()
    data['MACD_Signal'] = macd.macd_signal()

    # Calcular ATR
    atr = AverageTrueRange(high=data['High'], low=data['Low'], close=data['Close'], window=14)
    data['ATR'] = atr.average_true_range()

    # Calcular log_return y otras métricas
    data['log_return'] = np.log(data['Close'] / data['Open'])
    data['IntraDayVariation'] = (data['High'] - data['Low']) / data['Open']
    data['AveragePrice'] = (data['High'] + data['Low'] + data['Close']) / 3

    # Calcular EMA_50
    ema_50 = EMAIndicator(close=data['Close'], window=50)
    data['EMA_50'] = ema_50.ema_indicator()

    # Calcular Bollinger Bands Width
    bb = BollingerBands(close=data['Close'], window=20, window_dev=2)
    data['BB_width'] = (bb.bollinger_hband() - bb.bollinger_lband()) / data['Close']

    # Calcular STOCH
    stoch = StochasticOscillator(high=data['High'], low=data['Low'], close=data['Close'], window=14, smooth_window=3)
    data['STOCH'] = stoch.stoch()

    # Verificación final de columnas
    expected_columns = ['log_return', 'STOCH', 'EMA_50', 'BB_width']
    missing_cols = [col for col in expected_columns if col not in data.columns]

    if missing_cols:
        print(f"[ERROR] Faltan las siguientes columnas en `calculate_indicators()`: {missing_cols}")
        for col in missing_cols:
            data[col] = 0  # Rellenamos con ceros para evitar errores.

    print("[INFO] Indicadores calculados correctamente.")
    print("[DEBUG] Columnas finales en DataFrame:", list(data.columns))  
    return data


def prepare_for_export(data):
    print("[INFO] Preparando datos para exportación...")

    expected_columns = ['log_return', 'STOCH', 'EMA_50', 'BB_width']
    missing_cols = [col for col in expected_columns if col not in data.columns]

    if missing_cols:
        print(f"[ERROR] Faltan las siguientes columnas antes de exportar: {missing_cols}")
        for col in missing_cols:
            data[col] = 0

    # Convertir las fechas correctamente
    if 'Datetime' in data.columns:
        data['Datetime'] = data['Datetime'].apply(lambda x: int(x.tz_convert('UTC').timestamp() * 1000))

    print("[INFO] Datos listos para exportar. Columnas finales:", list(data.columns))  
    return data




def scale_features(data, scaler_stats, model_features):
    """
    Escala las características del modelo utilizando las estadísticas del escalador.
    """
    print("[INFO] Aplicando el escalador a las características del modelo...")

    datetime_column = data['Datetime']
    extra_columns = [col for col in data.columns if col not in model_features and col != 'Datetime']

    scaled_data = data[model_features].copy()
    for i, feature in enumerate(model_features):
        scaled_data[feature] = (scaled_data[feature] - scaler_stats['mean'][i]) / scaler_stats['scale'][i]

    print("[INFO] Escalado aplicado con éxito para las características del modelo.")

    for col in extra_columns:
        scaled_data[col] = data[col]
    scaled_data['Datetime'] = datetime_column

    return scaled_data

# Cargar el modelo (que contiene scaler_stats y las características requeridas)
MODEL_FILE = "msm_model.pkl"
with open(MODEL_FILE, 'rb') as f:
    model_data = pickle.load(f)

scaler_stats = model_data['scaler_stats']
model_features = model_data['features']

# Flujo principal
end_date = datetime.now(pytz.UTC)
start_date = end_date - timedelta(days=total_days)

print(f"[INFO] Descargando datos desde {start_date.strftime('%Y-%m-%d')} hasta {end_date.strftime('%Y-%m-%d')}")
data = download_data_in_segments(ticker, interval, start_date, end_date, segment_days)

if data.empty:
    print("[ERROR] No se obtuvieron datos.")
else:
    # 1) Procesar y limpiar los datos
    data = process_data(data, ticker)
    # 2) Calcular indicadores técnicos usando los días de buffer
    data = calculate_indicators(data, period_days=period_days, buffer_days=buffer_days)
    # 3) Escalar las características según el modelo
    print("[INFO] Aplicando escalado real al DataFrame...")
    data = scale_features(data, scaler_stats, model_features)
    # 4) Preparar los datos para exportar (convertir fechas)
    data = prepare_for_export(data)
    # 5) Exportar a JSON
    output_file = f'/home/hobeat/MoneyMakers/Reports/{ticker.replace("-", "_")}_1Y1HM2.json'
    with open(output_file, 'w') as f:
        json.dump({"data": data.to_dict(orient="records")}, f, indent=4)
    print(f"[INFO] Archivo generado: {output_file}")