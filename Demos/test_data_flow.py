#!/usr/bin/env python3
"""
Script de prueba para verificar el flujo de datos completo
"""
import sys
import os
import pandas as pd
from EthSession import CapitalOP
from DataEth import calculate_ltf_indicators

print("=" * 60)
print("TEST 1: Autenticación con Capital.com")
print("=" * 60)

try:
    capital_ops = CapitalOP()
    account_id = os.environ.get("CAPITAL_ACCOUNT_ID")
    if account_id:
        capital_ops.set_account_id(account_id)
    auth_result = capital_ops.authenticate()
    print(f"✅ Autenticación: {auth_result}")
except Exception as e:
    print(f"❌ Error autenticación: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 2: Obtener velas 1M desde API")
print("=" * 60)

try:
    fresh_candles = capital_ops.get_1m_candles("ETHUSD", limit=10)
    print(f"✅ Cantidad de velas: {len(fresh_candles) if fresh_candles else 0}")

    if fresh_candles and len(fresh_candles) > 0:
        print(f"✅ Primera vela: {fresh_candles[0]}")
        print(f"✅ Última vela: {fresh_candles[-1]}")
        print(f"✅ Keys: {list(fresh_candles[0].keys())}")
    else:
        print("❌ No se obtuvieron velas")
        sys.exit(1)
except Exception as e:
    print(f"❌ Error obteniendo velas: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 3: Convertir a DataFrame")
print("=" * 60)

try:
    fresh_df = pd.DataFrame(fresh_candles)
    print(f"✅ DataFrame shape: {fresh_df.shape}")
    print(f"✅ Columnas: {list(fresh_df.columns)}")
    print(f"✅ Primeras filas:\n{fresh_df.head(2)}")

    # Establecer timestamp como índice
    fresh_df['timestamp'] = pd.to_datetime(fresh_df['timestamp'])
    fresh_df.set_index('timestamp', inplace=True)
    fresh_df = fresh_df.sort_index()

    print(f"✅ DataFrame con índice temporal: {fresh_df.index[0]} → {fresh_df.index[-1]}")

except Exception as e:
    print(f"❌ Error creando DataFrame: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 4: Calcular indicadores técnicos")
print("=" * 60)

try:
    fresh_df_with_indicators = calculate_ltf_indicators(fresh_df)

    if fresh_df_with_indicators.empty:
        print("❌ DataFrame con indicadores está VACÍO")
        sys.exit(1)

    print(f"✅ DataFrame con indicadores shape: {fresh_df_with_indicators.shape}")
    print(f"✅ Columnas: {list(fresh_df_with_indicators.columns)}")
    print(f"✅ Índice: {fresh_df_with_indicators.index[0]} → {fresh_df_with_indicators.index[-1]}")

    # Verificar indicadores clave
    required_indicators = ['RSI', 'MACD', 'EMA_3', 'EMA_9', 'EMA_20', 'ATR', 'ADX']
    missing = [ind for ind in required_indicators if ind not in fresh_df_with_indicators.columns]

    if missing:
        print(f"⚠️ Indicadores faltantes: {missing}")
    else:
        print(f"✅ Todos los indicadores presentes")

    print(f"\n✅ Última vela con indicadores:")
    latest = fresh_df_with_indicators.iloc[-1]
    print(f"   Close: {latest.get('Close', 'N/A')}")
    print(f"   RSI: {latest.get('RSI', 'N/A')}")
    print(f"   MACD: {latest.get('MACD', 'N/A')}")
    print(f"   EMA_3: {latest.get('EMA_3', 'N/A')}")
    print(f"   EMA_9: {latest.get('EMA_9', 'N/A')}")

except Exception as e:
    print(f"❌ Error calculando indicadores: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 5: Convertir última vela a dict")
print("=" * 60)

try:
    latest_series = fresh_df_with_indicators.iloc[-1]
    last_ts = fresh_df_with_indicators.index[-1]

    latest_dict = latest_series.to_dict()
    latest_dict['Datetime'] = last_ts

    print(f"✅ Dict creado con {len(latest_dict)} keys")
    print(f"✅ Datetime: {latest_dict['Datetime']}")
    print(f"✅ Close: {latest_dict.get('Close', 'N/A')}")
    print(f"✅ RSI: {latest_dict.get('RSI', 'N/A')}")
    print(f"✅ Type Close: {type(latest_dict.get('Close'))}")

except Exception as e:
    print(f"❌ Error convirtiendo a dict: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ TODAS LAS PRUEBAS PASARON")
print("=" * 60)
