import os
import pandas as pd
import numpy as np
from datetime import datetime
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import AverageTrueRange
import json
import yfinance as yf
import joblib

# Configuración
ticker = "BTC-USD"
interval = "1h"
buffer_period = "2y"  # Incluye 1 año adicional para el cálculo de indicadores
desired_period = "1y"  # Período real deseado
output_file = f"/home/hobeat/MoneyMakers/Reports/{ticker.replace('-', '_')}_IndicadoresCondensados.json"
model_file = "/home/hobeat/MoneyMakers/BTCMD1.pkl"

# Funciones
def validate_columns(data, required_columns):
    """
    Valida que las columnas necesarias estén presentes en los datos descargados.
    """
    print("[INFO] Validando columnas necesarias en los datos...")
    for col in required_columns:
        if col not in data.columns:
            raise ValueError(f"[ERROR] La columna requerida '{col}' no está presente en los datos descargados.")

def process_data(data):
    """
    Procesa los datos descargados de YFinance y prepara las columnas necesarias.
    """
    print("[INFO] Procesando datos iniciales...")

    # Paso 1: Asegurar que los datos no estén vacíos
    if data.empty:
        raise ValueError("[ERROR] Los datos descargados están vacíos.")

    # Paso 2: Simplificar el MultiIndex
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = ['_'.join(map(str, col)).strip() for col in data.columns]
    print(f"[DEBUG] Columnas después de simplificar el MultiIndex: {list(data.columns)}")

    # Paso 3: Renombrar columnas
    column_map = {
        'Close_BTC-USD': 'Close',
        'High_BTC-USD': 'High',
        'Low_BTC-USD': 'Low',
        'Open_BTC-USD': 'Open',
        'Volume_BTC-USD': 'Volume'
    }
    data.rename(columns=column_map, inplace=True)
    print(f"[DEBUG] Columnas renombradas: {list(data.columns)}")

    # Paso 4: Convertir el índice en columna `Datetime`
    data['Datetime'] = data.index
    data['Datetime'] = pd.to_datetime(data['Datetime'], errors='coerce')

    # Paso 5: Validar columnas necesarias
    required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in required_columns:
        if col not in data.columns:
            raise ValueError(f"[ERROR] La columna requerida '{col}' no está presente en los datos procesados.")

    # Paso 6: Eliminar duplicados y valores inválidos
    data = data.dropna(subset=required_columns)
    data = data[(data['Close'] > 0) & (data['High'] > 0) & (data['Low'] > 0) & (data['Volume'] > 0)]
    data = data[~data['Datetime'].duplicated()]
    data.reset_index(drop=True, inplace=True)

    print(f"[INFO] Datos procesados correctamente. Total de filas: {len(data)}")
    return data



def calculate_indicators(data):
    """
    Calcula indicadores técnicos manualmente y los agrega a los datos.
    """
    print("[INFO] Calculando indicadores manualmente...")

    # --- 1️⃣ RSI (Relative Strength Index) ---
    period_rsi = 14
    delta = data["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period_rsi).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period_rsi).mean()
    rs = gain / loss
    data["RSI"] = 100 - (100 / (1 + rs))

    # --- 2️⃣ MACD (Moving Average Convergence Divergence) ---
    fast_period, slow_period, signal_period = 12, 26, 9
    data["EMA_12"] = data["Close"].ewm(span=fast_period, adjust=False).mean()
    data["EMA_26"] = data["Close"].ewm(span=slow_period, adjust=False).mean()
    data["MACD"] = data["EMA_12"] - data["EMA_26"]
    data["MACD_Signal"] = data["MACD"].ewm(span=signal_period, adjust=False).mean()

    # --- 3️⃣ ATR (Average True Range) ---
    atr_period = 14
    high_low = data["High"] - data["Low"]
    high_close_prev = abs(data["High"] - data["Close"].shift(1))
    low_close_prev = abs(data["Low"] - data["Close"].shift(1))
    data["TR"] = high_low.combine(high_close_prev, max).combine(low_close_prev, max)
    data["ATR"] = data["TR"].rolling(window=atr_period).mean()

    # --- 4️⃣ STOCH (Stochastic Oscillator) ---
    stoch_k_period, stoch_d_period = 14, 3
    data["Lowest_Low"] = data["Low"].rolling(window=stoch_k_period).min()
    data["Highest_High"] = data["High"].rolling(window=stoch_k_period).max()
    data["STOCH_K"] = 100 * ((data["Close"] - data["Lowest_Low"]) / (data["Highest_High"] - data["Lowest_Low"]))
    data["STOCH_D"] = data["STOCH_K"].rolling(window=stoch_d_period).mean()

    # --- 5️⃣ EMA (Exponential Moving Average) ---
    ema_period = 50
    data["EMA_50"] = data["Close"].ewm(span=ema_period, adjust=False).mean()

    # --- 6️⃣ Bollinger Bands ---
    bb_period, bb_std_dev = 20, 2
    data["BB_Middle"] = data["Close"].rolling(window=bb_period).mean()
    data["BB_Std"] = data["Close"].rolling(window=bb_period).std()
    data["BB_Upper"] = data["BB_Middle"] + (bb_std_dev * data["BB_Std"])
    data["BB_Lower"] = data["BB_Middle"] - (bb_std_dev * data["BB_Std"])
    data["BB_Width"] = (data["BB_Upper"] - data["BB_Lower"]) / data["BB_Middle"]

    # --- 7️⃣ Variaciones y Log Retorno ---
    data["IntraDayVariation"] = (data["High"] - data["Low"]) / data["Open"]
    data["LogReturn"] = np.log(data["Close"] / data["Open"]).replace([np.inf, -np.inf], 0)

    # --- 8️⃣ Relativos y Cambios ---
    data["RelClose"] = (data["Close"] - data["Close"].shift(1)) / data["Close"].shift(1)
    data["RelHigh"] = (data["High"] - data["Close"]) / data["Close"]
    data["RelLow"] = (data["Low"] - data["Close"]) / data["Close"]
    data["LogVolume"] = np.log1p(data["Volume"].clip(lower=1))
    data["LogVolumeChange"] = data["LogVolume"].diff().fillna(0)
    data["VolumeChange"] = data["Volume"].pct_change().replace([np.inf, -np.inf], 0).fillna(0)
    data["AvgDailyVolume"] = data["Volume"].rolling(window=24).mean().fillna(0)

    # --- 🚀 Limpiar NaN y valores extremos ---
    data.replace([np.inf, -np.inf], 0, inplace=True)
    data.fillna(0, inplace=True)

    print("[INFO] Indicadores técnicos calculados correctamente.")
    
    # 🔍 Depuración: Mostrar los primeros valores después del cálculo
    print("[DEBUG] Primeros 10 registros después de calcular indicadores:")
    print(data[["RSI", "MACD", "ATR", "STOCH_K", "EMA_50", "BB_Width", "MACD_Signal"]].head(10))

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


def save_model(hmm_model, scaler, features, model_file):
    """
    Guarda el modelo HMM entrenado en un archivo junto con las estadísticas del escalador.
    """
    if hmm_model is None:
        print("[ERROR] No hay un modelo entrenado para guardar.")
        return

    scaler_stats = {
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "features": features  # Agregar las características utilizadas
    }

    # Preparar el diccionario que se guardará
    model_data = {
        'model': hmm_model,
        'scaler_stats': scaler_stats
    }

    # Guardar en un archivo pickle
    with open(model_file, 'wb') as file:
        joblib.dump(model_data, file)

    print(f"[INFO] Modelo guardado exitosamente en {model_file}.")
    print(f"[DEBUG] Características guardadas: {features}")
    print("[DEBUG] Información del escalador guardado:")
    print(f"Media: {scaler_stats['mean']}")
    print(f"Escala: {scaler_stats['scale']}")






def convert_to_condensed_format(data):
    """
    Convierte el DataFrame en un formato condensado y JSON serializable.
    """
    print("[INFO] Convirtiendo datos al formato condensado...")
    if 'Datetime' not in data.columns:
        raise ValueError("[ERROR] La columna 'Datetime' no se encuentra en el DataFrame.")

    data = data[['Datetime'] + [col for col in data.columns if col != 'Datetime']]  # Asegurar orden
    data['Datetime'] = data['Datetime'].apply(lambda x: int(x.timestamp() * 1000) if not pd.isnull(x) else 0)
    data.fillna(0, inplace=True)

    return data.to_dict(orient="records")

try:
    print("[INFO] Cargando modelo...")
    model_data = joblib.load(model_file)
    scaler_stats = model_data['scaler_stats']
    required_features = model_data['features']  # Características utilizadas por el modelo

    # Buffer extendido para cálculos de indicadores
    buffer_period = "2y"
    desired_days = 365  # Un año deseado en días

    print("[INFO] Descargando datos con buffer...")
    data = yf.download(ticker, interval=interval, period=buffer_period)

    # Depuración inicial
    print("[DEBUG] Datos iniciales descargados:")
    print(data.head())
    print(f"[DEBUG] Columnas iniciales: {data.columns}")
    print(f"[DEBUG] Índice inicial: {data.index}")

    if data.empty:
        raise ValueError("[ERROR] No se obtuvieron datos de YFinance.")

    print("[INFO] Procesando datos iniciales...")
    data = process_data(data)

    print("[INFO] Calculando indicadores...")
    data = calculate_indicators(data)

    # Filtrar el período deseado
    print("[INFO] Filtrando datos al período deseado...")
    start_date = (datetime.now() - pd.Timedelta(days=desired_days)).strftime('%Y-%m-%d')
    data = data[data['Datetime'] >= start_date]
    print(f"[INFO] Período filtrado: Desde {start_date} hasta {data['Datetime'].max()}")

    print("[INFO] Aplicando escalador a las características del modelo...")
    data = scale_features(data, scaler_stats, required_features)

    print("[INFO] Convirtiendo a formato condensado...")
    condensed_data = convert_to_condensed_format(data)
    with open(output_file, "w") as file:
        json.dump({"data": condensed_data}, file, indent=4)

    print(f"[INFO] Archivo generado: {output_file}")

except Exception as e:
    print(f"[ERROR] Ocurrió un error: {e}")
