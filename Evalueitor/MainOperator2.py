import pickle
import time
import pandas as pd
import os
import json
from CapitalOperations import CapitalOP
from Strategy import Strategia
from PyQt5.QtCore import QObject, pyqtSignal


# Lógica para decisiones
class TradingOperator(QObject):

    positions_updated = pyqtSignal(list)  # Señal para emitir las posiciones actualizadas

    def __init__(self, model, features, strategy,saldo_update_callback,scaler_stats):
        super().__init__()

        self.model = model
        self.features = features
        self.strategy = strategy  # La estrategia se pasa como argumento
        self.log_open_positions = []
        self.log_process_data = []
        self.previous_state = None  # Inicializa el estado previo como None
        self.scaler_mean = scaler_stats["mean"]
        self.scaler_scale = scaler_stats["scale"]
        self.capital_ops = CapitalOP()  # Ensure authenticated here if required
        self.account_id = "253360361314791710"  # Example value
        self.positions = []  # Placeholder for positions
        self.saldo_update_callback = saldo_update_callback  # Callback para actualizar el saldo
        self.last_processed_index = -1  # Mantiene el índice de la última fila procesada
        self.balance = 0  # Inicializa el saldo
        self.position_tracker = {}
        

    def run_main_loop(self, data_frame, interval=10):
        """
        Procesa la última fila del DataFrame si es nueva,
        evalúa nuevas decisiones y revisa posiciones abiertas, cada `interval` segundos.
        """
        print("[INFO] Iniciando bucle principal de TradingOperator.")
        try:
            while True:  # Bucle infinito para procesar datos periódicamente
                if data_frame.empty:
                    print("[WARNING] El DataFrame está vacío. No hay datos para procesar.")
                    time.sleep(interval)
                    continue

                # Obtener la última fila del DataFrame
                latest_row = self.get_latest_data(data_frame)

                # Verificar si la fila es nueva comparando índices
                if self.last_processed_index < latest_row.name:
                    print(f"[INFO] Procesando nueva fila del DataFrame: {latest_row.name}")

                    # Actualizar saldo y posiciones
                    try:
                        balance, positions = self.update_balance_and_positions()
                    except Exception as e:
                        print(f"[ERROR] Error al actualizar saldo y posiciones: {e}")
                        time.sleep(interval)
                        continue

                    # Procesar datos de la última fila (nuevas decisiones)
                    try:
                        self.process_data(row=latest_row, positions=positions, balance=balance)
                    except Exception as e:
                        print(f"[ERROR] Error al procesar datos: {e}")

                    # Evaluar posiciones abiertas después de procesar datos
                    try:
                        current_price = latest_row["Close"]
                        features = latest_row.to_dict()  # Convertir la fila a un diccionario para obtener características
                        self.process_open_positions(
                            account_id=self.account_id,
                            capital_ops=self.capital_ops,
                            current_price=current_price,
                            features=features,
                            state=self.previous_state,
                            previous_state=None  # Aquí puedes usar self.previous_state si es aplicable
                        )
                    except Exception as e:
                        print(f"[ERROR] Error al evaluar posiciones abiertas: {e}")

                    # Actualizar el índice de la última fila procesada
                    self.last_processed_index = latest_row.name

                    # Imprimir el log acumulado
                    self.print_log()
                else:
                    print("[INFO] No hay nuevas filas para procesar.")

                # Esperar el intervalo antes de la próxima iteración
                time.sleep(interval)

        except Exception as e:
            print(f"[ERROR] Error en el bucle principal: {e}")


    def descale_value(self, feature_name, value):
        """
        Desescala un valor utilizando las estadísticas del escalador.
        :param feature_name: Nombre de la característica.
        :param value: Valor escalado.
        :return: Valor desescalado.
        """
        if feature_name not in self.features:
            raise ValueError(f"[ERROR] La característica {feature_name} no está en el modelo.")
        index = self.features.index(feature_name)
        mean = self.scaler_mean[index]
        scale = self.scaler_scale[index]
        return (value * scale) + mean



    def update_balance_and_positions(self):
        """Actualiza el saldo y las posiciones desde Capital.com."""
        try:
            # Solicitar el resumen de la cuenta
            print("[DEBUG] Solicitando resumen de la cuenta...")
            account_info = self.capital_ops.get_account_summary()
            print(f"[DEBUG] Información de la cuenta obtenida: {account_info}")

            # Validar que 'accounts' esté presente y no esté vacío
            accounts = account_info.get("accounts", [])
            if not accounts:
                print("[ERROR] No se encontraron cuentas en la respuesta.")
                return 0, []

            # Acceder al primer elemento de 'accounts' y extraer el saldo
            account_data = accounts[0]
            balance_info = account_data.get("balance", {})  # Aquí definimos balance_info correctamente
            available_balance = balance_info.get("available", 0)
            currency_iso_code = account_data.get("currency", "USD")
            print(f"[DEBUG] Saldo disponible: {available_balance}, Moneda: {currency_iso_code}")

            # Actualizar el saldo en el atributo interno
            self.balance = available_balance

            # Ejecutar el callback para actualizar el saldo en la interfaz (si aplica)
            if self.saldo_update_callback:
                print("[DEBUG] Ejecutando callback para actualizar el saldo en la interfaz...")
                self.saldo_update_callback(available_balance, currency_iso_code)

            # Solicitar posiciones abiertas
            print("[DEBUG] Solicitando posiciones abiertas...")
            positions = self.capital_ops.get_open_positions(self.account_id).get("positions", [])
            print(f"[DEBUG] Posiciones abiertas obtenidas: {positions}")

            # Retornar el saldo y las posiciones
            return available_balance, positions

        except Exception as e:
            # Manejo de excepciones con registro del error
            print(f"[ERROR] Error al actualizar saldo y posiciones: {e}")
            return 0, []



    def get_latest_data(self, data_frame):
        """
        Devuelve la última fila de un DataFrame ya cargado.
        
        :param data_frame: DataFrame con los datos cargados.
        :return: Última fila como un objeto pandas.Series.
        """
        if data_frame.empty:
            raise ValueError("[ERROR] Los datos están vacíos.")
        
        print(f"[INFO] Última fila cargada:")
        print(data_frame.iloc[-1].to_dict())  # Opcional: Imprimir la última fila para depuración
        return data_frame.iloc[-1]  # Retorna la última fila como un objeto pandas.Series

    def serialize_positions(positions):
        """
        Serializa las posiciones para ser usadas en la tabla.
        """
        serialized = []
        for position in positions:
            # Aquí accedemos directamente al campo "position" como está en la respuesta
            position_data = position.get("position", {})
            market = position.get("market", {})

            # Validar que las claves críticas existan en `position_data`
            required_keys = ["level", "direction", "size"]
            missing_keys = [key for key in required_keys if key not in position_data or position_data[key] is None]

            if missing_keys:
                print(f"[ERROR] Posición incompleta. Faltan claves: {missing_keys}. Datos: {position_data}")
                continue

            # Serializar los datos
            serialized.append({
                "instrument": market.get("instrumentName", "N/A"),
                "type": market.get("instrumentType", "N/A"),
                "direction": position_data["direction"],  # Clave obligatoria
                "size": position_data["size"],            # Clave obligatoria
                "level": position_data["level"],          # Clave obligatoria
                "upl": position_data.get("upl", 0),
                "currency": position_data.get("currency", "N/A"),
                "take_profit": position_data.get("profitLevel", None),  # Nuevo campo opcional
                "dealId": position_data.get("dealId", None)             # Clave opcional
            })
        return serialized

    def obtener_posiciones(self, account_id, capital_ops):
        raw_positions = capital_ops.get_open_positions(account_id)
        positions = raw_positions.get("positions", [])
        serialized_positions = TradingOperator.serialize_positions(positions)
        
        # Emitir la señal con las posiciones serializadas
        self.positions_updated.emit(serialized_positions)

    def save_position_tracker(self, filepath='position_tracker.json'):
        """
        Guarda el diccionario position_tracker en un archivo JSON.
        """
        try:
            with open(filepath, 'w') as file:
                json.dump(self.position_tracker, file, indent=4)
            print("[INFO] position_tracker guardado exitosamente.")
        except Exception as e:
            print(f"[ERROR] Error al guardar position_tracker: {e}")

    def load_position_tracker(self, filepath='position_tracker.json'):
        """
        Carga el diccionario position_tracker desde un archivo JSON.
        """
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as file:
                    self.position_tracker = json.load(file)
                print("[INFO] position_tracker cargado exitosamente.")
            except Exception as e:
                print(f"[ERROR] Error al cargar position_tracker: {e}")
                self.position_tracker = {}
        else:
            print("[INFO] No se encontró el archivo position_tracker.json. Inicializando diccionario vacío.")
            self.position_tracker = {}


    def format_datetime(self, timestamp):
        """Convierte un UNIX timestamp a un formato legible."""
        return pd.to_datetime(timestamp, unit='ms').strftime('%Y-%m-%d %H:%M:%S')



    def process_open_positions(self, account_id, capital_ops, current_price, features, state, previous_state):
        """
        Procesa y evalúa las posiciones abiertas con valores desescalados,
        aplicando la estrategia y cerrando posiciones según sea necesario.
        """
        try:
            # 1) Obtener las posiciones actuales desde el broker
            raw_positions = capital_ops.get_open_positions(account_id)
            positions = raw_positions.get("positions", [])

            if not isinstance(positions, list):
                print("[ERROR] Las posiciones no están en el formato esperado.")
                return

            print(f"[INFO] Procesando {len(positions)} posiciones abiertas.")

            # 2) Construir 'formatted_positions' con datos reales del broker
            formatted_positions = []
            for position in positions:
                position_data = position.get("position", {})
                market_data   = position.get("market", {})

                # Verificar que tengamos level, direction y size
                missing_keys = [
                    key for key in ("level", "direction", "size")
                    if key not in position_data or position_data[key] is None
                ]
                if missing_keys:
                    print(f"[ERROR] Posición incompleta. Faltan claves: {missing_keys}. Datos: {position_data}")
                    continue

                # Recuperar dealId (o asignar uno temporal si no existe)
                deal_id = position_data.get("dealId") or f"temp_{id(position)}"

                # Obtener el max_profit previo desde el tracker
                old_info = self.position_tracker.get(deal_id, {})
                prev_max_profit = old_info.get("max_profit", 0)

                # Construir la posición formateada con datos reales
                fpos = {
                    "price":      position_data["level"],    # Precio real del broker
                    "direction":  position_data["direction"],
                    "size":       position_data["size"],
                    "upl":        position_data.get("upl", 0),
                    "instrument": market_data.get("instrumentName", "N/A"),
                    "dealId":     deal_id,
                    "max_profit": prev_max_profit
                }
                formatted_positions.append(fpos)
                print(f"[DEBUG] Posición formateada: {fpos}")

            # 3) Desescalar valores para la estrategia
            #    (Solo si 'current_price' y/o 'features' vienen escalados)
            unscaled_current_price = self.descale_value("Close", current_price)

            unscaled_features = {}
            for feat_name, feat_val in features.items():
                if feat_name in self.features:  # Solo desescalar si lo habías escalado
                    unscaled_features[feat_name] = self.descale_value(feat_name, feat_val)
                else:
                    # RSI, MACD, etc. no estaban escalados en muchos casos
                    unscaled_features[feat_name] = feat_val

            # 4) Llamar a la estrategia con valores REALES
            to_close = self.strategy.evaluate_positions(
                positions       = formatted_positions,
                current_price   = unscaled_current_price,
                state           = state,
                features        = unscaled_features,
                previous_state  = previous_state
            )

            # 5) Cerrar posiciones si la estrategia lo indica
            if to_close:
                for action in to_close:
                    if action["action"] == "sell":
                        deal_id = action.get("dealId")
                        if deal_id:
                            capital_ops.close_position(deal_id)
                            print(f"[INFO] Cerrando posición con dealId={deal_id}")
                            # Remover de position_tracker si se cierra
                            if deal_id in self.position_tracker:
                                del self.position_tracker[deal_id]
                        else:
                            print("[ERROR] No se proporcionó dealId para la posición a cerrar.")

            # 6) Actualizar max_profit basado en las posiciones restantes
            for fpos in formatted_positions:
                d_id = fpos["dealId"]
                direction = fpos["direction"].upper()
                entry_price = fpos["price"]
                size = fpos["size"]

                # Calcular profit_loss basado en la dirección de la posición
                if direction == "BUY":
                    current_profit = (unscaled_current_price - entry_price) / entry_price
                elif direction == "SELL":
                    current_profit = (entry_price - unscaled_current_price) / entry_price
                else:
                    print(f"[WARNING] Dirección desconocida: {direction}. No se actualiza max_profit.")
                    continue

                # Actualizar max_profit en position_tracker
                if d_id in self.position_tracker:
                    previous_max = self.position_tracker[d_id]["max_profit"]
                    self.position_tracker[d_id]["max_profit"] = max(previous_max, current_profit)
                    print(f"[DEBUG] Actualizado max_profit para dealId={d_id}: {self.position_tracker[d_id]['max_profit']:.4f}")
                else:
                    self.position_tracker[d_id] = {"max_profit": current_profit}
                    print(f"[DEBUG] Inicializado max_profit para dealId={d_id}: {current_profit:.4f}")

                # Actualizar la posición formateada con el nuevo max_profit
                fpos["max_profit"] = self.position_tracker[d_id]["max_profit"]

            relevant_features = {key: features[key] for key in ['Close', 'RSI', 'ATR', 'VolumeChange'] if key in features}

            # 7) Crear y registrar log entry
            log_entry = {
                "datetime":       pd.Timestamp.now(),
                "current_price":  unscaled_current_price,
                "state":          state,
                "previous_state": previous_state,
                "positions":      formatted_positions,
                "actions_taken":  to_close,
                "features":       relevant_features ,
            }
            self.log_open_positions.append(log_entry)

            print(f"[DEBUG] Entrada añadida al log desde process_open_positions: {log_entry}")
            print(f"[INFO] Evaluación completada. Acciones registradas: {to_close}")

            # 8) Guardar el position_tracker después de actualizarlo
            self.save_position_tracker()

        except Exception as e:
            print(f"[ERROR] Fallo durante el procesamiento de posiciones: {e}")

    def process_data(self, row, positions, balance):
        """
        Procesa los datos actuales usando la estrategia y valida las posiciones.
        """
        try:

                # Validar precisión antes de la predicción
            input_features = [list(row[self.features])]
            print(f"[DEBUG] Valores para predicción: {input_features}")
            current_state = self.model.predict(input_features)[0]


            # Validar y formatear posiciones
            formatted_positions = []
            for pos in positions:
                try:
                    position_data = pos["position"]
                    market_data = pos["market"]
                    formatted_positions.append({
                        "price": position_data["level"],
                        "direction": position_data["direction"],
                        "size": position_data["size"],
                        "upl": position_data.get("upl", 0),
                        "instrument": market_data.get("instrumentName", "N/A")
                    })
                except KeyError as e:
                    print(f"[ERROR] Datos de posición incompletos: {e}, posición: {pos}")
                    continue

            # Desescalar valores y preparar contexto para la estrategia
            descaled_values = {feature: self.descale_value(feature, row[feature]) for feature in self.features}
            descaled_values["Datetime"] = self.format_datetime(row["Datetime"])
            descaled_values["Close"] = self.descale_value("Close", row["Close"])  # Desescalar 'Close' correctamente

            # Mantener un estado previo
            current_state = self.model.predict([list(row[self.features])])[0]
            previous_state = getattr(self, "previous_state", None)
            self.previous_state = current_state
            print(f"[DEBUG] Valores desescalados: {descaled_values}")
            print(f"[DEBUG] Valores escalados: {row[self.features].to_dict()}")
            # Tomar decisiones para nuevas posiciones
            decision = self.strategy.decide(
                state=current_state,
                current_price=row["Close"],
                balance=self.balance,
                features={
                    "RSI": row.get("RSI", 0),
                    "MACD": row.get("MACD", 0),
                    "ATR": row.get("ATR", 0),
                    "VolumeChange": row.get("VolumeChange", 0)},

                previous_state=previous_state,
                market_id="BTCUSD",
                open_positions=formatted_positions  # Pasar las posiciones abiertas aquí


            )

            # Ejecutar nueva acción si es necesario
            if decision["action"] == "buy":
                self.capital_ops.open_position(
                    market_id=decision["market_id"],
                    direction=decision["action"].upper(),  # Convierte 'buy' a 'BUY'
                    size=decision["size"],
                    stop_loss=decision.get("stop_loss"),
                    take_profit=decision.get("take_profit")
                )

            # Registrar en el log
            log_entry = {
                "datetime": str(descaled_values["Datetime"]),  # Asegurarse de que sea una cadena
                "current_price": float(row["Close"]),          # Convertir a float
                "balance": float(self.balance),                # Convertir a float
                "decision": decision,                          # Diccionario serializable
                "descaled_values": descaled_values,            # Valores ya desescalados
                "state": int(current_state),                   # Asegurar que sea un int estándar
                "previous_state": int(previous_state) if previous_state is not None else None
            }

            self.log_process_data.append(log_entry)

            print(f"[INFO] Log actualizado Desde Process Data (Decide): {json.dumps(log_entry, ensure_ascii=False, indent=4)}")

        except Exception as e:
            print(f"[ERROR] Error en process_data: {e}")



    def print_log(self):
        """Imprime el log detallado de las operaciones, formateado por origen."""
        print("[INFO] Registro de operaciones detallado:")
        
        if not self.log_open_positions and not self.log_process_data:  # Verificar si ambos logs están vacíos
            print("[INFO] Los logs están vacíos. No hay datos para imprimir.")
            return

        # Formatear y mostrar las entradas de `process_open_positions`
        if self.log_open_positions:
            print("[INFO] Registro desde process_open_positions:")
            for entry in self.log_open_positions:
                print("=" * 40)
                print("[ORIGEN] process_open_positions")
                print(f"Fecha: {entry['datetime']}")
                print(f"Precio actual: {entry['current_price']:.2f}")
                print(f"Estado predicho por el modelo: {entry['state']}")
                print(f"Estado previo: {entry['previous_state']}")
                print(f"Posiciones evaluadas:")
                for pos in entry.get("positions", []):
                    print(f"  - Dirección: {pos.get('direction', 'N/A')}")
                    print(f"    Tamaño: {pos.get('size', 'N/A')}")
                    print(f"    Precio de apertura: {pos.get('price', 'N/A')}")
                    print(f"    Ganancia/Pérdida: {pos.get('upl', 'N/A')}")
                print(f"Acciones tomadas: {entry['actions_taken']}")
                print(f"Características usadas: {entry['features']}")
                print("=" * 40)

        # Formatear y mostrar las entradas de `process_data`
        if self.log_process_data:
            print("[INFO] Registro desde process_data:")
            for entry in self.log_process_data:
                print("=" * 40)
                print("[ORIGEN] process_data")
                print(f"Fecha: {entry['datetime']}")
                print(f"Precio actual Escalado: {entry['current_price']:.2f}")
                print(f"Estado predicho por el modelo: {entry['state']}")  # Mostrar estado actual
                print(f"Estado previo: {entry['previous_state']}")  # Mostrar estado previo
                print(f"Balance disponible: {entry['balance']:.2f}")
                print(f"Posiciones abiertas:")
                for pos in entry.get("positions", []):
                    print(f"  - Dirección: {pos.get('direction', 'N/A')}")
                    print(f"    Tamaño: {pos.get('size', 'N/A')}")
                    print(f"    Precio de apertura: {pos.get('price', 'N/A')}")
                    print(f"    Ganancia/Pérdida: {pos.get('upl', 'N/A')}")

                print(f"Decisión tomada: {entry['decision']}")
                print(f"Valores desescalados:")
                for key, value in entry["descaled_values"].items():
                    if key != "Datetime":  # Omitir duplicados de fecha
                        print(f"  {key}: {value}")
                print("=" * 40)

        # Limpiar ambos logs después de imprimir
        self.log_open_positions = []
        self.log_process_data = []


if __name__ == "__main__":

    from PyQt5.QtWidgets import QApplication
    import sys

    try:
        # Inicializar el operador de trading
        print("[INFO] Inicializando operador de trading...")
        
        # Cargar modelo, características, estrategia y datos
        MODEL_FILE = "BTCMD1.pkl"
        DATA_FILE = "/home/hobeat/MoneyMakers/Reports/BTC_USD_IndicadoresCondensados.json"

        with open(MODEL_FILE, 'rb') as file:
            model_data = pickle.load(file)
        
        model = model_data.get('model')
        features = model_data.get('features', [])
        scaler_stats = model_data.get("scaler_stats", {})

        with open(DATA_FILE, 'r') as file:
            raw_data = json.load(file)

        # Crear DataFrame desde el JSON cargado
        data_frame = pd.DataFrame(raw_data.get('data', []))

        # Configurar estrategia
        strategy = Strategia(threshold_buy=0, threshold_sell=2)

        # Crear instancia de TradingOperator
        trading_operator = TradingOperator(
            model=model,
            features=features,
            strategy=strategy,
            saldo_update_callback=None,
            scaler_stats=scaler_stats
        )

        # Iniciar la aplicación PyQt5
        print("[INFO] Inicializando la aplicación PyQt5...")
        app = QApplication(sys.argv)

        # Ejecutar el bucle principal directamente
        trading_operator.run_main_loop(data_frame)

        # Ejecutar la aplicación (opcional, si necesitas una interfaz gráfica)
        sys.exit(app.exec_())

    except Exception as e:
        print(f"[ERROR] Error durante la ejecución principal: {e}")
