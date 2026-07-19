#!/usr/bin/env python3
"""
Utilidad para gestionar missing_ranges.json
Permite inspeccionar, limpiar y editar rangos sin datos
"""
import os
import sys
import json
from datetime import datetime
import pytz

REPORTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Reports')
MISSING_FILE = os.path.join(REPORTS, 'missing_ranges.json')

def load():
    if not os.path.exists(MISSING_FILE):
        return {}
    with open(MISSING_FILE, 'r') as f:
        return json.load(f)

def save(m):
    os.makedirs(REPORTS, exist_ok=True)
    with open(MISSING_FILE, 'w') as f:
        json.dump(m, f, indent=2, default=str)

def show():
    """Muestra todos los rangos registrados"""
    m = load()
    if not m:
        print("✅ No hay rangos sin datos registrados")
        return

    print(f"\n📊 Total: {len(m)} rango(s) sin datos\n")
    print("-" * 100)
    for key, entry in m.items():
        attempts = entry.get('attempts', 0)
        last = entry.get('last_attempt', 'N/A')
        reason = entry.get('reason', 'N/A')
        print(f"🔸 {key}")
        print(f"   Intentos: {attempts}/3")
        print(f"   Último intento: {last}")
        print(f"   Razón: {reason}")
        print("-" * 100)

def clear_all():
    """Limpia todos los rangos"""
    m = load()
    count = len(m)
    if count == 0:
        print("✅ No hay rangos para limpiar")
        return

    confirm = input(f"⚠️  ¿Seguro que quieres limpiar {count} rango(s)? (s/N): ")
    if confirm.lower() != 's':
        print("❌ Operación cancelada")
        return

    save({})
    print(f"✅ {count} rango(s) limpiados")

def clear_maxed():
    """Limpia solo rangos que alcanzaron max attempts"""
    m = load()
    maxed = {k: v for k, v in m.items() if v.get('attempts', 0) >= 3}
    if not maxed:
        print("✅ No hay rangos con max attempts alcanzado")
        return

    print(f"🔍 Encontrados {len(maxed)} rango(s) con max attempts:")
    for k in maxed.keys():
        print(f"   - {k}")

    confirm = input(f"⚠️  ¿Limpiar estos {len(maxed)} rango(s)? (s/N): ")
    if confirm.lower() != 's':
        print("❌ Operación cancelada")
        return

    for k in maxed.keys():
        m.pop(k)
    save(m)
    print(f"✅ {len(maxed)} rango(s) limpiados")

def reset_attempts():
    """Resetea el contador de intentos de todos los rangos"""
    m = load()
    if not m:
        print("✅ No hay rangos registrados")
        return

    confirm = input(f"⚠️  ¿Resetear intentos de {len(m)} rango(s)? (s/N): ")
    if confirm.lower() != 's':
        print("❌ Operación cancelada")
        return

    for entry in m.values():
        entry['attempts'] = 0
    save(m)
    print(f"✅ {len(m)} rango(s) reseteados a 0 intentos")

def stats():
    """Muestra estadísticas"""
    m = load()
    if not m:
        print("✅ No hay rangos registrados")
        return

    total = len(m)
    by_attempts = {}
    by_reason = {}

    for entry in m.values():
        attempts = entry.get('attempts', 0)
        reason = entry.get('reason', 'unknown')
        by_attempts[attempts] = by_attempts.get(attempts, 0) + 1
        by_reason[reason] = by_reason.get(reason, 0) + 1

    print(f"\n📊 Estadísticas de missing_ranges.json\n")
    print(f"Total rangos: {total}")
    print(f"\nPor intentos:")
    for att, count in sorted(by_attempts.items()):
        print(f"  {att} intentos: {count} rango(s)")
    print(f"\nPor razón:")
    for reason, count in sorted(by_reason.items()):
        print(f"  {reason}: {count} rango(s)")

def help_menu():
    print("""
🛠️  Utilidad de gestión de missing_ranges.json

Uso: python3 tools/manage_missing_ranges.py [comando]

Comandos:
  show          Mostrar todos los rangos registrados
  stats         Mostrar estadísticas
  clear-all     Limpiar todos los rangos
  clear-maxed   Limpiar solo rangos con max attempts (>=3)
  reset         Resetear contador de intentos a 0
  help          Mostrar este mensaje

Ejemplos:
  python3 tools/manage_missing_ranges.py show
  python3 tools/manage_missing_ranges.py stats
  python3 tools/manage_missing_ranges.py clear-maxed
""")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        help_menu()
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == 'show':
        show()
    elif cmd == 'stats':
        stats()
    elif cmd == 'clear-all':
        clear_all()
    elif cmd == 'clear-maxed':
        clear_maxed()
    elif cmd == 'reset':
        reset_attempts()
    elif cmd == 'help':
        help_menu()
    else:
        print(f"❌ Comando desconocido: {cmd}")
        help_menu()
        sys.exit(1)
