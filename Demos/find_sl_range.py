#!/usr/bin/env python3
"""Encuentra el rango exacto de stopLevel permitido y revisa el endpoint /markets."""
import requests, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from EthConfig import BASE_URL, API_KEY, LOGIN, PASSWORD

# Autenticar
r = requests.post(f"{BASE_URL}api/v1/session", json={
    "identifier": LOGIN, "password": PASSWORD, "encryptedPassword": False
}, headers={
    "Content-Type": "application/json", "X-CAP-API-KEY": API_KEY
}, timeout=15)
cst, sec_token = r.headers.get("CST"), r.headers.get("X-SECURITY-TOKEN")
headers = {
    "Content-Type": "application/json", "X-CAP-API-KEY": API_KEY,
    "CST": cst, "X-SECURITY-TOKEN": sec_token,
}

# 1. Obtener info del mercado ETHUSD
print("=== INFO MERCADO ETHUSD ===")
mr = requests.get(f"{BASE_URL}api/v1/markets/ETHUSD", headers=headers, timeout=10)
if mr.status_code == 200:
    data = mr.json()
    # Extraer solo campos relevantes de GSL, stop, etc.
    snap = data.get("snapshot", {})
    print(f"Precio bid: {snap.get('bid')}, offer: {snap.get('offer')}")
    # Dealing rules
    dr = data.get("dealingRules", {})
    if dr:
        gsl = dr.get("guaranteedStopLoss", {})
        print(f"\nGuaranteed Stop Loss rules:")
        print(json.dumps(gsl, indent=2))
        if "minDistance" in gsl:
            print(f"\nMin distance (value): {gsl['minDistance'].get('value', 'N/A')}")
        # Market order rules
        mor = dr.get("marketOrder", {})
        print(f"\nMarket Order rules:")
        print(json.dumps(mor, indent=2))
    else:
        print("No dealingRules found")
        print(json.dumps(data, indent=2)[:2000])
else:
    print(f"Error: {mr.status_code} - {mr.text}")

# 2. Precio actual
current_mid = (snap.get("bid", 0) + snap.get("offer", 0)) / 2 if mr.status_code == 200 else 2375
print(f"\nPrecio mid actual: ~${current_mid:.2f}")

# 3. Encontrar el stopLevel máximo permitido (búsqueda binaria)
print(f"\n=== BUSCANDO LÍMITE EXACTO DE STOPLOSS (BUY ETHUSD) ===")
lo, hi = 1000, int(current_mid)
best = lo
for _ in range(10):
    mid = (lo + hi) // 2
    payload = {"epic": "ETHUSD", "direction": "BUY", "size": 0.001, "type": "MARKET",
               "stopLevel": float(mid), "guaranteedStop": True}
    resp = requests.post(f"{BASE_URL}api/v1/positions", json=payload, headers=headers, timeout=10)
    if resp.status_code == 200:
        # Aceptado - probar más cerca del precio
        best = mid
        lo = mid + 1
        print(f"  stopLevel={mid} ✅ (aceptado) -> subiendo límite")
    else:
        hi = mid - 1
        err = resp.json().get("errorCode", resp.text[:100])
        print(f"  stopLevel={mid} ❌ ({err}) -> bajando límite")

print(f"\n✅ stopLevel MÁXIMO permitido para BUY: ~${best:.2f}")
print(f"   Distancia desde precio actual (${current_mid:.2f}): ${current_mid - best:.2f} ({((current_mid - best)/current_mid)*100:.1f}%)")

# 4. Lo mismo para SELL
print(f"\n=== BUSCANDO LÍMITE EXACTO DE STOPLOSS (SELL ETHUSD) ===")
lo2, hi2 = int(current_mid), int(current_mid * 1.5)
best2 = lo2
for _ in range(10):
    mid = (lo2 + hi2) // 2
    payload = {"epic": "ETHUSD", "direction": "SELL", "size": 0.001, "type": "MARKET",
               "stopLevel": float(mid), "guaranteedStop": True}
    resp = requests.post(f"{BASE_URL}api/v1/positions", json=payload, headers=headers, timeout=10)
    if resp.status_code == 200:
        best2 = mid
        lo2 = mid + 1
        print(f"  stopLevel={mid} ✅ (aceptado) -> subiendo límite")
    else:
        hi2 = mid - 1
        err = resp.json().get("errorCode", resp.text[:100])
        print(f"  stopLevel={mid} ❌ ({err}) -> bajando límite")

print(f"\n✅ stopLevel MÍNIMO permitido para SELL: ~${best2:.2f}")
print(f"   Distancia desde precio actual (${current_mid:.2f}): ${best2 - current_mid:.2f} ({((best2 - current_mid)/current_mid)*100:.1f}%)")

print(f"\n=== RESUMEN ===")
print(f"BUY:  stopLevel ≤ ${best:.2f}  (distancia ≥ ${current_mid - best:.2f})")
print(f"SELL: stopLevel ≥ ${best2:.2f} (distancia ≥ ${best2 - current_mid:.2f})")
