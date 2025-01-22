import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import AverageTrueRange
import json
import yfinance as yf
import pytz
import pickle

# Configurable variables
ticker = "ETH-USD"
interval = "1h"
period = "1y"  # Período solicitado
segment_days = 10  # Límite por segmento debido a restricciones de Yahoo Finance

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
    """
    Calcula indicadores técnicos para el DataFrame.
    """
    print("[INFO] Calculando indicadores técnicos...")
    required_columns = ['High', 'Low', 'Close', 'Open', 'Volume']
    for col in required_columns:
        if col not in data.columns:
            raise ValueError(f"[ERROR] La columna {col} no se encuentra en el DataFrame.")

    # Calcular indicadores técnicos
    rsi_indicator = RSIIndicator(close=data['Close'], window=14)
    data['RSI'] = rsi_indicator.rsi()

    macd = MACD(close=data['Close'])
    data['MACD'] = macd.macd()
    data['MACD_Signal'] = macd.macd_signal()

    atr = AverageTrueRange(high=data['High'], low=data['Low'], close=data['Close'], window=14)
    data['ATR'] = atr.average_true_range()

    data['IntraDayVariation'] = (data['High'] - data['Low']) / data['Open']
    data['LogReturn'] = np.log(data['Close'] / data['Open'])
    data['AveragePrice'] = (data['High'] + data['Low'] + data['Close']) / 3

    # Cálculo del cambio en el volumen
    if 'Volume' in data.columns:
        data['VolumeChange'] = data['Volume'].pct_change().fillna(0)
        daily_volume = data.groupby(data['Datetime'].dt.date)['Volume'].transform('sum')
        data['AvgDailyVolume'] = daily_volume.rolling(window=7).mean()

    # Filtrar datos
    start_date_original = datetime.now(pytz.UTC) - timedelta(days=period_days)
    data = data[data['Datetime'] >= start_date_original]

    return data


def prepare_for_export(data):
    """
    Convierte columnas datetime a formato serializable.
    """
    for col in data.columns:
        if pd.api.types.is_datetime64_any_dtype(data[col]):
            # Convertir 'Datetime' a timestamps en milisegundos para JSON
            if col == 'Datetime':
                data[col] = data[col].apply(lambda x: int(x.timestamp() * 1000))
            else:
                data[col] = data[col].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return data



def scale_features(data, scaler_stats, model_features):
    """
    Escala las características del modelo utilizando las estadísticas del escalador.
    """
    print("[INFO] Aplicando el escalador a las características del modelo...")

    # Separar 'Datetime' y otras columnas no escalables
    datetime_column = data['Datetime']
    extra_columns = [col for col in data.columns if col not in model_features and col != 'Datetime']

    # Escalar solo las columnas esperadas por el modelo
    scaled_data = data[model_features].copy()
    for i, feature in enumerate(model_features):
        scaled_data[feature] = (scaled_data[feature] - scaler_stats['mean'][i]) / scaler_stats['scale'][i]

    print("[INFO] Escalado aplicado con éxito para las características del modelo.")

    # Reincorporar columnas adicionales y 'Datetime'
    for col in extra_columns:
        scaled_data[col] = data[col]
    scaled_data['Datetime'] = datetime_column

    return scaled_data


MODEL_FILE = "RatzoMode.pkl"

# Cargar modelo (que contiene scaler_stats y features)
with open(MODEL_FILE, 'rb') as f:
    model_data = pickle.load(f)

# Extraer scaler_stats y model_features del modelo
scaler_stats = model_data['scaler_stats']
model_features = model_data['features']

# Flujo principal
data = yf.download(ticker, interval=interval, period=period)
if data.empty:
    print("[ERROR] No se obtuvieron datos.")
else:
    # 1) Procesar y calcular indicadores
    data = process_data(data, ticker)
    data = calculate_indicators(data, period_days=365, buffer_days=68)

    # 2) Escalar los datos con las estadísticas y características del modelo
    print("[INFO] Aplicando escalado real al DataFrame...")
    data = scale_features(data, scaler_stats, model_features)

    # 3) Preparar datos para exportar (fechas → milisegundos)
    data = prepare_for_export(data)

    # 4) Exportar
    output_file = f'/home/hobeat/MoneyMakers/Reports/{ticker.replace("-", "_")}_1Y1HM2.json'
    with open(output_file, 'w') as f:
        json.dump({"data": data.to_dict(orient="records")}, f, indent=4)
    print(f"[INFO] Archivo generado: {output_file}")