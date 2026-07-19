#!/usr/bin/env python3
"""
Script para comparar valores OHLCV de Capital.com vs APIs gratuitas
Descarga el mismo tramo horario desde las 4 fuentes y muestra diferencias.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import pytz
import time
from EthSession import CapitalOP
from EthConfig import BASE_URL, API_KEY

# ========================
# CONFIGURACIÓN DEL TRAMO A COMPARAR
# ========================
# Usar las últimas 24 horas completas
now = datetime.now(pytz.UTC)
END_TIME = now.replace(minute=0, second=0, microsecond=0)  # Hora completa más reciente
START_TIME = END_TIME - timedelta(hours=24)

print("="*80)
print("🔬 COMPARACIÓN DE APIs: Capital.com vs Binance vs Kraken vs CryptoCompare")
print("="*80)
print(f"📅 Tramo a comparar: {START_TIME} → {END_TIME}")
print(f"⏱️  Duración: 24 horas (esperadas 24-25 velas de 1h)")
print("="*80)

# ========================
# 1. CAPITAL.COM
# ========================
def download_capital():
    """Descargar datos desde Capital.com"""
    print("\n" + "─"*80)
    print("🔵 CAPITAL.COM API")
    print("─"*80)

    try:
        # Autenticar
        capital_ops = CapitalOP()
        print("🔐 Autenticando con Capital.com...")

        if not capital_ops.authenticate():
            print("❌ Fallo en autenticación con Capital.com")
            return None

        print("✅ Autenticación exitosa")

        # Obtener EPIC de ETHUSD
        epic = "ETHUSD"

        # Construir URL
        prices_url = (
            f"{BASE_URL}/api/v1/prices/{epic}"
            f"?resolution=HOUR"
            f"&from={START_TIME.strftime('%Y-%m-%dT%H:%M:%S')}"
            f"&to={END_TIME.strftime('%Y-%m-%dT%H:%M:%S')}"
        )

        headers = {
            "Content-Type": "application/json",
            "X-CAP-API-KEY": API_KEY,
            "CST": capital_ops.session_token,
            "X-SECURITY-TOKEN": capital_ops.x_security_token
        }

        print(f"📡 Descargando datos...")
        response = requests.get(prices_url, headers=headers, timeout=15)

        if response.status_code == 200:
            data_json = response.json().get("prices", [])

            if not data_json:
                print("❌ API devolvió lista vacía")
                return None

            # Capital.com puede devolver valores como dicts con 'bid'/'ask' o como números
            # Necesitamos extraer el valor correcto
            processed_data = []
            for candle in data_json:
                processed_candle = {
                    'timestamp': candle.get('snapshotTimeUTC'),
                    'open': None,
                    'high': None,
                    'low': None,
                    'close': None,
                    'volume': None
                }

                # Extraer valores (pueden ser dict o float)
                for key, capital_key in [('open', 'openPrice'), ('high', 'highPrice'),
                                         ('low', 'lowPrice'), ('close', 'closePrice')]:
                    val = candle.get(capital_key)
                    if isinstance(val, dict):
                        # Usar bid o ask (preferir bid para coherencia)
                        processed_candle[key] = val.get('bid') or val.get('ask') or val.get('mid')
                    else:
                        processed_candle[key] = val

                # Volume
                vol = candle.get('lastTradedVolume')
                if isinstance(vol, dict):
                    processed_candle['volume'] = vol.get('value', 0)
                else:
                    processed_candle['volume'] = vol

                processed_data.append(processed_candle)

            df = pd.DataFrame(processed_data)
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
            df.sort_values('timestamp', inplace=True)
            df.reset_index(drop=True, inplace=True)

            print(f"✅ Éxito: {len(df)} velas obtenidas")
            print(f"   Rango: {df['timestamp'].min()} → {df['timestamp'].max()}")

            return df

        else:
            print(f"❌ Error HTTP {response.status_code}: {response.text[:200]}")
            return None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        import traceback
        traceback.print_exc()
        return None

# ========================
# 2. BINANCE
# ========================
def download_binance():
    """Descargar datos desde Binance"""
    print("\n" + "─"*80)
    print("🟡 BINANCE SPOT API")
    print("─"*80)

    try:
        url = "https://api.binance.com/api/v3/klines"

        start_ms = int(START_TIME.timestamp() * 1000)
        end_ms = int(END_TIME.timestamp() * 1000)

        params = {
            'symbol': 'ETHUSDT',
            'interval': '1h',
            'startTime': start_ms,
            'endTime': end_ms,
            'limit': 1000
        }

        print(f"📡 Descargando datos...")
        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()

            if not data:
                print("❌ API devolvió lista vacía")
                return None

            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])

            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

            print(f"✅ Éxito: {len(df)} velas obtenidas")
            print(f"   Rango: {df['timestamp'].min()} → {df['timestamp'].max()}")

            return df

        else:
            print(f"❌ Error HTTP {response.status_code}")
            return None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        import traceback
        traceback.print_exc()
        return None

# ========================
# 3. KRAKEN
# ========================
def download_kraken():
    """Descargar datos desde Kraken"""
    print("\n" + "─"*80)
    print("🔵 KRAKEN API")
    print("─"*80)

    try:
        url = "https://api.kraken.com/0/public/OHLC"

        params = {
            'pair': 'ETHUSD',
            'interval': 60,
            'since': int(START_TIME.timestamp())
        }

        print(f"📡 Descargando datos...")
        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()

            if 'error' in data and data['error']:
                print(f"❌ Error de API: {data['error']}")
                return None

            result = data.get('result', {})
            pair_key = next(iter([k for k in result.keys() if 'ETH' in k]), None)

            if not pair_key:
                print("❌ No se encontró par ETH")
                return None

            ohlc_data = result[pair_key]

            if not ohlc_data:
                print("❌ API devolvió lista vacía")
                return None

            df = pd.DataFrame(ohlc_data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
            ])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

            # Filtrar por rango
            df = df[(df['timestamp'] >= START_TIME) & (df['timestamp'] <= END_TIME)]
            df.reset_index(drop=True, inplace=True)

            print(f"✅ Éxito: {len(df)} velas obtenidas")
            print(f"   Rango: {df['timestamp'].min()} → {df['timestamp'].max()}")

            return df

        else:
            print(f"❌ Error HTTP {response.status_code}")
            return None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        import traceback
        traceback.print_exc()
        return None

# ========================
# 4. CRYPTOCOMPARE
# ========================
def download_cryptocompare():
    """Descargar datos desde CryptoCompare"""
    print("\n" + "─"*80)
    print("🟠 CRYPTOCOMPARE API")
    print("─"*80)

    try:
        url = "https://min-api.cryptocompare.com/data/v2/histohour"

        params = {
            'fsym': 'ETH',
            'tsym': 'USD',
            'limit': 2000,
            'toTs': int(END_TIME.timestamp())
        }

        print(f"📡 Descargando datos...")
        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()

            if data.get('Response') != 'Success':
                print(f"❌ API error: {data.get('Message')}")
                return None

            ohlc_data = data['Data']['Data']

            if not ohlc_data:
                print("❌ API devolvió lista vacía")
                return None

            df = pd.DataFrame(ohlc_data)
            df['timestamp'] = pd.to_datetime(df['time'], unit='s', utc=True)
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volumefrom']]
            df.rename(columns={'volumefrom': 'volume'}, inplace=True)

            # Filtrar por rango
            df = df[(df['timestamp'] >= START_TIME) & (df['timestamp'] <= END_TIME)]
            df.reset_index(drop=True, inplace=True)

            print(f"✅ Éxito: {len(df)} velas obtenidas")
            if len(df) > 0:
                print(f"   Rango: {df['timestamp'].min()} → {df['timestamp'].max()}")

            return df if len(df) > 0 else None

        else:
            print(f"❌ Error HTTP {response.status_code}")
            return None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        import traceback
        traceback.print_exc()
        return None

# ========================
# COMPARACIÓN DE DATOS
# ========================
def compare_dataframes(df_capital, df_binance, df_kraken, df_cc):
    """Comparar los DataFrames de las 4 APIs"""
    print("\n" + "="*80)
    print("📊 ANÁLISIS COMPARATIVO")
    print("="*80)

    # Verificar qué APIs tienen datos
    apis_ok = {
        'Capital.com': df_capital is not None,
        'Binance': df_binance is not None,
        'Kraken': df_kraken is not None,
        'CryptoCompare': df_cc is not None
    }

    print("\n🔍 Estado de las APIs:")
    for api, ok in apis_ok.items():
        icon = "✅" if ok else "❌"
        print(f"  {icon} {api}")

    # Si no hay datos suficientes, terminar
    successful_apis = [name for name, ok in apis_ok.items() if ok]
    if len(successful_apis) < 2:
        print("\n❌ Se necesitan al menos 2 APIs con datos para comparar")
        return

    print(f"\n✅ {len(successful_apis)} APIs disponibles para comparación")

    # Alinear por timestamp (usar merge)
    # Empezar con la API que tenga más datos
    dfs = []
    labels = []

    if df_capital is not None:
        dfs.append(df_capital)
        labels.append('capital')
    if df_binance is not None:
        dfs.append(df_binance)
        labels.append('binance')
    if df_kraken is not None:
        dfs.append(df_kraken)
        labels.append('kraken')
    if df_cc is not None:
        dfs.append(df_cc)
        labels.append('cryptocompare')

    # Merge todos los DataFrames por timestamp
    merged = dfs[0].copy()
    merged = merged.rename(columns={
        'open': f'open_{labels[0]}',
        'high': f'high_{labels[0]}',
        'low': f'low_{labels[0]}',
        'close': f'close_{labels[0]}',
        'volume': f'volume_{labels[0]}'
    })

    for i in range(1, len(dfs)):
        df_temp = dfs[i].copy()
        df_temp = df_temp.rename(columns={
            'open': f'open_{labels[i]}',
            'high': f'high_{labels[i]}',
            'low': f'low_{labels[i]}',
            'close': f'close_{labels[i]}',
            'volume': f'volume_{labels[i]}'
        })
        merged = pd.merge(merged, df_temp, on='timestamp', how='outer')

    merged.sort_values('timestamp', inplace=True)
    merged.reset_index(drop=True, inplace=True)

    print(f"\n📈 Velas alineadas: {len(merged)}")
    print(f"   Rango temporal: {merged['timestamp'].min()} → {merged['timestamp'].max()}")

    # Mostrar primeras 5 filas como muestra
    print("\n📋 MUESTRA DE DATOS (primeras 5 velas):")
    print("─"*80)

    for idx in range(min(5, len(merged))):
        row = merged.iloc[idx]
        print(f"\n⏰ {row['timestamp']}")

        for label in labels:
            open_val = row.get(f'open_{label}', None)
            high_val = row.get(f'high_{label}', None)
            low_val = row.get(f'low_{label}', None)
            close_val = row.get(f'close_{label}', None)

            if pd.notna(open_val):
                print(f"  {label:14s}: O={open_val:8.2f}  H={high_val:8.2f}  L={low_val:8.2f}  C={close_val:8.2f}")
            else:
                print(f"  {label:14s}: SIN DATOS")

    # Calcular diferencias porcentuales (usar Capital como referencia si está disponible)
    if 'capital' in labels:
        ref = 'capital'
    else:
        ref = labels[0]

    print(f"\n📊 DIFERENCIAS PORCENTUALES (referencia: {ref.upper()})")
    print("="*80)

    stats = {}

    for label in labels:
        if label == ref:
            continue

        # Calcular diferencias en Close
        if f'close_{ref}' in merged.columns and f'close_{label}' in merged.columns:
            merged[f'diff_{label}'] = ((merged[f'close_{label}'] - merged[f'close_{ref}']) / merged[f'close_{ref}']) * 100

            valid_diffs = merged[f'diff_{label}'].dropna()

            if len(valid_diffs) > 0:
                mean_diff = valid_diffs.mean()
                max_diff = valid_diffs.abs().max()
                std_diff = valid_diffs.std()

                stats[label] = {
                    'mean': mean_diff,
                    'max': max_diff,
                    'std': std_diff,
                    'count': len(valid_diffs)
                }

                print(f"\n{label.upper()} vs {ref.upper()}:")
                print(f"  Velas comparables: {len(valid_diffs)}")
                print(f"  Diferencia promedio: {mean_diff:+.4f}%")
                print(f"  Diferencia máxima: ±{max_diff:.4f}%")
                print(f"  Desviación estándar: {std_diff:.4f}%")

    # Resumen final
    print("\n" + "="*80)
    print("💡 CONCLUSIÓN")
    print("="*80)

    if stats:
        max_mean_diff = max([v['mean'] for v in stats.values()], key=abs)
        max_max_diff = max([v['max'] for v in stats.values()])

        print(f"\n📌 Diferencia promedio máxima entre APIs: {max_mean_diff:+.4f}%")
        print(f"📌 Diferencia puntual máxima: ±{max_max_diff:.4f}%")

        if max_max_diff < 0.1:
            print("\n✅ EXCELENTE: Todas las APIs muestran valores prácticamente idénticos (<0.1%)")
        elif max_max_diff < 0.5:
            print("\n✅ MUY BUENO: Las APIs muestran valores muy similares (<0.5%)")
        elif max_max_diff < 1.0:
            print("\n⚠️  ACEPTABLE: Hay ligeras diferencias entre APIs (<1.0%)")
        elif max_max_diff < 2.0:
            print("\n⚠️  MODERADO: Diferencias notables entre APIs (<2.0%)")
        else:
            print("\n❌ ALTO: Diferencias significativas entre APIs (>2.0%)")

        print("\n🔍 Posibles causas de diferencias:")
        print("  • Diferentes pares de trading (ETHUSDT vs ETHUSD)")
        print("  • Timestamps de cierre de vela ligeramente diferentes")
        print("  • Exchanges con diferentes volúmenes y liquidez")
        print("  • Ajustes de precio por horquilla bid/ask")

    print("\n" + "="*80)

# ========================
# EJECUCIÓN PRINCIPAL
# ========================
def main():
    """Ejecutar comparación completa"""

    # Descargar desde todas las APIs
    df_capital = download_capital()
    time.sleep(1)

    df_binance = download_binance()
    time.sleep(1)

    df_kraken = download_kraken()
    time.sleep(1)

    df_cc = download_cryptocompare()

    # Comparar resultados
    compare_dataframes(df_capital, df_binance, df_kraken, df_cc)

if __name__ == "__main__":
    main()
