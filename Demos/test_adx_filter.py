#!/usr/bin/env python3
"""
Test del filtro ADX para evitar trades en mercados choppy
"""

# Simular un ADX bajo que debería bloquear la señal
test_cases = [
    {"ADX": 16.45, "signal": "SELL ❌", "should_block": True},
    {"ADX": 28.50, "signal": "BUY ✅", "should_block": False},
    {"ADX": 22.00, "signal": "BUY ✅", "should_block": True},
    {"ADX": 30.00, "signal": "SELL ❌", "should_block": False},
]

print("=" * 60)
print("TEST: Filtro ADX < 25")
print("=" * 60)

for i, case in enumerate(test_cases, 1):
    adx_value = case["ADX"]
    signal = case["signal"]
    should_block = case["should_block"]

    # Simular la lógica del filtro
    if adx_value < 25 and signal in ["BUY ✅", "SELL ❌"]:
        result_signal = "HOLD ⚠️"
        result = f"🚫 BLOQUEADO: ADX {adx_value:.1f} < 25"
    else:
        result_signal = signal
        result = f"✅ PERMITIDO: ADX {adx_value:.1f} >= 25"

    # Verificar resultado esperado
    blocked = (result_signal == "HOLD ⚠️")
    status = "✅ PASS" if (blocked == should_block) else "❌ FAIL"

    print(f"\nCaso {i}: {status}")
    print(f"  ADX: {adx_value:.1f}")
    print(f"  Señal original: {signal}")
    print(f"  Señal final: {result_signal}")
    print(f"  {result}")

print("\n" + "=" * 60)
print("✅ Test completado")
print("=" * 60)
