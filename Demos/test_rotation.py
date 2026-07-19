#!/usr/bin/env python3
"""
Script de prueba para demostrar la rotación de APIs
Descarga 7 días de datos en segmentos pequeños para ver la rotación
"""

import pandas as pd
from datetime import datetime, timedelta
import pytz
import time
import requests

# ========== SISTEMA DE ROTACIÓN DE APIs ==========
class APIRotator:
    """Rotador de APIs para distribuir carga entre Binance, Kraken y CryptoCompare"""
    def __init__(self):
        self.apis = ['binance', 'kraken', 'cryptocompare']
        self.current_index = 0
        self.request_count = {'binance': 0, 'kraken': 0, 'cryptocompare': 0}
        self.error_count = {'binance': 0, 'kraken': 0, 'cryptocompare': 0}

    def get_next_api(self):
        """Obtiene la siguiente API en rotación"""
        api = self.apis[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.apis)
        return api

    def record_request(self, api, success=True):
        """Registra una petición a una API"""
        self.request_count[api] += 1
        if not success:
            self.error_count[api] += 1

    def get_stats(self):
        """Obtiene estadísticas de uso"""
        return {
            'requests': self.request_count.copy(),
            'errors': self.error_count.copy()
        }

# Instancia global del rotador
api_rotator = APIRotator()

# ========== FUNCIONES DE DESCARGA POR API ==========
def download_binance(start_date, end_date):
    """Descarga datos desde Binance Spot API"""
    try:
        url = "https://api.binance.com/api/v3/klines"

        params = {
            'symbol': 'ETHUSDT',
            'interval': '1h',
            'startTime': int(start_date.timestamp() * 1000),
            'endTime': int(end_date.timestamp() * 1000),
            'limit': 1000
        }

        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()
            if data:
                api_rotator.record_request('binance', success=True)
                return len(data)

        api_rotator.record_request('binance', success=False)
        return 0
    except Exception as e:
        api_rotator.record_request('binance', success=False)
        return 0

def download_kraken(start_date, end_date):
    """Descarga datos desde Kraken API"""
    try:
        url = "https://api.kraken.com/0/public/OHLC"

        params = {
            'pair': 'ETHUSD',
            'interval': 60,
            'since': int(start_date.timestamp())
        }

        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()
            if 'result' in data:
                pair_key = next(iter([k for k in data['result'].keys() if 'ETH' in k]), None)
                if pair_key:
                    api_rotator.record_request('kraken', success=True)
                    return len(data['result'][pair_key])

        api_rotator.record_request('kraken', success=False)
        return 0
    except Exception as e:
        api_rotator.record_request('kraken', success=False)
        return 0

def download_cryptocompare(start_date, end_date):
    """Descarga datos desde CryptoCompare API"""
    try:
        url = "https://min-api.cryptocompare.com/data/v2/histohour"

        params = {
            'fsym': 'ETH',
            'tsym': 'USD',
            'limit': 2000,
            'toTs': int(end_date.timestamp())
        }

        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()
            if data.get('Response') == 'Success':
                api_rotator.record_request('cryptocompare', success=True)
                return len(data['Data']['Data'])

        api_rotator.record_request('cryptocompare', success=False)
        return 0
    except Exception as e:
        api_rotator.record_request('cryptocompare', success=False)
        return 0

# ========== FUNCIÓN DE DESCARGA CON ROTACIÓN ==========
def download_with_rotation(start_date, end_date, segment_number):
    """Descarga datos rotando entre las 3 APIs"""
    api = api_rotator.get_next_api()
    print(f"  Segmento {segment_number}: {start_date.strftime('%Y-%m-%d %H:%M')} → {end_date.strftime('%Y-%m-%d %H:%M')}")
    print(f"    └─ Usando {api.upper()}...", end=" ")

    count = 0
    if api == 'binance':
        count = download_binance(start_date, end_date)
    elif api == 'kraken':
        count = download_kraken(start_date, end_date)
    elif api == 'cryptocompare':
        count = download_cryptocompare(start_date, end_date)

    if count > 0:
        print(f"✅ {count} velas")
    else:
        print(f"❌ sin datos")

    time.sleep(0.5)  # Rate limiting
    return count

# ========== PRUEBA ==========
print("="*70)
print("🔄 DEMOSTRACIÓN DE ROTACIÓN DE APIs")
print("="*70)
print()

# Descargar 7 días en segmentos de 2 días cada uno
end_date = datetime.now(pytz.UTC).replace(minute=0, second=0, microsecond=0)
start_date = end_date - timedelta(days=7)

print(f"📅 Período: {start_date.strftime('%Y-%m-%d')} hasta {end_date.strftime('%Y-%m-%d')}")
print(f"📦 Segmentos de 2 días cada uno")
print()

current = start_date
segment_num = 1

while current < end_date:
    seg_end = min(current + timedelta(days=2), end_date)
    download_with_rotation(current, seg_end, segment_num)
    current = seg_end
    segment_num += 1

# Mostrar estadísticas
stats = api_rotator.get_stats()
print()
print("="*70)
print("📊 ESTADÍSTICAS DE ROTACIÓN")
print("="*70)
total_requests = sum(stats['requests'].values())
total_errors = sum(stats['errors'].values())

for api_name in ['binance', 'kraken', 'cryptocompare']:
    requests = stats['requests'][api_name]
    errors = stats['errors'][api_name]
    success_rate = ((requests - errors) / requests * 100) if requests > 0 else 0
    percent_of_total = (requests / total_requests * 100) if total_requests > 0 else 0

    print(f"  {api_name.upper():14s}: {requests:2d} peticiones ({percent_of_total:5.1f}%) | "
          f"{errors:2d} errores | {success_rate:5.1f}% éxito")

print("="*70)
print(f"✅ TOTAL: {total_requests} peticiones | {total_errors} errores | "
      f"{((total_requests - total_errors) / total_requests * 100):.1f}% éxito global")
print("="*70)
print()
print("💡 La rotación distribuye la carga equilibradamente entre las 3 APIs")
print("   evitando saturar los límites gratuitos de cualquiera de ellas.")
print("="*70)
