import sys
import json
import os
sys.path.insert(0, os.path.dirname(__file__))

import Evaluador

def main():
    # Simular una posición que nunca alcanzó 10% y tiene momentum débil
    positions = [
        {
            "market": {"epic": "DEMO.EPIC", "instrumentName": "DemoAsset"},
            "position": {
                "dealId": "DEAL12345678",
                "direction": "BUY",
                "size": 1.0,
                "level": 100.0,
                "upl": 0.0007,
                "upl_pct": 0.07,  # 0.07% (never cerca de 10%)
                "createdDateUTC": "2026-02-20T12:00:00Z"
            }
        }
    ]

    # Momentum débil -> score < 30
    features = {
        "momentum_score": 20.0,
        "RSI": 40,
        "MACD": -0.5,
        "VolumeChange": -1
    }

    profittracker = {}

    print("Ejecutando evaluate_positions con posición de prueba...")
    to_close = Evaluador.evaluate_positions(positions, features, profittracker, debug_callback=print)

    print("Resultado to_close:")
    print(json.dumps(to_close, indent=2))
    print("Profittracker después:")
    print(json.dumps(profittracker, indent=2))

if __name__ == '__main__':
    main()
