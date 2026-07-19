#!/usr/bin/env python3
import json
from datetime import datetime, timedelta
import pytz
import pandas as pd
import numpy as np

# Copiar solo lo necesario de verify_indicators.py para cargar y recalcular
try:
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.volatility import BollingerBands
    TA_OK = True
except Exception:
    TA_OK = False


def load_reports(path):
    with open(path, 'r') as f:
        j = json.load(f)
    def to_df(records):
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        if 'Datetime' in df.columns:
            df['Datetime'] = pd.to_datetime(df['Datetime'], utc=True, errors='coerce')
        elif 'snapshotTime' in df.columns:
            df['Datetime'] = pd.to_datetime(df['snapshotTime'], utc=True, errors='coerce')
        else:
            return pd.DataFrame()
        df = df.dropna(subset=['Datetime']).copy()
        df.set_index('Datetime', inplace=True)
        df.sort_index(inplace=True)
        return df
    h = to_df(j.get('historical_data', []))
    l = to_df(j.get('data', []))
    return h, l


def calculate_indicators_local(data):
    data = data.copy()
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

    for col in ['Close', 'Open', 'High', 'Low']:
        if col in data.columns:
            data[col] = data[col].apply(_extract_price)

    if 'Close' in data.columns:
        data = data.dropna(subset=['Close']).copy()

    if len(data) < 20 or not TA_OK:
        # If TA libs missing, return data with extracted prices
        return data

    data['RSI'] = RSIIndicator(data['Close'], window=10).rsi()
    data['RSI_5'] = RSIIndicator(data['Close'], window=5).rsi()
    data['RSI_7'] = RSIIndicator(data['Close'], window=7).rsi()

    data['EMA_3'] = data['Close'].ewm(span=3, adjust=False).mean()
    data['EMA_6'] = data['Close'].ewm(span=6, adjust=False).mean()
    data['EMA_9'] = data['Close'].ewm(span=9, adjust=False).mean()
    data['EMA_14'] = data['Close'].ewm(span=14, adjust=False).mean()
    data['EMA_20'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA_50'] = data['Close'].ewm(span=50, adjust=False).mean()

    data['MACD'] = data['EMA_6'] - data['EMA_14']
    data['MACD_Signal'] = data['MACD'].ewm(span=5, adjust=False).mean()
    data['MACD_Histogram'] = data['MACD'] - data['MACD_Signal']

    high_low = data['High'] - data['Low']
    high_close_prev = (data['High'] - data['Close'].shift(1)).abs()
    low_close_prev = (data['Low'] - data['Close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
    data['ATR'] = tr.rolling(window=10, min_periods=1).mean()

    data['VolumeChange'] = data['Volume'].pct_change().replace([np.inf, -np.inf], 0).fillna(0)
    data['log_return'] = np.log(data['Close'] / data['Close'].shift(1))

    stoch = StochasticOscillator(high=data['High'], low=data['Low'], close=data['Close'], window=14, smooth_window=3)
    data['STOCH'] = stoch.stoch()

    bb = BollingerBands(close=data['Close'], window=20, window_dev=2)
    data['BB_width'] = bb.bollinger_wband()

    data.replace([np.inf, -np.inf], 0, inplace=True)
    data.fillna(0, inplace=True)
    return data


if __name__ == '__main__':
    path = 'Reports/ETHUSD_CapitalData.json'
    h, l = load_reports(path)
    if h.empty and l.empty:
        print('[ERROR] No hay datos en el JSON.');
        raise SystemExit(1)

    # Timestamps problemáticos según verify: concentrados en 2026-02-20 05:00-09:00 y 2025-08-10 00:00
    targets = [
        '2026-02-20T05:00:00+00:00',
        '2026-02-20T06:00:00+00:00',
        '2026-02-20T07:00:00+00:00',
        '2026-02-20T08:00:00+00:00',
        '2026-02-20T09:00:00+00:00',
        '2025-08-10T00:00:00+00:00'
    ]

    print(f"[INFO] HTF filas={len(h)}  LTF filas={len(l)}  TA_libs={'ok' if TA_OK else 'missing'}")

    # Recalcular tablas enteras (puede tardar) — pero limitaremos a ventana alrededor de targets
    # Tomar ventana de 72 horas antes y 6 horas después de cada target
    for t in targets:
        ti = pd.to_datetime(t)
        start = ti - pd.Timedelta(hours=72)
        end = ti + pd.Timedelta(hours=6)
        window = h.loc[start:end]
        print('\n' + '='*60)
        print(f'[TARGET] {t}  — filas en ventana: {len(window)} (desde {start} hasta {end})')
        if window.empty:
            print('[WARN] No hay filas HTF en esa ventana.')
            continue
        # Mostrar las 5 filas previas y 5 posteriores alrededor del target
        if ti in window.index:
            # handle possible duplicate index entries: get_loc may return a slice
            pos_list = np.where(window.index == ti)[0]
            if len(pos_list) > 0:
                idx_pos = int(pos_list[0])
            else:
                try:
                    idx_pos = int(window.index.get_loc(ti))
                except Exception:
                    idx_pos = len(window) - 1
            low = max(0, idx_pos-5)
            high = min(len(window)-1, idx_pos+5)
            snippet = window.iloc[low:high+1]
        else:
            snippet = window.tail(10)
        # Mostrar columnas clave
        cols_show = ['Open','High','Low','Close','Volume','RSI','RSI_5','RSI_7','EMA_20','EMA_50','MACD','MACD_Histogram','ATR','VolumeChange','log_return']
        available = [c for c in cols_show if c in snippet.columns]
        print(snippet[available].to_string())

        if TA_OK:
            # Recalcular indicadores sobre la ventana y mostrar la fila exacta del target si existe
            recal = calculate_indicators_local(window)
            if ti in recal.index and 'RSI' in recal.columns:
                print('\n[RECALC] fila recalculada para target:')
                print(recal.loc[ti, available].to_string())
            else:
                print('\n[RECALC] No fue posible recalcular la fila exacta (falta historia o columnas).')
        else:
            print('\n[RECALC] Bibliotecas TA no disponibles; solo se muestran valores almacenados y OHLC/Volume.')

    print('\n[INFO] Inspección completa.')
