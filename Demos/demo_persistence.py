#!/usr/bin/env python3
"""Demo rápido de la funcionalidad de persistencia"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Solo importar las constantes y funciones necesarias (evitar ejecución de DataEth)
import json
import pytz
from datetime import datetime, timedelta

# Re-implementar las funciones aquí para evitar imports
REPORTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Reports')
MISSING_FILE = os.path.join(REPORTS, 'missing_ranges.json')

MAX_ATTEMPTS_PER_RANGE = 3
ATTEMPT_COOLDOWN_HOURS = 24

def _load_missing_ranges():
    if not os.path.exists(MISSING_FILE):
        return {}
    try:
        with open(MISSING_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARNING] Error al leer missing_ranges.json: {e}")
        return {}

def _save_missing_ranges(missing):
    os.makedirs(REPORTS, exist_ok=True)
    try:
        with open(MISSING_FILE, 'w') as f:
            json.dump(missing, f, indent=2, default=str)
    except Exception as e:
        print(f"[ERROR] Error al guardar missing_ranges.json: {e}")

def _register_missing_range(start, end, reason="no-data"):
    missing = _load_missing_ranges()
    key = f"{start.isoformat()}->{end.isoformat()}"
    now = datetime.now(pytz.UTC)

    if key in missing:
        missing[key]['attempts'] = missing[key].get('attempts', 0) + 1
        missing[key]['last_attempt'] = now.isoformat()
        missing[key]['reason'] = reason
    else:
        missing[key] = {
            'start': start.isoformat(),
            'end': end.isoformat(),
            'attempts': 1,
            'last_attempt': now.isoformat(),
            'reason': reason
        }

    _save_missing_ranges(missing)
    attempts = missing[key]['attempts']
    print(f"[INFO] 📝 Rango {key} registrado (intento {attempts}/{MAX_ATTEMPTS_PER_RANGE}, motivo: {reason})")
    return missing

# Demo
print("=" * 80)
print("DEMO: Sistema de Persistencia de Tramos Sin Datos")
print("=" * 80)

print("\n1️⃣  Registrando primer rango sin datos...")
start1 = datetime(2026, 2, 16, 1, 0, 0, tzinfo=pytz.UTC)
end1 = datetime(2026, 2, 16, 6, 0, 0, tzinfo=pytz.UTC)
missing = _register_missing_range(start1, end1, 'demo-no-data')

print("\n2️⃣  Registrando segundo rango sin datos...")
start2 = datetime(2026, 2, 17, 10, 30, 0, tzinfo=pytz.UTC)
end2 = datetime(2026, 2, 17, 14, 0, 0, tzinfo=pytz.UTC)
missing = _register_missing_range(start2, end2, 'demo-api-error')

print("\n3️⃣  Incrementando intentos del primer rango...")
missing = _register_missing_range(start1, end1, 'demo-no-data')
missing = _register_missing_range(start1, end1, 'demo-no-data')

print("\n4️⃣  Contenido de missing_ranges.json:")
print("-" * 80)
print(json.dumps(missing, indent=2, default=str))
print("-" * 80)

print(f"\n✅ Demo completado. Archivo guardado en: {MISSING_FILE}")
print(f"\n💡 Para ver el contenido:")
print(f"   cat {MISSING_FILE}")
print(f"\n💡 Para gestionar rangos:")
print(f"   python3 tools/manage_missing_ranges.py show")
