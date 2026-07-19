"""
PositionValidator - Validador de posiciones para evitar cruces BUY/SELL
Asegura que las posiciones SELL siempre estén por encima de las BUY
"""

class PositionValidator:
    """
    Valida que las nuevas posiciones cumplan la regla:
    - BUY siempre por DEBAJO del precio de las SELL abiertas
    - SELL siempre por ENCIMA del precio de las BUY abiertas
    """

    @staticmethod
    def get_position_price(position):
        """Extrae el precio de entrada de una posición"""
        # 🔹 ESTRUCTURA BACKTEST: entry_price directo
        if "entry_price" in position:
            return float(position.get("entry_price", 0))

        # 🔹 ESTRUCTURA PRODUCCIÓN: position.level anidado
        if "position" in position:
            return float(position.get("position", {}).get("level", 0))

        # 🔹 FALLBACK: buscar otros campos comunes
        for field in ["level", "price", "open_price"]:
            if field in position:
                return float(position.get(field, 0))

        print(f"[WARNING] ⚠️ No se pudo extraer precio de posición: {position}")
        return 0.0

    @staticmethod
    def get_position_prices(positions_dict, direction):
        """
        Obtiene todos los precios de entrada de posiciones en una dirección

        Args:
            positions_dict: Dict con formato {"BUY": [...], "SELL": [...]}
            direction: "BUY" o "SELL"

        Returns:
            List de precios (floats)
        """
        positions = positions_dict.get(direction, [])
        return [PositionValidator.get_position_price(pos) for pos in positions if pos]

    @staticmethod
    def validate_new_position(current_price, action, open_positions, tolerance_pct=0.5, trend_info=None):
        """
        Valida si se puede abrir una nueva posición según la regla de no cruce

        REGLA:
        - Para abrir BUY: el precio actual debe estar DEBAJO de todas las SELL abiertas
        - Para abrir SELL: el precio actual debe estar ENCIMA de todas las BUY abiertas

        Args:
            current_price: Precio actual del mercado
            action: "BUY" o "SELL"
            open_positions: Dict {"BUY": [...], "SELL": [...]}
            tolerance_pct: Tolerancia en % (default 0.5% = permite cierto margen)
            trend_info: Dict opcional con ADX/strength para excepciones de movimiento obvio

        Returns:
            dict: {
                "allowed": bool,
                "reason": str,
                "blocking_positions": list (precios que bloquean)
            }
        """
        action = action.upper()

        if action == "BUY":
            # Para BUY: verificar que no haya SELL POR ENCIMA del precio actual (lógica corregida)
            sell_prices = PositionValidator.get_position_prices(open_positions, "SELL")

            if not sell_prices:
                return {
                    "allowed": True,
                    "reason": "No hay posiciones SELL abiertas",
                    "blocking_positions": []
                }

            # Encontrar SELLs que están POR ENCIMA del precio actual (conflicto real)
            max_sell_price = max(sell_prices)
            tolerance = current_price * (tolerance_pct / 100)

            # BUY permitido si precio actual - tolerancia > max SELL
            # (es decir, todas las SELL están por debajo, sin conflicto)
            if current_price - tolerance > max_sell_price:
                return {
                    "allowed": True,
                    "reason": f"Precio ${current_price:.2f} está por encima de SELL más alta (${max_sell_price:.2f}) - sin conflicto",
                    "blocking_positions": []
                }

            # Hay conflicto potencial (SELL por encima), verificar excepciones
            blocking = [p for p in sell_prices if p >= current_price - tolerance]
            distance_pct = abs(current_price - max_sell_price) / max_sell_price * 100

            # 🎯 EXCEPCIÓN: Permitir si movimiento es OBVIO (>3% distancia + trending fuerte)
            if trend_info:
                adx = trend_info.get('ADX', 0) if isinstance(trend_info, dict) else 0
                strength = trend_info.get('strength', 0) if isinstance(trend_info, dict) else 0

                # Movimiento obvio: >3% distancia + (ADX>30 O strength>1.5)
                if distance_pct > 3.0 and (adx > 30 or strength > 1.5):
                    return {
                        "allowed": True,
                        "reason": f"⚡ MOVIMIENTO OBVIO: BUY permitido a ${current_price:.2f} (+{distance_pct:.1f}% sobre SELL ${max_sell_price:.2f}) | ADX={adx:.1f}",
                        "blocking_positions": []
                    }

            # Sin excepción: bloquear
            return {
                "allowed": False,
                "reason": f"❌ No se puede BUY a ${current_price:.2f}. Hay SELL por encima en ${max_sell_price:.2f} ({distance_pct:.1f}% distancia)",
                "blocking_positions": blocking
            }

        elif action == "SELL":
            # Para SELL: verificar que no haya BUY POR DEBAJO del precio actual (lógica corregida)
            buy_prices = PositionValidator.get_position_prices(open_positions, "BUY")

            if not buy_prices:
                return {
                    "allowed": True,
                    "reason": "No hay posiciones BUY abiertas",
                    "blocking_positions": []
                }

            # Encontrar BUYs que están POR DEBAJO del precio actual (conflicto real)
            min_buy_price = min(buy_prices)
            tolerance = current_price * (tolerance_pct / 100)

            # SELL permitido si precio actual + tolerancia < min BUY
            # (es decir, todas las BUY están por encima, sin conflicto)
            if current_price + tolerance < min_buy_price:
                return {
                    "allowed": True,
                    "reason": f"Precio ${current_price:.2f} está por debajo de BUY más baja (${min_buy_price:.2f}) - sin conflicto",
                    "blocking_positions": []
                }

            # Hay conflicto potencial (BUY por debajo), verificar excepciones
            blocking = [p for p in buy_prices if p <= current_price + tolerance]
            distance_pct = abs(current_price - min_buy_price) / min_buy_price * 100

            # 🎯 EXCEPCIÓN: Permitir si movimiento es OBVIO (>3% distancia + trending fuerte)
            if trend_info:
                adx = trend_info.get('ADX', 0) if isinstance(trend_info, dict) else 0
                strength = trend_info.get('strength', 0) if isinstance(trend_info, dict) else 0

                # Movimiento obvio: >3% distancia + (ADX>30 O strength>1.5)
                if distance_pct > 3.0 and (adx > 30 or strength > 1.5):
                    return {
                        "allowed": True,
                        "reason": f"⚡ MOVIMIENTO OBVIO: SELL permitido a ${current_price:.2f} (-{distance_pct:.1f}% bajo BUY ${min_buy_price:.2f}) | ADX={adx:.1f}",
                        "blocking_positions": []
                    }

            # Sin excepción: bloquear
            return {
                "allowed": False,
                "reason": f"❌ No se puede SELL a ${current_price:.2f}. Hay BUY por debajo en ${min_buy_price:.2f} ({distance_pct:.1f}% distancia)",
                "blocking_positions": blocking
            }

        else:
            return {
                "allowed": False,
                "reason": f"Acción inválida: {action}",
                "blocking_positions": []
            }

    @staticmethod
    def suggest_alternative(current_price, action, open_positions, tolerance_pct=0.5):
        """
        Sugiere una acción alternativa si la original está bloqueada

        Returns:
            dict: {
                "alternative_action": str ("CLOSE_OPPOSITE" o "WAIT"),
                "message": str
            }
        """
        validation = PositionValidator.validate_new_position(
            current_price, action, open_positions, tolerance_pct
        )

        if validation["allowed"]:
            return {
                "alternative_action": "PROCEED",
                "message": "✅ Posición permitida"
            }

        action = action.upper()
        opposite = "BUY" if action == "SELL" else "SELL"
        opposite_positions = open_positions.get(opposite, [])

        if opposite_positions:
            return {
                "alternative_action": "CLOSE_OPPOSITE",
                "message": f"💡 Sugerencia: Cerrar posiciones {opposite} antes de abrir {action} a ${current_price:.2f}",
                "positions_to_close": opposite_positions
            }
        else:
            return {
                "alternative_action": "WAIT",
                "message": f"⏳ Esperar mejor precio para {action}"
            }


# ============ EJEMPLO DE USO ============
if __name__ == "__main__":
    # Simulación de posiciones abiertas
    open_positions = {
        "BUY": [
            {"position": {"level": 3000.0, "size": 0.001}},
            {"position": {"level": 2950.0, "size": 0.002}}
        ],
        "SELL": [
            {"position": {"level": 3200.0, "size": 0.001}}
        ]
    }

    print("=" * 60)
    print("VALIDADOR DE POSICIONES - PRUEBAS")
    print("=" * 60)
    print(f"\nPosiciones abiertas:")
    print(f"  BUY: $3000, $2950")
    print(f"  SELL: $3200")
    print("\n" + "-" * 60)

    # Test 1: BUY válido (debajo de todo)
    current_price = 2900
    result = PositionValidator.validate_new_position(current_price, "BUY", open_positions)
    print(f"\n1️⃣ BUY a ${current_price}:")
    print(f"   {result['reason']}")
    print(f"   Permitido: {'✅ SÍ' if result['allowed'] else '❌ NO'}")

    # Test 2: BUY inválido (cerca/encima de SELL)
    current_price = 3150
    result = PositionValidator.validate_new_position(current_price, "BUY", open_positions)
    print(f"\n2️⃣ BUY a ${current_price}:")
    print(f"   {result['reason']}")
    print(f"   Permitido: {'✅ SÍ' if result['allowed'] else '❌ NO'}")
    if not result['allowed']:
        suggestion = PositionValidator.suggest_alternative(current_price, "BUY", open_positions)
        print(f"   {suggestion['message']}")

    # Test 3: SELL válido (encima de todo)
    current_price = 3300
    result = PositionValidator.validate_new_position(current_price, "SELL", open_positions)
    print(f"\n3️⃣ SELL a ${current_price}:")
    print(f"   {result['reason']}")
    print(f"   Permitido: {'✅ SÍ' if result['allowed'] else '❌ NO'}")

    # Test 4: SELL inválido (debajo/cerca de BUY)
    current_price = 3050
    result = PositionValidator.validate_new_position(current_price, "SELL", open_positions)
    print(f"\n4️⃣ SELL a ${current_price}:")
    print(f"   {result['reason']}")
    print(f"   Permitido: {'✅ SÍ' if result['allowed'] else '❌ NO'}")
    if not result['allowed']:
        suggestion = PositionValidator.suggest_alternative(current_price, "SELL", open_positions)
        print(f"   {suggestion['message']}")

    print("\n" + "=" * 60)
