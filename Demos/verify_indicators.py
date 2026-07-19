#!/usr/bin/env python3
import json
from datetime import datetime
import pytz
import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands


def load_reports(path):
    with open(path, 'r') as f:
        j = json.load(f)
    def to_df(records):
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        # Prefer 'Datetime' or 'snapshotTime'
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
    # Copy of the project's calculation logic (simplified where safe)
    if data is None or data.empty:
        return data

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

    if len(data) < 20:
        return data

    # RSI
    data['RSI'] = RSIIndicator(data['Close'], window=10).rsi()
    data['RSI_5'] = RSIIndicator(data['Close'], window=5).rsi()
    data['RSI_7'] = RSIIndicator(data['Close'], window=7).rsi()

    # EMAs and MACD as in DataEth
    data['EMA_3'] = data['Close'].ewm(span=3, adjust=False).mean()
    data['EMA_6'] = data['Close'].ewm(span=6, adjust=False).mean()
    data['EMA_9'] = data['Close'].ewm(span=9, adjust=False).mean()
    data['EMA_14'] = data['Close'].ewm(span=14, adjust=False).mean()
    data['EMA_20'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA_50'] = data['Close'].ewm(span=50, adjust=False).mean()

    data['MACD'] = data['EMA_6'] - data['EMA_14']
    data['MACD_Signal'] = data['MACD'].ewm(span=5, adjust=False).mean()
    data['MACD_Histogram'] = data['MACD'] - data['MACD_Signal']

    # ATR
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


def compare_frames(stored, recalculated, cols, tol_abs=1e-6, tol_rel=1e-4, show_examples=5):
    report = {}
    # Definir lookbacks mínimos por indicador (conservador)
    lookbacks = {
        'RSI': 10, 'RSI_5': 5, 'RSI_7': 7,
        'EMA_20': 20, 'EMA_50': 50,
        'MACD': 50, 'MACD_Histogram': 50,
        'ATR': 10, 'VolumeChange': 2, 'log_return': 2
    }
    for c in cols:
        if c not in stored.columns or c not in recalculated.columns:
            report[c] = {'status': 'missing_column'}
            continue
        s = stored[c].astype(float)
        r = recalculated[c].astype(float)
        # crear DataFrame alineado
        df_cmp = pd.DataFrame({'stored': s, 'recalc': r})
        # eliminar duplicados en el índice manteniendo el último (coincide con la política de merge del proyecto)
        df_cmp = df_cmp[~df_cmp.index.duplicated(keep='last')]
        df_cmp.dropna(how='all', inplace=True)
        if df_cmp.empty:
            report[c] = {'status': 'no_overlap'}
            continue
        # Excluir timestamps donde no hay suficiente historial para recalcular el indicador
        lb = lookbacks.get(c, 0)
        if lb and lb > 0:
            sufficient_mask = []
            idx_list = list(df_cmp.index)
            for idx in idx_list:
                # número de filas disponibles hasta e incluyendo idx en el frame recalculado
                try:
                    available = int(recalculated.loc[:idx].shape[0])
                except Exception:
                    available = 0
                sufficient_mask.append(available >= lb)
            df_cmp['sufficient_history'] = sufficient_mask
            # separar los que no tienen suficiente historia
            insufficient = df_cmp[~df_cmp['sufficient_history']]
            if not insufficient.empty:
                # registrar cuántos fueron excluidos por falta de historia
                report[c] = {
                    'status': 'partial',
                    'excluded_insufficient_history': int(len(insufficient))
                }
            # quedarnos solo con los que sí tienen historia suficiente
            df_cmp = df_cmp[df_cmp['sufficient_history']].drop(columns=['sufficient_history'])
            if df_cmp.empty:
                # Si tras excluir no queda nada para comparar, marcar y continuar
                if c in report and report[c].get('status') == 'partial':
                    continue
                report[c] = {'status': 'no_sufficient_history'}
                continue
        diff = (df_cmp['stored'] - df_cmp['recalc']).abs()
        denom = df_cmp['recalc'].abs()
        denom = denom.where(denom > 1e-12, diff + 1e-12)
        rel = diff / denom
        mask = (diff > tol_abs) & (rel > tol_rel)
        mismatches = int(mask.sum())
        total = int(len(df_cmp))
        report[c] = {
            'total_compared': int(total),
            'mismatches': int(mismatches),
            'max_abs_diff': float(diff.max()),
            'max_rel_diff': float(rel.max())
        }
        if mismatches > 0:
            examples = []
            mismatch_idx = df_cmp.index[mask.values]
            for idx in mismatch_idx[:show_examples]:
                examples.append({
                    'ts': idx.isoformat(),
                    'stored': float(df_cmp.loc[idx, 'stored']),
                    'recalc': float(df_cmp.loc[idx, 'recalc']),
                    'abs_diff': float(diff.loc[idx]),
                    'rel_diff': float(rel.loc[idx])
                })
            report[c]['examples'] = examples
    return report


def main():
    path = 'Reports/ETHUSD_CapitalData.json'
    print(f"[INFO] Cargando {path}...")
    h, l = load_reports(path)
    if h.empty and l.empty:
        print('[ERROR] No hay datos en el JSON.')
        return

    print(f"[INFO] HTF filas={len(h)}  LTF filas={len(l)}")

    # Recalcular usando TODO el historial para asegurar ventanas completas
    h_sample = h.copy()
    l_sample = l.copy()

    print('[INFO] Recalculando indicadores HTF...')
    h_recalc = calculate_indicators_local(h_sample)
    print('[INFO] Recalculando indicadores LTF...')
    l_recalc = calculate_indicators_local(l_sample)

    cols = ['RSI', 'RSI_5', 'RSI_7', 'EMA_20', 'EMA_50', 'MACD', 'MACD_Histogram', 'ATR', 'VolumeChange', 'log_return']

    print('[INFO] Comparando HTF...')
    h_report = compare_frames(h_sample, h_recalc, cols)
    print('[INFO] Comparando LTF...')
    l_report = compare_frames(l_sample, l_recalc, cols)

    print('\n=== Resumen HTF ===')
    print(json.dumps(h_report, indent=2, ensure_ascii=False))
    print('\n=== Resumen LTF ===')
    print(json.dumps(l_report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
