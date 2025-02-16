import time
import pandas as pd
import os
import json
import subprocess
from EthSession import CapitalOP
from EthStrategy import Strategia
from PyQt5.QtCore import QObject, pyqtSignal
from threading import Lock
import pickle
from datetime import datetime, timezone

class TradingOperator(QObject):

    positions_updated = pyqtSignal(list)

    def __init__(self, model, features, strategy, saldo_update_callback, scaler_stats):
        super().__init__()
        self.model = model
        self.features = [f.strip() for f in features]  # Features definidas por el modelo
        self.strategy = strategy
        self.log_open_positions = []
        self.log_process_data = []
        self.previous_state = None
        self.scaler_mean = scaler_stats.get("mean", [])
        self.scaler_scale = scaler_stats.get("scale", [])
        self.capital_ops = CapitalOP()
        self.account_id = "260383560551191748"
        self.capital_ops.set_account_id(self.account_id)
        self.positions = []
        self.saldo_update_callback = saldo_update_callback
        self.last_processed_index = -1
        self.balance = 0
        self.position_tracker = {}
        self.data_lock = Lock()
        self.historical_data = None

    def update_historical_data(self):
        """
        Ejecuta DataEth.py para descargar y procesar los datos desde Capital.com
        y luego carga el JSON generado en self.historical_data con validaciones adicionales.
        """
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            dataeth_path = os.path.join(script_dir, "DataEth.py")

            print(f"[INFO] 🔄 Ejecutando DataEth.py en {dataeth_path} para actualizar datos desde Capital.com...")

            if not os.path.exists(dataeth_path):
                print(f"[ERROR] ❌ No se encontró DataEth.py en {dataeth_path}")
                return

            process = subprocess.Popen(["python3", dataeth_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            for line in process.stdout:
                print(f"[DATAETH] {line.strip()}")

            process.wait()

            if process.returncode == 0:
                print("[INFO] ✅ DataEth.py ejecutado con éxito. Datos actualizados.")
            else:
                print(f"[ERROR] ❌ Error al ejecutar DataEth.py. Código de salida: {process.returncode}")
                for error_line in process.stderr:
                    print(f"[DATAETH-ERROR] {error_line.strip()}")
                return

            # Validar que el archivo de datos generado realmente existe
            output_file = "/home/hobeat/MoneyMakers/Reports/ETHUSD_CapitalData.json"
            if not os.path.exists(output_file):
                print("[ERROR] ❌ No se encontró el archivo de datos después de ejecutar DataEth.py.")
                return

            print(f"[INFO] 📂 Cargando datos desde {output_file}...")

            with open(output_file, 'r') as f:
                raw_data = json.load(f)

            if "data" not in raw_data or not isinstance(raw_data["data"], list):
                print("[ERROR] ❌ El archivo JSON no contiene la clave 'data' o no es una lista.")
                return

            self.historical_data = pd.DataFrame(raw_data["data"])

            # **VALIDACIÓN CRÍTICA**: Buscar el nombre correcto de la columna de tiempo
            if "Datetime" not in self.historical_data.columns:
                if "snapshotTime" in self.historical_data.columns:
                    print("[INFO] 🔄 Renombrando 'snapshotTime' a 'Datetime'...")
                    self.historical_data.rename(columns={'snapshotTime': 'Datetime'}, inplace=True)
                else:
                    print(f"[ERROR] ❌ No se encontró una columna de tiempo válida. Columnas disponibles: {self.historical_data.columns.tolist()}")
                    return

            # **Convertir 'Datetime' a índice de tiempo correctamente**
            self.historical_data['Datetime'] = pd.to_datetime(self.historical_data['Datetime'], errors='coerce', utc=True)

            # **Eliminar valores NaT antes de establecer el índice**
            self.historical_data.dropna(subset=['Datetime'], inplace=True)

            # **Revisar si después de eliminar NaT el DataFrame está vacío**
            if self.historical_data.empty:
                print("[ERROR] ❌ El DataFrame quedó vacío después de eliminar NaT en 'Datetime'.")
                return

            # **Convertir Datetime a índice**
            self.historical_data.set_index('Datetime', inplace=True)
            self.historical_data.sort_index(inplace=True)

            # **Asegurar que el índice es un DatetimeIndex**
            if not isinstance(self.historical_data.index, pd.DatetimeIndex):
                print(f"[ERROR] ❌ El índice del DataFrame no es un DatetimeIndex. Tipo actual: {type(self.historical_data.index)}")
                return

            print("[INFO] ✅ Datos históricos cargados exitosamente después de ejecutar DataEth.py.")

        except Exception as e:
            print(f"[ERROR] ❌ Error al actualizar datos históricos: {e}")




    def get_model_input(self, row):
        """
        Extrae y devuelve un DataFrame con las features necesarias para la predicción.
        """
        try:
            input_df = pd.DataFrame([row[self.features]])
            input_df.index = pd.RangeIndex(start=0, stop=len(input_df), step=1)
            return input_df
        except Exception as e:
            print(f"[ERROR] Error al extraer features para el modelo: {e}")
            return None

    def predict_state(self, latest_row):
        """
        Predice el estado actual basado en las features seleccionadas.
        """
        try:
            input_df = self.get_model_input(latest_row)
            if input_df is None or input_df.empty:
                print("[ERROR] input_df está vacío. No se puede predecir estado.")
                return None

            if hasattr(self.model, "smoothed_marginal_probabilities"):
                smoothed_probs = pd.DataFrame(self.model.smoothed_marginal_probabilities)
                if not smoothed_probs.empty:
                    state = smoothed_probs.idxmax(axis=1).values[-1]
                    print(f"[DEBUG] Estado calculado: {state}")
                    return state
                else:
                    print("[ERROR] El DataFrame de probabilidades marginales está vacío.")
                    return None
            else:
                print("[ERROR] El modelo no tiene 'smoothed_marginal_probabilities'. No se puede calcular estado.")
                return None
        except Exception as e:
            print(f"[ERROR] Error al predecir el estado: {e}")
            return None

    def run_main_loop(self, data_frame, interval=25):
        print("[INFO] Iniciando bucle principal de TradingOperator.")

        try:
            while True:
                try:
                    print("[INFO] 🔄 Iniciando actualización de datos históricos...")
                    self.update_historical_data()
                    if self.historical_data is not None:
                        data_frame = self.historical_data
                    print("[INFO] ✅ Actualización de datos históricos completada.")
                except Exception as e:
                    print(f"[ERROR] ❌ Error al actualizar datos históricos: {e}")
                    time.sleep(interval)
                    continue

                print("[DEBUG] 📊 Verificando índice del DataFrame...")
                print(type(data_frame.index))
                print(data_frame.index[:5])  # Muestra las primeras 5 filas del índice

                # ✅ Asegurar que el índice es un DatetimeIndex
                if not isinstance(data_frame.index, pd.DatetimeIndex):
                    print("[WARNING] ⚠️ Índice no es de tipo DatetimeIndex. Convirtiendo...")
                    data_frame.index = pd.to_datetime(data_frame.index, errors='coerce')

                # ✅ Asegurar que el índice tiene timezone UTC
                if data_frame.index.tz is None:
                    data_frame.index = data_frame.tz_localize("UTC")

                # ✅ Eliminar valores nulos en el índice
                if data_frame.index.hasnans:
                    print("[WARNING] ⚠️ Se encontraron valores NaT en el índice. Eliminando...")
                    data_frame = data_frame.dropna(subset=["Datetime"])  # Suponiendo que "Datetime" existe

                if data_frame.empty:
                    print("[WARNING] ⚠️ El DataFrame está vacío. No hay datos para procesar.")
                    time.sleep(interval)
                    continue

                latest_row = self.get_latest_data(data_frame)

                # ✅ Validar que `latest_row.name` sea un Timestamp con timezone
                if not isinstance(latest_row.name, pd.Timestamp):
                    print(f"[ERROR] ❌ latest_row.name no es un Timestamp válido: {latest_row.name}")
                    time.sleep(interval)
                    continue

                if latest_row.name.tz is None:
                    latest_row.name = latest_row.name.tz_localize("UTC")

                try:
                    balance, positions = self.update_balance_and_positions()
                except Exception as e:
                    print(f"[ERROR] ❌ Error al actualizar saldo y posiciones: {e}")
                    time.sleep(interval)
                    continue

                # ✅ Obtener el estado usando el modelo con validación
                try:
                    input_features = [list(latest_row[self.features])]

                    if hasattr(self.model, "smoothed_marginal_probabilities"):
                        smoothed_probs = pd.DataFrame(self.model.smoothed_marginal_probabilities)
                        if not smoothed_probs.empty:
                            state = smoothed_probs.idxmax(axis=1).values[-1]  # Último estado detectado
                            print(f"[DEBUG] 🧠 Estado calculado: {state}")
                        else:
                            print("[ERROR] ❌ El DataFrame de probabilidades marginales está vacío.")
                            state = None
                    else:
                        print("[ERROR] ❌ El modelo no tiene 'smoothed_marginal_probabilities'. No se puede calcular estado.")
                        state = None
                        continue
                except Exception as e:
                    print(f"[ERROR] ❌ Error al predecir el estado: {e}")
                    state = None
                    continue

                try:
                    self.process_data(row=latest_row, positions=positions, balance=balance, state=state)
                except Exception as e:
                    print(f"[ERROR] ❌ Error al procesar datos: {e}")

                try:
                    current_price = latest_row["Close"]
                    features_dict = latest_row.to_dict()
                    self.process_open_positions(
                        account_id=self.account_id,
                        capital_ops=self.capital_ops,
                        current_price=current_price,
                        features=features_dict,
                        state=state,
                        previous_state=self.previous_state
                    )
                except Exception as e:
                    print(f"[ERROR] ❌ Error al evaluar posiciones abiertas: {e}")

                print("[INFO] ✅ Fila procesada exitosamente.")
                self.print_log()

                # ✅ Al final, esperar `interval` antes de la próxima iteración
                time.sleep(interval)

        except Exception as e:
            print(f"[ERROR] ❌ Error en el bucle principal: {e}")

    def descale_value(self, feature_name, value):
        try:
            if feature_name == "Close":
                print(f"[DEBUG] {feature_name} no se escala. Valor original: {value}")
                return value
            if feature_name not in self.features:
                raise ValueError(f"[ERROR] La feature {feature_name} no está en el modelo.")
            index = self.features.index(feature_name)
            mean = self.scaler_mean[index]
            scale = self.scaler_scale[index]
            descaled_value = (value * scale) + mean
            print(f"[DEBUG] Desescalando {feature_name}: {value} -> {descaled_value} (mean={mean}, scale={scale})")
            return descaled_value
        except Exception as e:
            print(f"[ERROR] Error al desescalar {feature_name}: {e}")
            return value

    def update_balance_and_positions(self):
        try:
            account_info = self.capital_ops.get_account_summary()
            if not account_info or "accounts" not in account_info:
                print("[ERROR] Información de cuenta inválida.")
                return 0, []

            accounts = account_info.get("accounts", [])
            if not accounts:
                print("[ERROR] No se encontraron cuentas.")
                return 0, []

            account_data = accounts[0]
            self.balance = account_data.get("balance", {}).get("available", 0)
            print("[INFO] Balance actualizado:", self.balance)

            positions = self.capital_ops.get_open_positions()

            # DEPURACIÓN: Imprimir el contenido real de la variable antes de la validación
            print("[DEBUG] Contenido de 'positions':", positions)

            if not isinstance(positions, dict) or "positions" not in positions:
                print("[ERROR] Formato inesperado en posiciones abiertas. Contenido recibido:", positions)
                return self.balance, []

            return self.balance, positions["positions"]

        except Exception as e:
            print(f"[ERROR] Error al actualizar saldo y posiciones: {e}")
            return 0, []

    def get_latest_data(self, data_frame):
        if data_frame.empty:
            raise ValueError("[ERROR] Los datos están vacíos.")
        print("[INFO] Última fila cargada:", data_frame.iloc[-1].to_dict())
        return data_frame.iloc[-1]

    def process_open_positions(self, account_id, capital_ops, current_price, features, state, previous_state):
        try:
            previous_state = self.previous_state
            print(f"[DEBUG] Estado previo: {previous_state}")

            _, sell_positions = capital_ops.get_open_positions()
            print(f"[INFO] Procesando {len(sell_positions)} posiciones SELL abiertas.")
            formatted_positions = []
            now_time = datetime.now(timezone.utc)
            for position in sell_positions:
                position_data = position.get("position", {})
                market_data = position.get("market", {})
                required_keys = ["level", "direction", "size", "createdDateUTC"]
                if any(key not in position_data or position_data[key] is None for key in required_keys):
                    print(f"[ERROR] Posición SELL incompleta: {position_data}")
                    continue
                deal_id = position_data.get("dealId") or f"temp_{id(position)}"
                try:
                    created_date_str = position_data.get("createdDateUTC")
                    if created_date_str:
                        created_time = datetime.strptime(created_date_str, "%Y-%m-%dT%H:%M:%S.%f")
                        created_time = created_time.replace(tzinfo=timezone.utc)
                        hours_open = (now_time - created_time).total_seconds() / 3600
                    else:
                        print(f"[WARNING] No se encontró 'createdDateUTC' para {deal_id}")
                        hours_open = "N/A"
                except Exception as e:
                    print(f"[ERROR] No se pudo calcular horas abiertas de {deal_id}: {e}")
                    hours_open = "N/A"
                prev_max_profit = self.position_tracker.get(deal_id, {}).get("max_profit", 0)
                fpos = {
                    "price": position_data["level"],
                    "direction": position_data["direction"],
                    "size": position_data["size"],
                    "upl": position_data.get("upl", 0),
                    "instrument": market_data.get("instrumentName", "N/A"),
                    "dealId": deal_id,
                    "max_profit": prev_max_profit,
                    "hours_open": hours_open
                }
                formatted_positions.append(fpos)
                print(f"[DEBUG] Posición formateada: {fpos}")

            unscaled_current_price = self.descale_value("Close", current_price)
            unscaled_features = {
                feat: self.descale_value(feat, val) if feat in self.features else val 
                for feat, val in features.items()
            }

            to_close = self.strategy.evaluate_positions(
                positions=formatted_positions,
                current_price=unscaled_current_price,
                state=state,
                features=unscaled_features,
                previous_state=previous_state
            )

            for action in to_close:
                if action["action"] == "Close":
                    deal_id = action.get("dealId")
                    if deal_id:
                        capital_ops.close_position(deal_id)
                        print(f"[INFO] Cerrando posición con dealId={deal_id}")
                        self.position_tracker.pop(deal_id, None)
                    else:
                        print("[ERROR] dealId no proporcionado para cerrar posición.")

            for fpos in formatted_positions:
                d_id = fpos["dealId"]
                direction = fpos["direction"].upper()
                entry_price = fpos["price"]
                if direction == "BUY":
                    current_profit = (unscaled_current_price - entry_price) / entry_price
                elif direction == "SELL":
                    current_profit = (entry_price - unscaled_current_price) / entry_price
                else:
                    print(f"[WARNING] Dirección desconocida: {direction}.")
                    continue
                self.position_tracker[d_id] = {
                    "max_profit": max(self.position_tracker.get(d_id, {}).get("max_profit", 0), current_profit)
                }
                fpos["max_profit"] = self.position_tracker[d_id]["max_profit"]

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

            print(f"[DEBUG] Log desde process_open_positions: {log_entry}")
            print(f"[INFO] Evaluación completada. Acciones: {to_close}")

            self.save_position_tracker()

        except Exception as e:
            print(f"[ERROR] Fallo en process_open_positions: {e}")

    def process_data(self, row, positions, balance, state):
        try:
            if row.name is None or not isinstance(row.name, pd.Timestamp):
                print(f"[ERROR] Índice inválido en la fila: {row.name}")
                return

            input_df = self.get_model_input(row)
            if input_df is None or input_df.empty:
                print("[ERROR] input_df vacío en process_data")
                return

            current_state = state
            print(f"[DEBUG] Estado predicho: {current_state}")

            buy_positions, sell_positions = self.capital_ops.get_open_positions()
            num_buy_positions = len(buy_positions)
            max_buy_positions = self.capital_ops.max_buy_positions
            num_sell_positions = len(sell_positions)
            max_sell_positions = self.capital_ops.max_sell_positions
            print(f"[INFO] Posiciones actuales: BUY={num_buy_positions}, SELL={num_sell_positions} (Máx SELL: {max_sell_positions})")

            if num_sell_positions >= max_sell_positions:
                log_entry = {
                    "datetime": str(row.name),
                    "current_price": float(row["Close"]),
                    "balance": float(self.balance),
                    "decision": "HOLD - Límite de posiciones Sell alcanzado",
                    "reason": "Max sell positions reached",
                    "state": int(current_state),
                    "previous_state": int(self.previous_state) if self.previous_state is not None else None
                }
                self.log_process_data.append(log_entry)
                return

            decision = self.strategy.decide(
                state=current_state,
                current_price=row["Close"],
                balance=self.balance,
                features={key: row.get(key, 0) for key in ["RSI", "MACD", "ATR", "VolumeChange"]},
                previous_state=self.previous_state,
                market_id="ETHUSD"
            )

            log_entry = {
                "datetime": str(row.name),
                "current_price": float(row["Close"]),
                "balance": float(self.balance),
                "decision": decision["action"],
                "reason": decision["reason"],
                "state": int(current_state),
                "previous_state": int(self.previous_state) if self.previous_state is not None else None
            }
            self.log_process_data.append(log_entry)

            if decision["action"] == "Short":
                self.capital_ops.open_position(
                    market_id=decision["market_id"],
                    direction="SELL",
                    size=decision["size"],
                    stop_loss=decision.get("stop_loss"),
                    take_profit=decision.get("take_profit")
                )

            print(f"[INFO] Log desde process_data:\n{json.dumps(log_entry, ensure_ascii=False, indent=4)}")

        except Exception as e:
            print(f"[ERROR] Error en process_data: {e}")

    def save_position_tracker(self, filepath='position_tracker.json'):
        try:
            with open(filepath, 'w') as file:
                json.dump(self.position_tracker, file, indent=4)
            print("[INFO] position_tracker guardado exitosamente.")
        except Exception as e:
            print(f"[ERROR] Error al guardar position_tracker: {e}")

    def load_position_tracker(self, filepath='position_tracker.json'):
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as file:
                    self.position_tracker = json.load(file)
                print("[INFO] position_tracker cargado exitosamente.")
            except Exception as e:
                print(f"[ERROR] Error al cargar position_tracker: {e}")
                self.position_tracker = {}
        else:
            print("[INFO] No se encontró position_tracker.json. Inicializando vacío.")
            self.position_tracker = {}

    def format_datetime(self, timestamp):
        if isinstance(timestamp, (pd.Timestamp, datetime)):
            return timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            return pd.to_datetime(timestamp, unit='ms').strftime('%Y-%m-%d %H:%M:%S')

    def print_log(self):
        """Imprime el log detallado de las operaciones, formateado por origen."""
        print("[INFO] Registro de operaciones detallado:")

        if not self.log_open_positions and not self.log_process_data:
            print("[INFO] Los logs están vacíos. No hay datos para imprimir.")
            return

        if self.log_process_data:
            print("[INFO] Registro desde process_data:")
            for entry in self.log_process_data:
                print("=" * 40)
                print("[ORIGEN] process_data")
                print(f"📉 Precio actual Escalado: {entry['current_price']:.2f}")
                print(f"🧠 Estado predicho por el modelo: {entry['state']}")
                print(f"🔄 Estado previo: {entry['previous_state']}")
                print(f"💰 Balance disponible: {entry['balance']:.2f}")
                if "HOLD" in entry["decision"]:
                    print(f"🚨 Decisión tomada: {entry['decision']}")
                    print(f"📢 Razón: {entry['reason']}")  # 🔹 Agregar la razón aquí

                else:
                    print(f"🔥 Decisión tomada: {entry['decision']}")
                    print(f"📢 Razón: {entry['reason']}")  # 🔹 Agregar la razón aquí

                print("📊 Valores desescalados:")
                if "descaled_values" in entry:
                    for key, value in entry["descaled_values"].items():
                        if key != "Datetime":
                            print(f"  {key}: {value}")
                print("=" * 40)

        if self.log_open_positions:
            print("[INFO] Registro desde process_open_positions:")
            for entry in self.log_open_positions:
                print("=" * 40)
                print("[ORIGEN] process_open_positions")
                print(f"📅 Fecha: {entry['datetime']}")
                print(f"📉 Precio actual: {entry['current_price']:.2f}")
                print(f"🧠 Estado predicho por el modelo: {entry['state']}")
                print(f"🔄 Estado previo: {entry['previous_state']}")
                num_buy = sum(1 for pos in entry.get("positions", []) if pos["direction"].upper() == "BUY")
                num_sell = sum(1 for pos in entry.get("positions", []) if pos["direction"].upper() == "SELL")
                print(f"📊 Posiciones abiertas: BUY={num_buy}, SELL={num_sell} (Máx permitido: {self.capital_ops.max_sell_positions} ")
                print("📍 Posiciones evaluadas:")
                for pos in entry.get("positions", []):
                    upl = pos.get('upl', 'N/A')
                    if upl != 'N/A' and upl is not None:
                        upl = float(upl)
                        if upl >= 0:
                            upl_str = f"\033[42m {upl:.5f} \033[0m"
                        else:
                            upl_str = f"\033[41m {upl:.5f} \033[0m"
                    else:
                        upl_str = "N/A"
                    print("=" * 40)
                    print(f"  - 🎯 Instrumento: {pos.get('instrument', 'N/A')}")
                    print(f"  - 🔀 Dirección: {pos.get('direction', 'N/A')}")
                    print(f"  - 📏 Tamaño: {pos.get('size', 'N/A')}")
                    print(f"  - 💵 Precio de apertura: {pos.get('price', 'N/A')}")
                    print(f"  - ⏳ Horas abiertas: {pos.get('hours_open', 'N/A'):.2f} horas")
                    print(f"  - 📈 Ganancia/Pérdida: {upl_str}")
                    if "log" in pos:
                        for log_message in pos["log"]:
                            print(f"    📌 {log_message}")
                    print("=" * 40)
                print(f"⚡ Acciones tomadas: {entry['actions_taken']}")
                print(f"📊 Características usadas: {entry['features']}")
                print("=" * 40)

        self.log_open_positions = []
        self.log_process_data = []



if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    import sys

    try:
        print("[INFO] Inicializando operador de trading...")
        MODEL_FILE = "msm_model.pkl"
        DATA_FILE = "/home/hobeat/MoneyMakers/Reports/ETH_USD_1Y1HM2.json"

        with open(MODEL_FILE, 'rb') as file:
            model_data = pickle.load(file)

        model = model_data.get('model')
        features = model_data.get('features', [])
        scaler_stats = model_data.get("scaler_stats", {})

        with open(DATA_FILE, 'r') as file:
            raw_data = json.load(file)

        data_frame = pd.DataFrame(raw_data.get('data', []))
        data_frame.columns = data_frame.columns.str.strip()
        if 'Datetime' in data_frame.columns:
            data_frame['Datetime'] = pd.to_datetime(data_frame['Datetime'], unit='ms', errors='coerce')
            data_frame = data_frame.set_index('Datetime')
            data_frame.sort_index(inplace=True)
        else:
            print("[WARNING] No se encontró la columna 'Datetime' en los datos.")

        print("[DEBUG] Tipo de índice:", type(data_frame.index))
        print("[DEBUG] Primeros 5 valores del índice:", data_frame.index[:5])

        capital_ops = CapitalOP()
        strategy = Strategia(capital_ops=capital_ops, threshold_buy=0, threshold_sell=2)

        trading_operator = TradingOperator(
            model=model,
            features=features,
            strategy=strategy,
            saldo_update_callback=None,
            scaler_stats=scaler_stats
        )

        print("[INFO] Inicializando la aplicación PyQt5...")
        app = QApplication(sys.argv)
        trading_operator.run_main_loop(data_frame)
        sys.exit(app.exec_())

    except Exception as e:
        print(f"[ERROR] Error en la ejecución principal: {e}")
