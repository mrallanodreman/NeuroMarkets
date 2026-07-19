#!/usr/bin/env python3
import pandas as pd
from DataLoader import DataLoader

# Cargar HTF
dl = DataLoader()
htf, _ = dl.load_historical_data()

# Último registro HTF
latest = htf.iloc[-1]

print('=== INDICADORES HTF (HOUR) - ÚLTIMA VELA ===')
print(f'Timestamp: {htf.index[-1]}')
print(f'Close: ${latest["Close"]:.2f}')
print(f'EMA_20: ${latest.get("EMA_20", 0):.2f}')
print(f'EMA_50: ${latest.get("EMA_50", 0):.2f}')
print(f'RSI: {latest.get("RSI", 0):.2f}')
print(f'RSI_7: {latest.get("RSI_7", 0):.2f}')
print(f'MACD_Histogram: {latest.get("MACD_Histogram", 0):.4f}')
print(f'ADX: {latest.get("ADX", 0):.2f}')
print(f'Volume_Ratio: {latest.get("Volume_Ratio", 0):.2f}')
print(f'OBV_Trend: {latest.get("OBV_Trend", 0)}')
print(f'Market_Regime: {latest.get("Market_Regime", "N/A")}')
print()
print('=== CÁLCULO DE SCORE BUY (simulado) ===')
score = 0
detalles = []

if latest['EMA_20'] > latest['EMA_50']:
    score += 2
    detalles.append('+2: EMA_20 > EMA_50 ✅')
else:
    detalles.append('+0: EMA_20 <= EMA_50 ❌')

rsi7 = latest.get('RSI_7', 0)
if 30 < rsi7 < 65:
    score += 2
    detalles.append(f'+2: RSI_7={rsi7:.1f} en [30-65] ✅')
else:
    detalles.append(f'+0: RSI_7={rsi7:.1f} fuera de [30-65] ❌')

if latest.get('MACD_Histogram', 0) > 0:
    score += 1
    detalles.append('+1: MACD_Histogram > 0 ✅')
else:
    detalles.append('+0: MACD_Histogram <= 0 ❌')

obv = latest.get('OBV_Trend', 0)
vol = latest.get('Volume_Ratio', 0)
if obv == 1 and vol > 1.1:
    score += 2
    detalles.append(f'+2: OBV=1 + Vol={vol:.2f}>1.1 ✅')
elif vol > 0.8:
    score += 1
    detalles.append(f'+1: Vol={vol:.2f}>0.8 ✅')
else:
    detalles.append(f'+0: Vol={vol:.2f}<=0.8 ❌')

regime = latest.get('Market_Regime', 'CHOPPY')
adx = latest.get('ADX', 0)
if regime == 'TRENDING' and adx > 25:
    score += 1
    detalles.append('+1: TRENDING + ADX>25 ✅')
elif regime == 'RANGING':
    score -= 1
    detalles.append('-1: RANGING ❌')
else:
    detalles.append(f'+0: {regime} + ADX={adx:.1f}<=25 ❌')

print()
for d in detalles:
    print(d)
print()
print(f'SCORE TOTAL: {score}/8')
print(f'Mínimo requerido: 4/8 (50%)')
if score >= 4:
    print('✅ SEÑAL: BUY VALIDADO')
else:
    print(f'❌ SEÑAL: HOLD - Confianza insuficiente ({score}/8 < 4/8)')
print()
print('=== CONCLUSIÓN ===')
if adx < 25:
    print(f'⚠️ ADX={adx:.1f} < 25 → Mercado sin tendencia clara (CHOPPY)')
    print('   La estrategia NO opera en mercados choppy por seguridad.')
if rsi7 >= 65:
    print(f'⚠️ RSI_7={rsi7:.1f} >= 65 → Zona de sobrecompra')
    print('   Pierde 2 puntos de confianza.')
