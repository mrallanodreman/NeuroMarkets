# -*- coding: utf-8 -*-
"""
Script de ejecucion de DataEth para poblar datos historicos.
Ejecutar con: python run_dataeth.py
"""
import sys
import os

# Forzar UTF-8 en stdout/stderr
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Asegurar que el directorio de DataEth esta en el path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

import json
import pandas as pd
from datetime import datetime, timezone, timedelta
import DataEth

def log(msg):
    # Escapar emojis para compatibilidad con cp1252
    safe = msg.encode('ascii', 'replace').decode('ascii')
    print(safe, flush=True)

log("=== EJECUTANDO DATAETH ===")

try:
    end_date = datetime.now(timezone.utc)
    htf_start = end_date - timedelta(days=5 * 365)
    ltf_start = end_date - timedelta(days=7)

    log(f"HTF: {htf_start.date()} -> {end_date.date()} (HOUR)")
    log(f"LTF: {ltf_start.date()} -> {end_date.date()} (MINUTE)")

    log("1. Descargando datos HTF (HOUR)...")
    htf_data, htf_meta = DataEth.download_data_capital('ETHUSD', 'HOUR', htf_start, end_date)
    log(f"   HTF: {len(htf_data)} registros descargados")

    log("2. Descargando datos LTF (MINUTE)...")
    ltf_data, ltf_meta = DataEth.download_data_capital('ETHUSD', 'MINUTE', ltf_start, end_date)
    log(f"   LTF: {len(ltf_data)} registros descargados")

    log("3. Calculando indicadores HTF...")
    htf_data = DataEth.calculate_indicators(htf_data, buffer_days=30, recent_days=None)
    log(f"   HTF con indicadores: {len(htf_data)} registros")

    log("4. Calculando indicadores LTF...")
    ltf_data = DataEth.calculate_ltf_indicators(ltf_data)
    log(f"   LTF con indicadores: {len(ltf_data)} registros")

    reports_dir = os.path.join(script_dir, "Reports")
    os.makedirs(reports_dir, exist_ok=True)

    # Guardar JSON legacy
    log("5. Exportando JSON legacy...")
    export_data = {'historical_data': [], 'ltf_data': []}

    for idx, row in htf_data.iterrows():
        record = {
            'timestamp': idx.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
            'Open': float(row['Open']), 'High': float(row['High']),
            'Low': float(row['Low']), 'Close': float(row['Close']), 'Volume': float(row['Volume'])
        }
        for col in row.index:
            if col not in ['Open', 'High', 'Low', 'Close', 'Volume']:
                try:
                    record[col] = float(row[col]) if pd.notna(row[col]) else 0.0
                except Exception:
                    record[col] = 0.0
        export_data['historical_data'].append(record)

    for idx, row in ltf_data.iterrows():
        record = {
            'timestamp': idx.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
            'Open': float(row['Open']), 'High': float(row['High']),
            'Low': float(row['Low']), 'Close': float(row['Close']), 'Volume': float(row['Volume'])
        }
        for col in row.index:
            if col not in ['Open', 'High', 'Low', 'Close', 'Volume']:
                try:
                    record[col] = float(row[col]) if pd.notna(row[col]) else 0.0
                except Exception:
                    record[col] = 0.0
        export_data['ltf_data'].append(record)

    json_path = os.path.join(reports_dir, "ETHUSD_CapitalData.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2)
    log(f"   JSON: {len(export_data['historical_data'])} HTF + {len(export_data['ltf_data'])} LTF -> {json_path}")

    # Guardar Parquet
    log("6. Guardando Parquet...")
    htf_parquet = os.path.join(reports_dir, "ethusd_htf_immutable.parquet")
    htf_data.to_parquet(htf_parquet, engine='pyarrow', compression='snappy')
    log(f"   HTF Parquet: {htf_parquet} ({len(htf_data)} velas)")

    ltf_parquet = os.path.join(reports_dir, "ethusd_ltf_7d.parquet")
    ltf_data.to_parquet(ltf_parquet, engine='pyarrow', compression='snappy')
    log(f"   LTF Parquet: {ltf_parquet} ({len(ltf_data)} velas)")

    log("DATAETH COMPLETADO EXITOSAMENTE")

except Exception as e:
    log(f"ERROR en DataEth: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
