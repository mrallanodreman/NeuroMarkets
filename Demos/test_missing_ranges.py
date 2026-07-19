#!/usr/bin/env python3
"""
Test script para verificar la mecánica de persistencia de tramos sin datos.
Simula:
1. Registro de un tramo sin datos
2. Verificación de cooldown
3. Contador de intentos
4. Marca permanente después de MAX_ATTEMPTS_PER_RANGE
"""
import os
import sys
import json
from datetime import datetime, timedelta
import pytz

# Importar funciones de DataEth
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock las variables globales necesarias antes de importar
import DataEth
DataEth.ATTEMPT_COOLDOWN_HOURS = 24
DataEth.MAX_ATTEMPTS_PER_RANGE = 3

from DataEth import _load_missing_ranges, _save_missing_ranges, _should_skip_range, _register_missing_range, _clear_missing_range

REPORTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Reports')
MISSING_FILE = os.path.join(REPORTS, 'missing_ranges.json')

def cleanup():
    """Limpiar archivo de test previo"""
    if os.path.exists(MISSING_FILE):
        # Hacer backup
        backup = MISSING_FILE + '.bak'
        os.rename(MISSING_FILE, backup)
        print(f"[INFO] Backup creado: {backup}")

def restore():
    """Restaurar backup si existe"""
    backup = MISSING_FILE + '.bak'
    if os.path.exists(backup):
        os.rename(backup, MISSING_FILE)
        print(f"[INFO] Backup restaurado desde {backup}")

def test_missing_ranges():
    print("\n" + "="*60)
    print("TEST: Mecánica de persistencia de tramos sin datos")
    print("="*60 + "\n")

    # Limpiar estado previo
    cleanup()

    # Test 1: Registrar primer tramo sin datos
    print("\n--- Test 1: Registrar primer tramo sin datos ---")
    start = datetime(2026, 2, 16, 1, 0, 0, tzinfo=pytz.UTC)
    end = datetime(2026, 2, 16, 6, 0, 0, tzinfo=pytz.UTC)
    _register_missing_range(start, end, reason="no-data")

    missing = _load_missing_ranges()
    key = f"{start.isoformat()}->{end.isoformat()}"
    assert key in missing, "❌ Rango no registrado"
    assert missing[key]['attempts'] == 1, "❌ Contador de intentos incorrecto"
    print("✅ Test 1 PASADO: Rango registrado con attempts=1")

    # Test 2: Verificar cooldown (debe saltar)
    print("\n--- Test 2: Verificar cooldown activo ---")
    skip, reason = _should_skip_range(start, end, missing)
    assert skip == True, "❌ Debería saltar por cooldown"
    assert "cooldown activo" in reason, f"❌ Razón incorrecta: {reason}"
    print(f"✅ Test 2 PASADO: Rango saltado ({reason})")

    # Test 3: Forzar timestamp antiguo para simular cooldown expirado
    print("\n--- Test 3: Simular cooldown expirado ---")
    old_time = (datetime.now(pytz.UTC) - timedelta(hours=25)).isoformat()
    missing[key]['last_attempt'] = old_time
    _save_missing_ranges(missing)

    skip, reason = _should_skip_range(start, end, _load_missing_ranges())
    assert skip == False, "❌ No debería saltar (cooldown expirado)"
    print("✅ Test 3 PASADO: Cooldown expirado, permite reintento")

    # Test 4: Incrementar intentos y verificar límite
    print("\n--- Test 4: Verificar límite de intentos ---")
    _register_missing_range(start, end, reason="no-data")  # intento 2
    _register_missing_range(start, end, reason="no-data")  # intento 3

    missing = _load_missing_ranges()
    assert missing[key]['attempts'] == 3, f"❌ Contador incorrecto: {missing[key]['attempts']}"
    print(f"✅ Test 4a PASADO: Contador en {missing[key]['attempts']}/{DataEth.MAX_ATTEMPTS_PER_RANGE}")

    # Ahora debe saltar por max attempts
    skip, reason = _should_skip_range(start, end, missing)
    assert skip == True, "❌ Debería saltar por max_attempts"
    assert "max_attempts" in reason, f"❌ Razón incorrecta: {reason}"
    print(f"✅ Test 4b PASADO: Rango marcado permanente ({reason})")

    # Test 5: Limpiar rango cuando se obtienen datos
    print("\n--- Test 5: Limpiar rango cuando se obtienen datos ---")
    start2 = datetime(2026, 2, 17, 10, 0, 0, tzinfo=pytz.UTC)
    end2 = datetime(2026, 2, 17, 12, 0, 0, tzinfo=pytz.UTC)
    _register_missing_range(start2, end2, reason="no-data")

    missing_before = _load_missing_ranges()
    key2 = f"{start2.isoformat()}->{end2.isoformat()}"
    assert key2 in missing_before, "❌ Rango no registrado"

    _clear_missing_range(start2, end2)
    missing_after = _load_missing_ranges()
    assert key2 not in missing_after, "❌ Rango no eliminado"
    print("✅ Test 5 PASADO: Rango limpiado correctamente")

    # Mostrar contenido final
    print("\n--- Contenido final de missing_ranges.json ---")
    final = _load_missing_ranges()
    print(json.dumps(final, indent=2, default=str))

    # Restaurar backup
    print("\n--- Restaurando estado original ---")
    restore()

    print("\n" + "="*60)
    print("✅ TODOS LOS TESTS PASARON")
    print("="*60 + "\n")

if __name__ == '__main__':
    try:
        test_missing_ranges()
    except AssertionError as e:
        print(f"\n❌ TEST FALLÓ: {e}\n")
        restore()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        restore()
        sys.exit(1)
