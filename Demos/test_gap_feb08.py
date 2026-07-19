#!/usr/bin/env python3
"""
Prueba de descarga del tramo problemático:
2026-02-08 09:00:00+00:00 -> 2026-02-08 22:00:00+00:00
"""

import requests
import pandas as pd
from datetime import datetime, timezone
import time

# Rango exacto del problema
START = datetime(2026, 2, 8, 9, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 2, 8, 23, 0, 0, tzinfo=timezone.utc)

print("="*70)
print(f"🔍 PROBANDO DESCARGA DEL TRAMO PROBLEMÁTICO")
print(f"   Inicio: {START}")
print(f"   Fin:    {END}")
print(f"   Duración: {(END - START).total_seconds() / 3600:.1f} horas")
print("="*70)

def test_binance_gap():
    """Probar descarga con Binance"""
    print("\n" + "─"*70)
    print("🟡 BINANCE SPOT API")
    print("─"*70)

    try:
        url = "https://api.binance.com/api/v3/klines"

        # Convertir a milisegundos
        start_ms = int(START.timestamp() * 1000)
        end_ms = int(END.timestamp() * 1000)

        params = {
            'symbol': 'ETHUSDT',
            'interval': '1h',
            'startTime': start_ms,
            'endTime': end_ms,
            'limit': 1000
        }

        print(f"📡 Solicitando datos...")
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()

            if not data:
                print("❌ API devolvió lista vacía - NO HAY DATOS EN ESTE RANGO")
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
            print(f"   Rango real: {df['timestamp'].min()} → {df['timestamp'].max()}")
            print(f"\n📊 Datos obtenidos:")
            print(df.to_string())

            # Verificar huecos
            expected_hours = int((END - START).total_seconds() / 3600) + 1
            if len(df) < expected_hours:
                print(f"\n⚠️ ADVERTENCIA: Se esperaban {expected_hours} velas, pero se obtuvieron {len(df)}")
            else:
                print(f"\n✅ Datos completos: {len(df)} velas (esperadas: {expected_hours})")

            return df

        else:
            print(f"❌ Error HTTP: {response.status_code}")
            print(f"   Respuesta: {response.text[:200]}")
            return None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_kraken_gap():
    """Probar descarga con Kraken"""
    print("\n" + "─"*70)
    print("🔵 KRAKEN API")
    print("─"*70)

    try:
        url = "https://api.kraken.com/0/public/OHLC"

        params = {
            'pair': 'ETHUSD',
            'interval': 60,  # 60 min
            'since': int(START.timestamp())
        }

        print(f"📡 Solicitando datos...")
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()

            if 'error' in data and data['error']:
                print(f"❌ Error de API: {data['error']}")
                return None

            result = data.get('result', {})
            pair_key = next(iter([k for k in result.keys() if 'ETH' in k]), None)

            if not pair_key:
                print("❌ No se encontró par ETH en resultado")
                return None

            ohlc_data = result[pair_key]

            if not ohlc_data:
                print("❌ API devolvió lista vacía - NO HAY DATOS EN ESTE RANGO")
                return None

            df = pd.DataFrame(ohlc_data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'
            ])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

            # Filtrar solo el rango solicitado
            df = df[(df['timestamp'] >= START) & (df['timestamp'] <= END)]

            print(f"✅ Éxito: {len(df)} velas obtenidas")
            print(f"   Rango real: {df['timestamp'].min()} → {df['timestamp'].max()}")
            print(f"\n📊 Datos obtenidos:")
            print(df.to_string())

            expected_hours = int((END - START).total_seconds() / 3600) + 1
            if len(df) < expected_hours:
                print(f"\n⚠️ ADVERTENCIA: Se esperaban {expected_hours} velas, pero se obtuvieron {len(df)}")
            else:
                print(f"\n✅ Datos completos: {len(df)} velas (esperadas: {expected_hours})")

            return df

        else:
            print(f"❌ Error HTTP: {response.status_code}")
            return None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_cryptocompare_gap():
    """Probar descarga con CryptoCompare"""
    print("\n" + "─"*70)
    print("🟠 CRYPTOCOMPARE API")
    print("─"*70)

    try:
        url = "https://min-api.cryptocompare.com/data/v2/histohour"

        # CryptoCompare requiere timestamp Unix
        params = {
            'fsym': 'ETH',
            'tsym': 'USD',
            'limit': 2000,  # límite alto
            'toTs': int(END.timestamp())
        }

        print(f"📡 Solicitando datos...")
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()

            if data.get('Response') != 'Success':
                print(f"❌ API error: {data.get('Message')}")
                return None

            ohlc_data = data['Data']['Data']

            if not ohlc_data:
                print("❌ API devolvió lista vacía - NO HAY DATOS")
                return None

            df = pd.DataFrame(ohlc_data)
            df['timestamp'] = pd.to_datetime(df['time'], unit='s', utc=True)
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volumefrom']]
            df.rename(columns={'volumefrom': 'volume'}, inplace=True)

            # Filtrar solo el rango solicitado
            df = df[(df['timestamp'] >= START) & (df['timestamp'] <= END)]

            print(f"✅ Éxito: {len(df)} velas obtenidas")
            if len(df) > 0:
                print(f"   Rango real: {df['timestamp'].min()} → {df['timestamp'].max()}")
                print(f"\n📊 Datos obtenidos:")
                print(df.to_string())

                expected_hours = int((END - START).total_seconds() / 3600) + 1
                if len(df) < expected_hours:
                    print(f"\n⚠️ ADVERTENCIA: Se esperaban {expected_hours} velas, pero se obtuvieron {len(df)}")
                else:
                    print(f"\n✅ Datos completos: {len(df)} velas (esperadas: {expected_hours})")
            else:
                print("❌ No hay datos para el rango solicitado después de filtrar")

            return df if len(df) > 0 else None

        else:
            print(f"❌ Error HTTP: {response.status_code}")
            return None

    except Exception as e:
        print(f"❌ Excepción: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """Ejecutar todas las pruebas"""

    results = {}

    # Test 1: Binance
    df_binance = test_binance_gap()
    results['Binance'] = df_binance is not None and len(df_binance) > 0
    time.sleep(1)

    # Test 2: Kraken
    df_kraken = test_kraken_gap()
    results['Kraken'] = df_kraken is not None and len(df_kraken) > 0
    time.sleep(1)

    # Test 3: CryptoCompare
    df_cc = test_cryptocompare_gap()
    results['CryptoCompare'] = df_cc is not None and len(df_cc) > 0

    # Resumen
    print("\n" + "="*70)
    print("📊 RESUMEN FINAL")
    print("="*70)

    for api, success in results.items():
        icon = "✅" if success else "❌"
        status = "TIENE DATOS" if success else "SIN DATOS / ERROR"
        print(f"{icon} {api}: {status}")

    print("\n" + "="*70)
    print("💡 CONCLUSIÓN")
    print("="*70)

    if results.get('Binance'):
        print("✅ Binance PUEDE llenar este hueco")
        print("   → Usar Binance como fuente principal")
    elif results.get('Kraken'):
        print("✅ Kraken PUEDE llenar este hueco")
        print("   → Usar Kraken como alternativa")
    elif results.get('CryptoCompare'):
        print("✅ CryptoCompare PUEDE llenar este hueco")
        print("   → Usar CryptoCompare como fallback")
    else:
        print("❌ NINGUNA API tiene datos para este rango")
        print("   → Posible que el mercado estuviera cerrado o sea fecha futura")
        print(f"   → Verificar si {START.date()} es válida")
        print(f"   → Hoy es: {datetime.now(timezone.utc).date()}")

        # Verificación: ¿la fecha es futura?
        if START > datetime.now(timezone.utc):
            print("\n🚨 IMPORTANTE: La fecha solicitada está EN EL FUTURO")
            print("   → No es posible obtener datos de fechas futuras")

    print("="*70)

if __name__ == "__main__":
    main()
