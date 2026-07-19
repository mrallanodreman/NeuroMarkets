#!/usr/bin/env python3
"""Prueba 3: variantes con guaranteedStop y stopLevel correcto."""
import requests, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from EthConfig import BASE_URL, API_KEY, LOGIN, PASSWORD

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

# Prueba D: guaranteedStop=true, sin stopLevel/limitLevel
print("=== D: guaranteedStop=true, sin SL/TP ===")
payload_d = {"epic": "ETHUSD", "direction": "BUY", "size": 0.001, "type": "MARKET", "guaranteedStop": True}
print(json.dumps(payload_d))
resp_d = requests.post(f"{BASE_URL}api/v1/positions", json=payload_d, headers=headers, timeout=15)
print(f"Status: {resp_d.status_code} | {resp_d.text[:300]}")

# Prueba E: stopLevel = 1677.66 (el maxvalue que dijo la API), guaranteedStop=true
print("\n=== E: stopLevel=1677.66, guaranteedStop=true ===")
payload_e = {"epic": "ETHUSD", "direction": "BUY", "size": 0.001, "type": "MARKET",
             "stopLevel": 1677.66, "guaranteedStop": True}
print(json.dumps(payload_e))
resp_e = requests.post(f"{BASE_URL}api/v1/positions", json=payload_e, headers=headers, timeout=15)
print(f"Status: {resp_e.status_code} | {resp_e.text[:300]}")

# Prueba F: stopLevel más cerca del precio
print("\n=== F: stopLevel=2350, guaranteedStop=true ===")
payload_f = {"epic": "ETHUSD", "direction": "BUY", "size": 0.001, "type": "MARKET",
             "stopLevel": 2350.0, "limitLevel": 2400.0, "guaranteedStop": True}
print(json.dumps(payload_f))
resp_f = requests.post(f"{BASE_URL}api/v1/positions", json=payload_f, headers=headers, timeout=15)
print(f"Status: {resp_f.status_code} | {resp_f.text[:300]}")

# Prueba G: solo guaranteedStop=true (tamaño mínimo)
print("\n=== G: guaranteedStop=true, size=0.001, epic=ETHUSD ===")
payload_g = {"epic": "ETHUSD", "direction": "BUY", "size": 0.001, "type": "MARKET", "guaranteedStop": True}
print(json.dumps(payload_g))
resp_g = requests.post(f"{BASE_URL}api/v1/positions", json=payload_g, headers=headers, timeout=15)
print(f"Status: {resp_g.status_code} | {resp_g.text[:500]}")

# Prueba H: SELL (para variar)
print("\n=== H: SELL con guaranteedStop=true ===")
payload_h = {"epic": "ETHUSD", "direction": "SELL", "size": 0.001, "type": "MARKET", "guaranteedStop": True}
print(json.dumps(payload_h))
resp_h = requests.post(f"{BASE_URL}api/v1/positions", json=payload_h, headers=headers, timeout=15)
print(f"Status: {resp_h.status_code} | {resp_h.text[:500]}")

print("\n=== FIN ===")
