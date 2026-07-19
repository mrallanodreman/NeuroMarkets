#!/usr/bin/env python3
import os
import json
import shutil
from datetime import datetime
import pandas as pd

# Import helper from verify_indicators (safe; main guarded)
from verify_indicators import load_reports, calculate_indicators_local

REPORTS_PATH = 'Reports/ETHUSD_CapitalData.json'
BACKUP_DIR = 'Reports/backup'

os.makedirs(BACKUP_DIR, exist_ok=True)
# Backup current file
if os.path.exists(REPORTS_PATH):
    ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    shutil.copy2(REPORTS_PATH, os.path.join(BACKUP_DIR, f'ETHUSD_CapitalData.json.{ts}.bak'))
    print(f"[INFO] Backup creado: {BACKUP_DIR}/ETHUSD_CapitalData.json.{ts}.bak")

# Load reports
h, l = load_reports(REPORTS_PATH)
print(f"[INFO] HTF filas={len(h)} LTF filas={len(l)}")

# Normalize and dedupe HTF
def normalize_and_dedupe(df):
    if df is None or df.empty:
        return df
    df2 = df.reset_index().copy()
    if 'Datetime' not in df2.columns:
        # try snapshotTime
        if 'snapshotTime' in df2.columns:
            df2['Datetime'] = pd.to_datetime(df2['snapshotTime'], utc=True, errors='coerce')
    else:
        df2['Datetime'] = pd.to_datetime(df2['Datetime'], utc=True, errors='coerce')
    before = len(df2)
    df2.dropna(subset=['Datetime'], inplace=True)
    df2 = df2[~df2['Datetime'].duplicated(keep='last')]
    after = len(df2)
    print(f"[INFO] Dedupe: {before-after} filas duplicadas eliminadas")
    df2.set_index('Datetime', inplace=True)
    df2.sort_index(inplace=True)
    return df2

h_clean = normalize_and_dedupe(h)
l_clean = normalize_and_dedupe(l)

# Recalculate indicators using verify_indicators logic
h_recalc = calculate_indicators_local(h_clean)
l_recalc = calculate_indicators_local(l_clean)

# Serialize back to JSON (Datetime -> ISO)
def df_to_records(df):
    if df is None or df.empty:
        return []
    r = df.reset_index().copy()
    r['Datetime'] = r['Datetime'].apply(lambda x: x.isoformat())
    return r.to_dict(orient='records')

out = {
    'historical_data': df_to_records(h_recalc),
    'data': df_to_records(l_recalc)
}

with open(REPORTS_PATH, 'w') as f:
    json.dump(out, f, indent=2, ensure_ascii=False)

print(f"[INFO] Reports reemplazado con versión deduplicada y recalculada: {REPORTS_PATH}")
