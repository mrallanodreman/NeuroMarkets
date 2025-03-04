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
from ta.momentum import RSIIndicator, StochasticOscillator


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
    Descarga datos históricos desde Capital.com y mantiene dos DataFrames:
    1. historical_data -> Contiene los datos históricos en la resolución original.
    2. data_1m -> Contiene los datos a 1 minuto.
    """
    all_data = []
    current_date = start_date
    segment_days = 10  # Descarga en segmentos de 10 días

    while current_date < end_date:
        seg_end_date = min(current_date + timedelta(days=segment_days), end_date)
        print(f"[INFO] Descargando datos {interval}: {current_date.strftime('%Y-%m-%d')} - {seg_end_date.strftime('%Y-%m-%d')}")

        # 📌 Descarga datos en la resolución original (ej: HOUR, DAY)
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
        # 📌 Crear DataFrame con datos históricos (HOUR, DAY, etc.)
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

        # ✅ Guardar copia de los datos históricos antes de modificar `df`
        historical_data = df.copy()

        # ✅ Descarga de datos a 1 minuto
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

                # ✅ Mantener solo datos a 1 minuto en `data_1m`
                data_1m = minute_df.copy()

                print(f"[INFO] ✅ Datos descargados correctamente: {len(historical_data)} registros históricos, {len(data_1m)} registros a 1M.")

                # 🔹 Retornar ambos DataFrames
                return historical_data, data_1m

    print("[ERROR] ❌ No se obtuvieron datos.")
    return pd.DataFrame(), pd.DataFrame()

def calculate_indicators(data, buffer_days=30, recent_days=395):
    """
    Calcula indicadores técnicos esenciales y los agrega a los datos.
    Se realiza sobre los últimos (recent_days + buffer_days) días para asegurar que 
    el primer día de recent_days tenga valores completos.
    """

    print("[INFO] Calculando indicadores esenciales...")

    # Filtrar los datos para usar solo los últimos `recent_days`
    cutoff_date = data.index.max() - pd.Timedelta(days=recent_days)
    data = data.loc[data.index >= cutoff_date].copy()

    # Convertir precios de diccionario a valores medios (si es necesario)
    for col in ["Close", "Open", "High", "Low"]:
        if isinstance(data[col].iloc[0], dict):
            print(f"[INFO] Extrayendo valores medios de precios en {col}...")
            data[col] = data[col].apply(lambda x: (x["bid"] + x["ask"]) / 2 if isinstance(x, dict) else x)

    # --- 1️⃣ RSI ---
    # Se calculan tres RSI con diferentes períodos
    data["RSI"] = RSIIndicator(data["Close"], window=10).rsi()  # RSI estándar
    data["RSI_5"] = RSIIndicator(data["Close"], window=5).rsi()  # RSI rápido
    data["RSI_7"] = RSIIndicator(data["Close"], window=7).rsi()  # RSI intermedio

    # --- 2️⃣ MACD y EMAs ---
    fast_period, slow_period, signal_period = 6, 14, 5

    # Cálculo de EMAs con la misma estructura
    data["EMA_3"] = data["Close"].ewm(span=3, adjust=False).mean()  # EMA ultrarrápida
    data["EMA_6"] = data["Close"].ewm(span=fast_period, adjust=False).mean()  # EMA rápida
    data["EMA_9"] = data["Close"].ewm(span=9, adjust=False).mean()  # EMA de corto plazo
    data["EMA_14"] = data["Close"].ewm(span=slow_period, adjust=False).mean()  # EMA lenta
    data["EMA_20"] = data["Close"].ewm(span=20, adjust=False).mean()  # EMA media
    data["EMA_50"] = data["Close"].ewm(span=50, adjust=False).mean()  # EMA de tendencia macro

    # Cálculo del MACD
    data["MACD"] = data["EMA_6"] - data["EMA_14"]
    data["MACD_Signal"] = data["MACD"].ewm(span=signal_period, adjust=False).mean()

    # MACD Histogram
    data["MACD_Histogram"] = data["MACD"] - data["MACD_Signal"]

    # --- 3️⃣ ATR ---
    atr_period = 10
    high_low = data["High"] - data["Low"]
    high_close_prev = abs(data["High"] - data["Close"].shift(1))
    low_close_prev = abs(data["Low"] - data["Close"].shift(1))
    tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
    data["ATR"] = tr.rolling(window=atr_period, min_periods=1).mean()

    # --- 4️⃣ VolumeChange ---
    data["VolumeChange"] = data["Volume"].pct_change().replace([np.inf, -np.inf], 0).fillna(0)

    # --- 5️⃣ Log Returns ---
    data["log_return"] = np.log(data["Close"] / data["Close"].shift(1))

    # --- 6️⃣ STOCH (Estocástico) ---
    stoch = StochasticOscillator(high=data["High"], low=data["Low"], close=data["Close"], window=14, smooth_window=3)
    data["STOCH"] = stoch.stoch()

    # --- 7️⃣ Bandas de Bollinger ---
    bb = BollingerBands(close=data["Close"], window=20, window_dev=2)
    data["BB_width"] = bb.bollinger_wband()

    # Limpiar NaN y valores extremos
    data.replace([np.inf, -np.inf], 0, inplace=True)
    data.fillna(0, inplace=True)

    print("[INFO] Indicadores esenciales calculados correctamente.")
    print("[DEBUG] Primeros 10 registros después de calcular indicadores:")
    print(data[["RSI", "RSI_5", "RSI_7", "MACD", "ATR", "VolumeChange", "Close"]].head(10))

    return data

def prepare_for_export(historical_data, data_1m):
    """
    Prepara y exporta ambos DataFrames: históricos y de 1 minuto.
    """
    print("[INFO] Preparando datos para exportación...")

    if 'Datetime' in historical_data.columns:
        historical_data['Datetime'] = historical_data['Datetime'].apply(lambda x: int(x.timestamp() * 1000))
    if 'Datetime' in data_1m.columns:
        data_1m['Datetime'] = data_1m['Datetime'].apply(lambda x: int(x.timestamp() * 1000))

    json_data = {
        "historical_data": historical_data.to_dict(orient="records"),
        "data_1m": data_1m.to_dict(orient="records")
    }

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Reports")
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, "ETHUSD_CapitalData.json")

    with open(output_file, 'w') as f:
        json.dump(json_data, f, indent=4)

    print(f"[INFO] ✅ Datos guardados correctamente en {output_file}")


# Obtener EPIC
epic = get_epic(ticker)
if epic:
    # 📌 Definir fechas de descarga
    end_date = datetime.now(pytz.UTC)
    start_date = end_date - timedelta(days=total_days)
    print(f"[INFO] Descargando datos desde {start_date.strftime('%Y-%m-%d')} hasta {end_date.strftime('%Y-%m-%d')}")

    # 📌 Descargar datos (se obtienen DOS DataFrames: histórico y 1M, renombrado a `data`)
    historical_data, data = download_data_capital(epic, interval, start_date, end_date)

    # ✅ Verificar si ambos DataFrames están vacíos
    if historical_data.empty and data.empty:
        print("[ERROR] No se obtuvieron datos de la API de Capital.com.")
    else:
        # ✅ Aplicar indicadores a **ambos** DataFrames (historical_data y data)
        historical_data = calculate_indicators(historical_data, buffer_days=buffer_days, recent_days=total_days)
        data = calculate_indicators(data, buffer_days=buffer_days, recent_days=total_days)

        # ✅ Filtrar solo los últimos 365 días en `historical_data`
        start_filter_date = end_date - timedelta(days=period_days)
        start_filter_date = pd.Timestamp(start_filter_date).tz_localize(None)
        print(f"[INFO] Filtrando datos históricos desde {start_filter_date.strftime('%Y-%m-%d')}")
        historical_data = historical_data[historical_data.index >= start_filter_date]

        # ✅ Preparar ambos DataFrames para exportación
        prepare_for_export(historical_data, data)

        # 📌 Directorio de exportación
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Reports")
        os.makedirs(output_dir, exist_ok=True)

        # 📌 Guardar archivo JSON con **ambos** conjuntos de datos
        output_file = os.path.join(output_dir, "ETHUSD_CapitalData.json")
        json_data = {
            "historical_data": historical_data.to_dict(orient="records"),
            "data": data.to_dict(orient="records")  # 📌 Cambiado de `data_1m` a `data`
        }

        with open(output_file, 'w') as f:
            json.dump(json_data, f, indent=4)

        # ✅ Verificación de guardado exitoso
        if os.path.exists(output_file):
            print(f"[INFO] ✅ Datos guardados correctamente en {output_file}")
        else:
            print(f"[ERROR] ❌ No se pudo guardar el archivo en {output_file}")
