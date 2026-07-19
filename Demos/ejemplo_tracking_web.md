# 🌐 Sistema de Detección de Cierres desde Web

## 📋 Funcionamiento

El Evaluador ahora detecta automáticamente cuando cierras una posición desde la web de Capital.com en lugar de dejar que el bot la cierre.

### 🔄 Flujo de Detección

1. **Tracking Continuo:** En cada ciclo, el Evaluador guarda el estado actual de todas las posiciones abiertas
2. **Comparación:** En el siguiente ciclo, compara las posiciones actuales con las previamente vistas
3. **Detección:** Si una posición desapareció sin que el bot la cerrara → fue cerrada desde la web
4. **Registro:** Guarda el último estado conocido antes del cierre

### 📁 Archivos Generados

- **`last_seen_positions.json`**: Tracking en tiempo real de posiciones abiertas
- **`web_closed_positions.txt`**: Log legible de cierres desde web
- **`web_closed_positions.json`**: Formato JSON para análisis

### 📊 Información Registrada

Cuando detecta un cierre desde web, guarda:
- ✅ DealID completo
- ✅ Última UPL vista (valor y porcentaje)
- ✅ Max profit alcanzado
- ✅ Precio de entrada
- ✅ Horas que estuvo abierta
- ✅ Última vez vista (timestamp)
- ✅ Últimos indicadores técnicos (RSI, MACD, ATR, etc.)

### 📝 Ejemplo de Registro

```
2026-02-25 15:30:45 UTC | 🌐 CERRADO DESDE WEB | DealID: 0015421d-0001-54c4-0000-00008492f207 |
EPIC: ETHUSD | Direction: SELL | Size: 0.01 | Entry: $1804.05 |
Last UPL: $-1.52 (-8.42%) | Max Profit: 0.00% | Hours Open: 24.8 |
Last Seen: 2026-02-25T15:30:42
```

### 🎯 Casos de Uso

1. **Cerrar manualmente cuando estás en pérdida** y quieres salir rápido
2. **Tomar ganancias anticipadas** desde el móvil
3. **Análisis post-mortem** de trades cerrados manualmente vs automáticamente

### ⚡ Ventajas

- No pierdes información de posiciones cerradas manualmente
- Puedes analizar si tus cierres manuales son mejores/peores que el bot
- Mantiene historial completo de todas las operaciones

