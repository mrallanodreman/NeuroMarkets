import pickle
import time
import pandas as pd
import os
import json
from EthSession import CapitalOP
from EthStrategy import Strategia
from PyQt5.QtCore import QObject, pyqtSignal
import threading
from threading import Lock  # Importa Lock para manejo de hilos
import ta


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
        self.account_id = "260136346534097182"  # TU cuenta Id
        self.capital_ops.set_account_id(self.account_id)  # Configurar el ID de cuenta en CapitalOP

        self.positions = []  # Placeholder for positions
        self.saldo_update_callback = saldo_update_callback  # Callback para actualizar el saldo
        self.last_processed_index = -1  # Mantiene el índice de la última fila procesada
        self.balance = 0  # Inicializa el saldo
        self.position_tracker = {}
        self.data_lock = Lock()  # Este candado protegerá los datos compartidos
        self.historical_data = None

        

    def update_historical_data(self):
        """
        Descarga y procesa datos históricos usando las funciones de DataEth.py.
        """
        try:

            # Importar las funciones necesarias de DataEth
            from DataEth import process_data, calculate_indicators, prepare_for_export
            import yfinance as yf

            # Descargar datos desde Yahoo Finance
            ticker = "ETH-USD"
            interval = "1h"
            period = "2y"
            data = yf.download(ticker, interval=interval, period=period)

            if data.empty:
                print("[ERROR] No se obtuvieron datos históricos.")
                return

            # Procesar los datos usando las funciones de DataEth
            data = process_data(data, ticker)
            data = calculate_indicators(data)
            data = prepare_for_export(data)

            # Exportar los datos procesados a un archivo JSON
            output_file = f'/home/hobeat/MoneyMakers/Reports/{ticker.replace("-", "_")}_historical_data.json'
            with open(output_file, 'w') as f:
                json.dump({"data": data.to_dict(orient="records")}, f, indent=4)

            print(f"[INFO] Archivo generado exitosamente: {output_file}")
            self.historical_data = data


        except Exception as e:
            print(f"[ERROR] Error al actualizar datos históricos: {e}")

    def run_main_loop(self, data_frame, interval=25):
        print("[INFO] Iniciando bucle principal de TradingOperator.")
        try:
            while True:  # Bucle infinito para procesar datos periódicamente
                try:
                    print("[INFO] Iniciando actualización de datos históricos...")
                    self.update_historical_data()
                    if self.historical_data is not None:
                       data_frame = self.historical_data

                    print("[INFO] Actualización de datos históricos completada.")
                except Exception as e:
                    print(f"[ERROR] Error al actualizar datos históricos: {e}")
                    time.sleep(interval)
                    continue

                if data_frame.empty:
                    print("[WARNING] El DataFrame está vacío. No hay datos para procesar.")
                    time.sleep(interval)
                    continue

                latest_row = self.get_latest_data(data_frame)

                print(f"[INFO] Procesando fila del DataFrame: {latest_row.name}")

                try:
                    balance, positions = self.update_balance_and_positions()
                except Exception as e:
                    print(f"[ERROR] Error al actualizar saldo y posiciones: {e}")
                    time.sleep(interval)
                    continue

                # Obtener el estado usando el modelo
                try:
                    input_features = [list(latest_row[self.features])]
                    state = self.model.predict(input_features)[0]
                    print(f"[DEBUG] Estado calculado: {state}")
                except Exception as e:
                    print(f"[ERROR] Error al predecir el estado: {e}")
                    state = None  # Manejo alternativo si ocurre un error
                    continue

                # Pasar el estado calculado a process_data
                try:
                    self.process_data(row=latest_row, positions=positions, balance=balance, state=state)
                except Exception as e:
                    print(f"[ERROR] Error al procesar datos: {e}")

                try:
                    current_price = latest_row["Close"]
                    features = latest_row.to_dict()
                    self.process_open_positions(
                        account_id=self.account_id,
                        capital_ops=self.capital_ops,
                        current_price=current_price,
                        features=features,
                        state=state,
                        previous_state=self.previous_state
                    )
                except Exception as e:
                    print(f"[ERROR] Error al evaluar posiciones abiertas: {e}")

                print("[INFO] Fila procesada exitosamente.")

                self.print_log()

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
        try:
            if feature_name not in self.features:
                raise ValueError(f"[ERROR] La característica {feature_name} no está en el modelo.")
            index = self.features.index(feature_name)
            mean = self.scaler_mean[index]
            scale = self.scaler_scale[index]

            descaled_value = (value * scale) + mean
            print(f"[DEBUG] Desescalando {feature_name}: Escalado={value}, Desescalado={descaled_value}, Mean={mean}, Scale={scale}")
            return descaled_value

        except Exception as e:
            print(f"[ERROR] Error al desescalar {feature_name}: {e}")
            return value  # Retornar el valor original en caso de error

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
            positions = self.capital_ops.get_open_positions()  # `get_open_positions` ya devuelve una lista
            if not isinstance(positions, list):
                print("[ERROR] Las posiciones no están en el formato esperado.")
                return available_balance, []
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
        serialized = []
        for position in positions:
            position_data = position.get("position", {})
            market_data = position.get("market", {})

            if not position_data or "direction" not in position_data or "size" not in position_data:
                print(f"[ERROR] Posición con datos incompletos: {json.dumps(position, indent=4)}")
                continue  # Omitir posiciones con datos faltantes

            serialized.append({
                "instrument": market_data.get("instrumentName", "N/A"),
                "type": market_data.get("instrumentType", "N/A"),
                "direction": position_data.get("direction", "UNKNOWN"),
                "size": position_data.get("size", 0),
                "level": position_data.get("level", 0),
                "upl": position_data.get("upl", 0),
                "currency": position_data.get("currency", "N/A"),
                "take_profit": position_data.get("profitLevel", None),
                "dealId": position_data.get("dealId", None)
            })
        return serialized


    def obtener_posiciones(self, account_id, capital_ops):
        raw_positions = capital_ops.get_open_positions()
        positions = raw_positions  # `raw_positions` ya es una lista
        if not isinstance(positions, list):
            print("[ERROR] Las posiciones no están en el formato esperado.")
            return

        
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
            previous_state = self.previous_state
            print(f"[DEBUG] Estado previo antes de procesar: {previous_state}")

            # 🔹 1) Obtener las posiciones abiertas correctamente
            buy_positions, sell_positions = capital_ops.get_open_positions()
            positions = buy_positions + sell_positions  # ✅ Combinar ambas listas

            print(f"[INFO] Procesando {len(positions)} posiciones abiertas.")

            # 🔹 2) Construir 'formatted_positions' con datos reales
            formatted_positions = []
            for position in positions:
                position_data = position.get("position", {})
                market_data = position.get("market", {})

                # Validar datos requeridos
                required_keys = ["level", "direction", "size"]
                if any(key not in position_data or position_data[key] is None for key in required_keys):
                    print(f"[ERROR] Posición incompleta: {position_data}")
                    continue

                deal_id = position_data.get("dealId") or f"temp_{id(position)}"

                # Obtener max_profit previo
                prev_max_profit = self.position_tracker.get(deal_id, {}).get("max_profit", 0)

                fpos = {
                    "price": position_data["level"],
                    "direction": position_data["direction"],
                    "size": position_data["size"],
                    "upl": position_data.get("upl", 0),
                    "instrument": market_data.get("instrumentName", "N/A"),
                    "dealId": deal_id,
                    "max_profit": prev_max_profit,
                }
                formatted_positions.append(fpos)
                print(f"[DEBUG] Posición formateada: {fpos}")

            # 🔹 3) Desescalar valores
            unscaled_current_price = self.descale_value("Close", current_price)
            unscaled_features = {feat: self.descale_value(feat, val) if feat in self.features else val for feat, val in features.items()}

            # 🔹 4) Evaluar con la estrategia
            to_close = self.strategy.evaluate_positions(
                positions=formatted_positions,
                current_price=unscaled_current_price,
                state=state,
                features=unscaled_features,
                previous_state=previous_state
            )

            # 🔹 5) Cerrar posiciones si la estrategia lo indica
            for action in to_close:
                if action["action"] == "sell":
                    deal_id = action.get("dealId")
                    if deal_id:
                        capital_ops.close_position(deal_id)
                        print(f"[INFO] Cerrando posición con dealId={deal_id}")
                        self.position_tracker.pop(deal_id, None)  # ✅ Eliminar del tracker si se cierra
                    else:
                        print("[ERROR] No se proporcionó dealId para la posición a cerrar.")

            # 🔹 6) Actualizar max_profit
            for fpos in formatted_positions:
                d_id = fpos["dealId"]
                direction = fpos["direction"].upper()
                entry_price = fpos["price"]
                
                if direction == "BUY":
                    current_profit = (unscaled_current_price - entry_price) / entry_price
                elif direction == "SELL":
                    current_profit = (entry_price - unscaled_current_price) / entry_price
                else:
                    print(f"[WARNING] Dirección desconocida: {direction}. No se actualiza max_profit.")
                    continue

                self.position_tracker[d_id] = {"max_profit": max(self.position_tracker.get(d_id, {}).get("max_profit", 0), current_profit)}
                fpos["max_profit"] = self.position_tracker[d_id]["max_profit"]

            # 🔹 7) Crear y registrar log
            log_entry = {
                "datetime": pd.Timestamp.now(),
                "current_price": unscaled_current_price,
                "state": state,
                "previous_state": previous_state,
                "positions": formatted_positions,
                "actions_taken": to_close,
                "features": {key: features[key] for key in ["Close", "RSI", "ATR", "VolumeChange"] if key in features},
            }
            self.previous_state = state
            self.log_open_positions.append(log_entry)

            print(f"[DEBUG] Entrada añadida al log desde process_open_positions: {log_entry}")
            print(f"[INFO] Evaluación completada. Acciones registradas: {to_close}")

            # 🔹 8) Guardar cambios en el position_tracker
            self.save_position_tracker()

        except Exception as e:
            print(f"[ERROR] Fallo durante el procesamiento de posiciones: {e}")


    def process_data(self, row, positions, balance, state):
        """
        Procesa los datos actuales usando la estrategia y valida las posiciones.
        """
        try:
            previous_state = getattr(self, "previous_state", None)

            # Validar precisión antes de la predicción
            input_features = [list(row[self.features])]
            print(f"[DEBUG] Valores para predicción: {input_features}")
            current_state = self.model.predict(input_features)[0]

            # Validar y formatear posiciones abiertas
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

            # Mantener coherencia con el estado
            current_state = self.model.predict([list(row[self.features])])[0]
            previous_state = self.previous_state
            self.previous_state = current_state

            # Desescalar valores para mostrar en log
            descaled_values = {}
            descaled_values["Datetime"] = self.format_datetime(row["Datetime"])
            if "Close" in self.features:
                descaled_values["Close"] = self.descale_value("Close", row["Close"])
            else:
                descaled_values["Close"] = row["Close"]

            # Decisión de estrategia
            decision = self.strategy.decide(
                state=current_state,
                current_price=row["Close"],
                balance=self.balance,
                features={
                    "RSI": row.get("RSI", 0),
                    "MACD": row.get("MACD", 0),
                    "ATR": row.get("ATR", 0),
                    "VolumeChange": row.get("VolumeChange", 0),
                },
                previous_state=previous_state,
                market_id="ETHUSD",
            )

            # Ejecutar acción si corresponde
            if decision["action"] == "sell":
                self.capital_ops.open_position(
                    market_id=decision["market_id"],
                    direction=decision["action"].upper(),
                    size=decision["size"],
                    stop_loss=decision.get("stop_loss"),
                    take_profit=decision.get("take_profit")
                )

            # Registrar en el log
            log_entry = {
                "datetime": str(descaled_values["Datetime"]),
                "current_price": float(row["Close"]),
                "balance": float(self.balance),
                "decision": decision,
                "descaled_values": descaled_values,
                "state": int(current_state),
                "previous_state": int(previous_state) if previous_state is not None else None
            }
            self.previous_state = state
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
                    print(f"  - Instrumento: {pos.get('instrument', 'N/A')}")
                    print(f"  - Dirección: {pos.get('direction', 'N/A')}")
                    print(f"    Tamaño: {pos.get('size', 'N/A')}")
                    print(f"    Precio de apertura: {pos.get('price', 'N/A')}")
                    
                    # Ganancia/Pérdida con colores de fondo
                    gain_loss = pos.get("upl", "N/A")
                    if isinstance(gain_loss, (int, float)):  # Asegúrate de que sea numérico
                        if gain_loss < 0:
                            print(f"\033[41m    Ganancia/Pérdida: {gain_loss}\033[0m")  # Fondo rojo
                        else:
                            print(f"\033[42m    Ganancia/Pérdida: {gain_loss}\033[0m")  # Fondo verde
                    else:
                        print(f"    Ganancia/Pérdida: {gain_loss}")  # Para valores no numéricos

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
                print(f" 💲 Balance disponible: {entry['balance']:.2f}")
                print(f" 📍Posiciones abiertas:")
                for pos in entry.get("positions", []):
                    print(f"  - Dirección: {pos.get('direction', 'N/A')}")
                    print(f"    Tamaño: {pos.get('size', 'N/A')}")
                    print(f"    Precio de apertura: {pos.get('price', 'N/A')}")
                    print(f"  💰  Ganancia/Pérdida: {pos.get('upl', 'N/A')}")

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
        MODEL_FILE = "NeoModel.pkl"
        DATA_FILE = "/home/hobeat/MoneyMakers/Reports/ETH_USD_1Y1HM2.json"

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
