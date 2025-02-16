class Strategia:
    def __init__(self, threshold_buy=(1,2), threshold_sell=(0, 2, 3), risk_factor=0.01, 
                 margin_protection=0.9, profit_threshold=0.03, stop_loss=0.1, 
                 retracement_threshold=0.01):
        """
        Estrategia de trading mejorada.
        """
        self.threshold_buy = threshold_buy
        self.threshold_sell = threshold_sell
        self.risk_factor = risk_factor
        self.margin_protection = margin_protection
        self.profit_threshold = profit_threshold
        self.stop_loss = stop_loss
        self.retracement_threshold = retracement_threshold
        self.history = []
        self.balance = 10

    def decide(self, state, current_price, balance, features, market_id, previous_state=None, open_positions=None):
        leverage = 20  # Apalancamiento
        margin_percentage = 1  # Usamos el 1% del balance disponible como margen
        max_positions = 1  # Número máximo de posiciones permitidas
        max_deal_size = 0.0003  # Tamaño máximo permitido por el mercado
        min_deal_size = 0.0001  # Tamaño mínimo permitido

        print(f"[DEBUG] Decidiendo con state={state}, previous_state={previous_state}, precio={current_price}")

        if current_price <= 0 or balance <= 0:
            return {"action": "hold", "size": 0, "reason": "Precio o balance inválido"}
        num_open_positions = len(open_positions) if open_positions else 0
        if num_open_positions >= max_positions:

            print(f"[INFO] Límite de posiciones alcanzado ({max_positions}).")
            return {"action": "hold", "size": 0, "reason": "Límite de posiciones abiertas alcanzado"}
        
        # Indicadores
        rsi = features.get("RSI", 0)
        macd = features.get("MACD", 0)
        atr = features.get("ATR", 0)
        volume_change = features.get("VolumeChange", 0)

        def calculate_position_size(balance, leverage, current_price, risk_factor, min_deal_size, max_deal_size, margin_protection=0.9):
            """
            Calcula el tamaño de la posición basado en el riesgo y los límites del mercado.
            
            :param balance: Balance disponible en USD.
            :param leverage: Apalancamiento.
            :param current_price: Precio actual del activo (USD/BTC).
            :param risk_factor: Porcentaje del balance a usar como margen (e.g., 1%).
            :param min_deal_size: Tamaño mínimo permitido por el mercado.
            :param max_deal_size: Tamaño máximo permitido por el mercado.
            :param margin_protection: Factor para proteger margen (e.g., usar solo 90% del margen disponible).
            :return: Tamaño de la posición ajustado en BTC.
            """
            # Calcular el margen permitido considerando el factor de riesgo y protección
            margin_to_use = balance * risk_factor * margin_protection

            # Calcular tamaño de posición en BTC basado en el margen permitido y apalancamiento
            position_size = (margin_to_use * leverage) / current_price

            # Validar y ajustar el tamaño dentro de los límites permitidos por el mercado
            position_size = max(min(position_size, max_deal_size), min_deal_size)

            # Recalcular si el margen requerido es mayor al permitido
            margin_required = (position_size * current_price) / leverage
            if margin_required > margin_to_use:
                position_size = (margin_to_use * leverage) / current_price

            # Redondear a 4 decimales para precisión
            return round(position_size, 4)


        # **Condición 1: Estados favorables consecutivos (1 → 1, 1 → 2, 2 → 1)**
        if state in [1, 2] and previous_state in [1, 2]:
            if volume_change > -0.1:
                size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
                margin_required = (size * abs(current_price)) / leverage  # El tamaño SIEMPRE será el 1% del balance en relación al precion                margin_required = (size * abs(current_price)) / leverage
                if balance >= margin_required:
                    print(f"[INFO] Compra sugerida basada en estados favorables: {size:.6f} unidades a precio {current_price}")
                    return {
                        "action": "buy",
                        "size": size,
                        "market_id": market_id,
                        "margin_required": margin_required,
                        "reason": "Estados favorables consecutivos detectados"
                    }
                else:
                    return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}

        # **Condición 2: Retrocesos desde picos (3 → 2, 3 → 1)**
        if state in [2, 1] and previous_state == 3:
            if rsi > 45 and atr < 0.03 and volume_change > 0.1:
                size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
                margin_required = (size * abs(current_price)) / leverage
                if balance >= margin_required:
                    print(f"[INFO] Compra sugerida en retroceso desde pico: {size:.6f} unidades a precio {current_price}")
                    return {
                        "action": "buy",
                        "size": size,
                        "market_id": market_id,
                        "margin_required": margin_required,
                        "reason": "Retroceso desde pico detectado"
                    }
                else:
                    return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}

        # **Condición 3: Consolidaciones con ATR dinámico (2 → 2)**
        if state == 2 and previous_state == 2:
            atr_threshold = 0.02 if atr < 0.015 else 0.05
            if rsi > 45 and macd > 0 and atr < atr_threshold:
                size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
                margin_required = (size * abs(current_price)) / leverage
                if balance >= margin_required:
                    print(f"[INFO] Compra sugerida en consolidación: {size:.6f} unidades a precio {current_price}")
                    return {
                        "action": "buy",
                        "size": size,
                        "market_id": market_id,
                        "margin_required": margin_required,
                        "reason": "Consolidación detectada con ATR dinámico"
                    }
                else:
                    return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}

        # **Condición 4: Impulsos iniciales (0 → 1)**
        if state == 1 and previous_state == 0:
            if rsi > 50 and volume_change > 0 and macd > -0.1:
                size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
                margin_required = (size * abs(current_price)) / leverage
                if balance >= margin_required:
                    print(f"[INFO] Compra sugerida en impulso inicial: {size:.6f} unidades a precio {current_price}")
                    return {
                        "action": "buy",
                        "size": size,
                        "market_id": market_id,
                        "margin_required": margin_required,
                        "reason": "Impulso inicial detectado"
                    }
                else:
                    return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}

        # **Condición 5: Estados bajistas con indicadores positivos (0 → 2)**
        if state == 2 and previous_state == 0:
            if rsi > 55 and macd > 0 and volume_change > 0:
                size = calculate_position_size(balance, leverage, current_price, margin_percentage, min_deal_size, max_deal_size)
                margin_required = (size * abs(current_price)) / leverage
                if balance >= margin_required:
                    print(f"[INFO] Compra sugerida en transición bajista positiva: {size:.6f} unidades a precio {current_price}")
                    return {
                        "action": "buy",
                        "size": size,
                        "market_id": market_id,
                        "margin_required": margin_required,
                        "reason": "Transición bajista positiva detectada"
                    }
                else:
                    return {"action": "hold", "size": 0, "reason": "Saldo insuficiente para abrir la posición"}

        # **Default: Mantener posición**
        return {"action": "hold", "size": 0, "reason": "No se cumplieron condiciones para abrir posición"}

    def evaluate_positions(self, positions, current_price, state, features, previous_state=None):
        """
        Evalúa posiciones abiertas para decidir si cerrarlas.
        Nunca cierra posiciones en negativo, incluye Emergency Exit.
        Retorna una lista de acciones a tomar.
        """
        to_close = []

        for position in positions:
            deal_id = position.get("dealId")
            direction = position.get("direction")
            entry_price = position.get("price")
            size = position.get("size")
            upl = position.get("upl", 0)  # Usar el UPL directamente

            # Verificar que todos los datos esenciales estén presentes
            if not deal_id or not direction or not entry_price or not size:
                print(f"[WARNING] Posición incompleta. dealId: {deal_id}, direction: {direction}, price: {entry_price}. Manteniendo posición.")
                continue

            # Usar upl como current_profit
            current_profit = upl

            # Nunca cerrar posiciones con ganancia negativa
            if current_profit <= 0:
                print(f"[DEBUG] Manteniendo posición debido a ganancia negativa. Profit: {current_profit * 100:.2f}%")
                continue

            # Obtener el max_profit previo desde el tracker
            max_profit_prev = position.get("max_profit", 0)

            # Actualizar el máximo alcanzado solo si current_profit es positivo
            if current_profit > 0:
                updated_max_profit = max(max_profit_prev, current_profit)
                position["max_profit"] = updated_max_profit
                print(f"[INFO] Max Profit actualizado: {updated_max_profit * 100:.2f}%")
            else:
                print(f"[DEBUG] Current Profit es negativo o cero ({current_profit * 100:.2f}%). No se actualiza Max Profit.")


            # Emergency Exit: Detectar pequeñas ganancias positivas
            if 0 < current_profit <= 0.01:  # Ganancia entre 0% y 1%
                rsi = features.get("RSI", 0)
                macd = features.get("MACD", 0)
                volume_change = features.get("VolumeChange", 0)

                if state in [0, 1] and (rsi < 50 or macd < 0 or volume_change <= 0):
                    print(f"[INFO] Emergency Exit: Cierre por pequeña ganancia: {current_profit * 100:.2f}%")
                    to_close.append({
                        "action": "sell",
                        "dealId": deal_id,
                        "size": size,
                        "reason": "emergency_exit"
                    })
                    continue

            # Regla para transiciones 0 → 3
            if current_profit > 0:
                if previous_state == 0 and state == 3:
                    print(f"[INFO] Cierre inmediato por transición 0 → 3 con ganancia: {current_profit * 100:.2f}%")
                    to_close.append({
                        "action": "sell",
                        "dealId": deal_id,
                        "size": size,
                        "reason": "state_0_to_3"
                    })
                    continue

            # Regla para estados consecutivos 3 → 3
            if current_profit > 0:
                if previous_state == 3 and state == 3:
                    print(f"[INFO] Cierre inmediato por estado consecutivo 3 → 3 con ganancia: {current_profit * 100:.2f}%")
                    to_close.append({
                        "action": "sell",
                        "dealId": deal_id,
                        "size": size,
                        "reason": "state_3_consecutive"
                    })
                    continue

            # Retroceso basado en el máximo alcanzado
            retracement_allowed = updated_max_profit * self.retracement_threshold
            if updated_max_profit > 0 and (updated_max_profit - current_profit) > retracement_allowed:
                # Verificar que current_profit es positivo antes de proceder
                if current_profit <= 0.01:
                    print(f"[DEBUG] Manteniendo posición por ganancia negativa durante evaluación de retroceso. Profit: {current_profit * 100:.2f}%")
                    continue

                # Condiciones adicionales para evitar cierre si indicadores son positivos
                rsi = features.get("RSI", 0)
                macd = features.get("MACD", 0)
                volume_change = features.get("VolumeChange", 0)
                if rsi > 50 and macd > 0 and volume_change > 0:
                    print(f"[INFO] Sosteniendo posición: Indicadores positivos detectados.")
                    continue

                # Cierre si todas las condiciones están cumplidas
                print(f"[INFO] Cierre por retroceso positivo detectado: {current_profit * 100:.2f}%")
                to_close.append({
                    "action": "sell",
                    "dealId": deal_id,
                    "size": size,
                    "reason": "retracement_positive"
                })

            # Cierre por ganancia alcanzada
            if current_profit >= self.profit_threshold:
                print(f"[INFO] Cierre por ganancia alcanzada: {current_profit * 100:.2f}%")
                to_close.append({
                    "action": "sell",
                    "dealId": deal_id,
                    "size": size,
                    "reason": "profit_threshold"
                })

            if current_profit > 0:
                # Cierre por estados decrecientes (solo si current_profit > 0)
                if (previous_state, state) in [(3, 2), (2, 0), (3, 0)]:
                    print(f"[INFO] Cierre por cambio de estados con ganancia: {previous_state} → {state}")
                    to_close.append({
                        "action": "sell",
                        "dealId": deal_id,
                        "size": size,
                        "reason": "state_decrease_positive"
                    })

        return to_close



    def get_history(self):
        """
        Devuelve el historial de decisiones tomadas.
        """
        return self.history
