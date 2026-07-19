#!/usr/bin/env python3
"""
Script de prueba para verificar APIs gratuitas de datos de ETH/USD
Prueba: Binance, CoinGecko, Kraken, y otras fuentes
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import json

def test_binance_spot():
    """Binance Spot - API pública, sin límites estrictos, datos históricos excelentes"""
    print("\n" + "="*60)
    print("🟡 PROBANDO: Binance Spot API")
    print("="*60)

    try:
        # Klines (candlestick) - límite 1000 velas por request
        # Intervalos: 1m, 5m, 15m, 1h, 4h, 1d

        # Prueba 1: Últimas 100 velas de 1 hora
        url = "https://api.binance.com/api/v3/klines"
        params = {
            'symbol': 'ETHUSDT',
            'interval': '1h',
            'limit': 100
        }

        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])

            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

            print(f"✅ Éxito: {len(df)} velas obtenidas")
            print(f"Rango: {df['timestamp'].min()} → {df['timestamp'].max()}")
            print(f"\nPrimeras 3 velas:")
            print(df.head(3))
            print(f"\nÚltimas 3 velas:")
            print(df.tail(3))

            # Prueba 2: Datos de 1 minuto (últimos 60 minutos)
            params_1m = {
                'symbol': 'ETHUSDT',
                'interval': '1m',
                'limit': 60
            }
            response_1m = requests.get(url, params=params_1m, timeout=10)
            if response_1m.status_code == 200:
                data_1m = response_1m.json()
                print(f"\n✅ 1m interval: {len(data_1m)} velas obtenidas")

            return True, df

        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            return False, None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        return False, None

def test_binance_historical():
    """Prueba descarga histórica con fechas específicas"""
    print("\n" + "="*60)
    print("🟡 PROBANDO: Binance Histórico (con fechas)")
    print("="*60)

    try:
        url = "https://api.binance.com/api/v3/klines"

        # Descargar datos de hace 30 días
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)

        params = {
            'symbol': 'ETHUSDT',
            'interval': '1h',
            'startTime': start_time,
            'endTime': end_time,
            'limit': 1000  # máximo por request
        }

        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            print(f"✅ Éxito: {len(df)} velas obtenidas (30 días)")
            print(f"Rango: {df['timestamp'].min()} → {df['timestamp'].max()}")

            return True, df
        else:
            print(f"❌ Error: {response.status_code}")
            return False, None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        return False, None

def test_coingecko():
    """CoinGecko - Gratuita pero con límites de rate (10-50 req/min)"""
    print("\n" + "="*60)
    print("🟢 PROBANDO: CoinGecko API")
    print("="*60)

    try:
        # Market chart - rango de datos históricos
        # vs_currency: usd, eur, etc.
        # days: 1, 7, 14, 30, 90, 180, 365, max

        url = "https://api.coingecko.com/api/v3/coins/ethereum/market_chart"
        params = {
            'vs_currency': 'usd',
            'days': '7',
            'interval': 'hourly'  # hourly or daily
        }

        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()

            # Extraer precios (timestamp, price)
            prices = data.get('prices', [])
            df = pd.DataFrame(prices, columns=['timestamp', 'close'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            print(f"✅ Éxito: {len(df)} puntos obtenidos")
            print(f"Rango: {df['timestamp'].min()} → {df['timestamp'].max()}")
            print(f"\nPrimeras 3 filas:")
            print(df.head(3))

            # Nota: CoinGecko no provee OHLC en API gratuita, solo precio de cierre
            print("\n⚠️ Nota: CoinGecko gratuita solo da precio de cierre, NO OHLC completo")

            return True, df

        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            return False, None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        return False, None

def test_kraken():
    """Kraken - API pública, OHLC disponible"""
    print("\n" + "="*60)
    print("🔵 PROBANDO: Kraken API")
    print("="*60)

    try:
        # OHLC endpoint
        # pair: ETHUSD, XETHZUSD
        # interval: 1, 5, 15, 30, 60, 240, 1440, 10080, 21600 (en minutos)

        url = "https://api.kraken.com/0/public/OHLC"
        params = {
            'pair': 'ETHUSD',
            'interval': 60,  # 60 min = 1 hora
            'since': int((datetime.now() - timedelta(days=7)).timestamp())
        }

        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()

            if 'error' in data and data['error']:
                print(f"❌ Error de API: {data['error']}")
                return False, None

            result = data.get('result', {})
            # La clave del par puede variar (XETHZUSD, ETHUSD)
            pair_key = next(iter([k for k in result.keys() if 'ETH' in k]), None)

            if pair_key:
                ohlc_data = result[pair_key]
                df = pd.DataFrame(ohlc_data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
                ])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
                df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

                print(f"✅ Éxito: {len(df)} velas obtenidas")
                print(f"Rango: {df['timestamp'].min()} → {df['timestamp'].max()}")
                print(f"\nPrimeras 3 velas:")
                print(df.head(3))

                return True, df
            else:
                print(f"❌ No se encontró par ETH en resultado")
                return False, None

        else:
            print(f"❌ Error: {response.status_code}")
            return False, None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        return False, None

def test_cryptocompare():
    """CryptoCompare - API gratuita con límites razonables"""
    print("\n" + "="*60)
    print("🟠 PROBANDO: CryptoCompare API")
    print("="*60)

    try:
        # Histohour - datos históricos por hora
        url = "https://min-api.cryptocompare.com/data/v2/histohour"
        params = {
            'fsym': 'ETH',
            'tsym': 'USD',
            'limit': 100  # últimas 100 horas
        }

        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()

            if data.get('Response') == 'Success':
                ohlc_data = data['Data']['Data']
                df = pd.DataFrame(ohlc_data)
                df['timestamp'] = pd.to_datetime(df['time'], unit='s')
                df = df[['timestamp', 'open', 'high', 'low', 'close', 'volumefrom']]
                df.rename(columns={'volumefrom': 'volume'}, inplace=True)

                print(f"✅ Éxito: {len(df)} velas obtenidas")
                print(f"Rango: {df['timestamp'].min()} → {df['timestamp'].max()}")
                print(f"\nPrimeras 3 velas:")
                print(df.head(3))

                return True, df
            else:
                print(f"❌ API devolvió error: {data.get('Message')}")
                return False, None

        else:
            print(f"❌ Error: {response.status_code}")
            return False, None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        return False, None

def main():
    """Ejecuta todas las pruebas"""
    print("\n" + "▓"*60)
    print("🔍 TESTE DE APIs GRATUITAS PARA DATOS DE ETHEREUM")
    print("▓"*60)

    results = {}

    # Test 1: Binance Spot
    success, data = test_binance_spot()
    results['Binance Spot'] = success
    time.sleep(1)

    # Test 2: Binance Histórico
    success, data = test_binance_historical()
    results['Binance Histórico'] = success
    time.sleep(1)

    # Test 3: CoinGecko
    success, data = test_coingecko()
    results['CoinGecko'] = success
    time.sleep(2)  # CoinGecko tiene rate limit más estricto

    # Test 4: Kraken
    success, data = test_kraken()
    results['Kraken'] = success
    time.sleep(1)

    # Test 5: CryptoCompare
    success, data = test_cryptocompare()
    results['CryptoCompare'] = success

    # Resumen
    print("\n" + "▓"*60)
    print("📊 RESUMEN DE RESULTADOS")
    print("▓"*60)

    for api, status in results.items():
        icon = "✅" if status else "❌"
        print(f"{icon} {api}: {'FUNCIONA' if status else 'FALLO'}")

    print("\n" + "▓"*60)
    print("💡 RECOMENDACIONES")
    print("▓"*60)

    if results.get('Binance Spot'):
        print("🥇 MEJOR OPCIÓN: Binance Spot API")
        print("   - Sin autenticación requerida")
        print("   - OHLCV completo (Open, High, Low, Close, Volume)")
        print("   - Intervalos: 1m, 5m, 15m, 1h, 4h, 1d, etc.")
        print("   - Límite: 1000 velas por request")
        print("   - Rate limit: ~1200 req/min (muy generoso)")
        print("   - Datos históricos: Años completos disponibles")

    if results.get('Kraken'):
        print("\n🥈 ALTERNATIVA: Kraken API")
        print("   - OHLC completo")
        print("   - Sin autenticación para datos públicos")
        print("   - Menos límites que CoinGecko")

    if results.get('CryptoCompare'):
        print("\n🥉 BACKUP: CryptoCompare")
        print("   - OHLC completo")
        print("   - API Key gratuita recomendada para más requests")

    print("\n⚠️ NO RECOMENDADO: CoinGecko para OHLC")
    print("   - Solo precio de cierre, no OHLC completo en versión gratuita")

    print("\n" + "▓"*60)

if __name__ == "__main__":
    main()
