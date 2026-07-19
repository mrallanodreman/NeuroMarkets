#!/usr/bin/env python3
"""
Prueba 2: corrige el payload agregando guaranteedStop.
"""
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

# Prueba A: con guaranteedStop=false
print("=== PRUEBA A: guaranteedStop=false ===")
payload_a = {
    "epic": "ETHUSD", "direction": "BUY", "size": 0.001, "type": "MARKET",
    "stopLevel": 2300.0, "limitLevel": 2450.0,
    "guaranteedStop": False,
}
print(f"Payload: {json.dumps(payload_a, indent=2)}")
resp_a = requests.post(f"{BASE_URL}api/v1/positions", json=payload_a, headers=headers, timeout=15)
print(f"Status: {resp_a.status_code}")
try:
    print(f"Resp: {json.dumps(resp_a.json(), indent=2)}")
except:
    print(f"Resp: {resp_a.text}")

# Prueba B: sin stopLevel/limitLevel
print("\n=== PRUEBA B: solo MARKET (sin SL/TP) ===")
payload_b = {
    "epic": "ETHUSD", "direction": "BUY", "size": 0.001, "type": "MARKET",
}
print(f"Payload: {json.dumps(payload_b, indent=2)}")
resp_b = requests.post(f"{BASE_URL}api/v1/positions", json=payload_b, headers=headers, timeout=15)
print(f"Status: {resp_b.status_code}")
try:
    print(f"Resp: {json.dumps(resp_b.json(), indent=2)}")
except:
    print(f"Resp: {resp_b.text}")

# Prueba C: stopLevel con guaranteedStop=true
print("\n=== PRUEBA C: guaranteedStop=true ===")
payload_c = {
    "epic": "ETHUSD", "direction": "BUY", "size": 0.001, "type": "MARKET",
    "stopLevel": 2300.0, "limitLevel": 2450.0,
    "guaranteedStop": True,
}
print(f"Payload: {json.dumps(payload_c, indent=2)}")
resp_c = requests.post(f"{BASE_URL}api/v1/positions", json=payload_c, headers=headers, timeout=15)
print(f"Status: {resp_c.status_code}")
try:
    print(f"Resp: {json.dumps(resp_c.json(), indent=2)}")
except:
    print(f"Resp: {resp_c.text}")

print("\n=== HECHO ===")
