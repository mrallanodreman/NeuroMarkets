#!/usr/bin/env python3
"""
Manual test: abrir una posición a precio de mercado (precio actual) en la cuenta DEMO.

Consolida el flujo probado manualmente:
  1. Autenticar contra Capital.com (credenciales desde EthConfig / variables de entorno).
  2. Resolver la cuenta activa (usa CAPITAL_ACCOUNT_ID si es válida; si no, cae a la
     única cuenta disponible y avisa del desajuste).
  3. Leer el precio actual de ETHUSD.
  4. Calcular el Stop Loss con Strategia.get_sl_tp_levels(), que respeta el flag de
     entorno STOP_LOSS (si STOP_LOSS=true -> stop al 99% de distancia).
  5. Abrir la posición con CapitalOP.open_position().

⚠️  Este script ENVÍA ÓRDENES REALES a la cuenta configurada. Pensado para la cuenta
    DEMO (CAPITAL_OPERATION_MODE=demo). Por seguridad, por defecto hace un DRY-RUN
    (solo preflight): hay que pasar --execute para abrir la posición de verdad.

Uso:
    # Dry-run (no abre nada, solo muestra precio/cuenta/stop calculado):
    python ManualTests/open_position_at_market.py

    # Abrir BUY 0.001 ETHUSD a mercado (con STOP_LOSS=true para stop al 99%):
    STOP_LOSS=true python ManualTests/open_position_at_market.py --execute

    # SELL de 0.01:
    python ManualTests/open_position_at_market.py --execute --direction SELL --size 0.01
"""
import argparse
import os
import sys

# Permitir ejecutar el script desde cualquier directorio (añade Demos/ al path)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EthSession import CapitalOP
from EthStrategy import Strategia
from EthConfig import STOP_LOSS, STOP_LOSS_PCT


def resolve_account(capital_ops):
    """Devuelve un account_id válido. Prefiere el configurado; si no está entre los
    disponibles, cae a la única cuenta accesible. Devuelve None si es ambiguo."""
    available = capital_ops.get_available_accounts()
    available_ids = [a["accountId"] for a in available]

    if capital_ops.account_id and capital_ops.account_id in available_ids:
        return capital_ops.account_id

    print(f"[WARNING] ⚠️ account_id configurado ({capital_ops.account_id!r}) no está "
          f"entre las cuentas disponibles: {available_ids}")
    if len(available_ids) == 1:
        print(f"[INFO] Usando la única cuenta disponible: {available_ids[0]}")
        return available_ids[0]
    print("[ERROR] ❌ No se puede resolver la cuenta automáticamente "
          "(0 o varias cuentas disponibles). Configura CAPITAL_ACCOUNT_ID.")
    return None


def main():
    parser = argparse.ArgumentParser(description="Abrir posición a precio de mercado (DEMO).")
    parser.add_argument("--direction", choices=["BUY", "SELL"], default="BUY",
                        help="Dirección de la posición (default: BUY).")
    parser.add_argument("--size", type=float, default=0.001,
                        help="Tamaño en ETH (default: 0.001 = mínimo Capital.com).")
    parser.add_argument("--epic", default="ETHUSD", help="Mercado/epic (default: ETHUSD).")
    parser.add_argument("--execute", action="store_true",
                        help="Enviar la orden de verdad. Sin este flag solo hace dry-run.")
    args = parser.parse_args()

    print(f"[INFO] STOP_LOSS flag (env): {STOP_LOSS} | distancia stop: {STOP_LOSS_PCT*100:.0f}%")

    capital_ops = CapitalOP()
    if not capital_ops.authenticate():
        print("[ERROR] ❌ Autenticación fallida. Revisa las credenciales.")
        return 1

    account_id = resolve_account(capital_ops)
    if not account_id:
        return 1
    capital_ops.set_account_id(account_id)

    price = capital_ops.get_last_price(args.epic)
    if not price:
        print(f"[ERROR] ❌ No se pudo obtener el precio de {args.epic}.")
        return 1

    strategy = Strategia(capital_ops)
    sltp = strategy.get_sl_tp_levels(price, {}, args.direction)
    stop_loss = sltp["stop_loss"]

    if stop_loss is None:
        sl_desc = "desactivado"
    else:
        sl_desc = f"{sltp['sl_pct'] * 100:.2f}% de distancia"

    print("\n=== PREFLIGHT ===")
    print(f"  Cuenta:     {account_id}")
    print(f"  Epic:       {args.epic}")
    print(f"  Dirección:  {args.direction}")
    print(f"  Tamaño:     {args.size} ETH")
    print(f"  Precio ~:   {price}")
    print(f"  Stop Loss:  {stop_loss} ({sl_desc})")

    if not args.execute:
        print("\n[DRY-RUN] No se envió ninguna orden. Usa --execute para abrir la posición.")
        return 0

    print("\n=== ENVIANDO ORDEN ===")
    result = capital_ops.open_position(
        market_id=args.epic,
        direction=args.direction,
        size=args.size,
        stop_loss=stop_loss,
    )
    print(f"\nRESULT: {result}")

    if isinstance(result, dict) and result.get("error"):
        print(f"[ERROR] ❌ La orden no se abrió: {result.get('message')}")
        return 1
    print("[INFO] ✅ Posición abierta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
