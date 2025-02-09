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
import pickle  # Asegura que pickle esté disponible
from datetime import datetime, timezone

# Lógica para decisiones
class TradingOperator(QObject):

    positions_updated = pyqtSignal(list)  # Señal para emitir las posiciones actualizadas

    def __init__(self, model, features, strategy, saldo_update_callback, scaler_stats):
        super().__init__()

        self.model = model
        # Se limpian los nombres de las features
        self.features = [f.strip() for f in features]
        self.strategy = strategy  # La estrategia se pasa como argumento
        self.log_open_positions = []
        self.log_process_data = []
        self.previous_state = None  # Inicializa el estado previo como None
        self.scaler_mean = scaler_stats["mean"]
        self.scaler_scale = scaler_stats["scale"]
        self.capital_ops = CapitalOP()  # Ensure authenticated here if required
        self.account_id = "260136346534097182"  # Tu cuenta Id
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
            from DataEth import process_data, calculate_indicators, prepare_for_export
            import yfinance as yf

            ticker = "ETH-EUR"
            interval = "1h"
            period = "2y"
            data = yf.download(ticker, interval=interval, period=period)

            if data.empty:
                print("[ERROR] No se obtuvieron datos históricos.")
                return

            # Procesar los datos
            data = process_data(data, ticker)
            data = calculate_indicators(data)
            data = prepare_for_export(data)

            # Reconvertir la columna 'Datetime' a datetime y establecerla como índice
            if 'Datetime' in data.columns:
                data['Datetime'] = pd.to_datetime(data['Datetime'], unit='ms', errors='coerce')
                data.set_index('Datetime', inplace=True)
                data.sort_index(inplace=True)
                # Reordenar las columnas para que las que usa el modelo aparezcan primero:
                data = data[self.features + [col for col in data.columns if col not in self.features]]
            else:
                print("[WARNING] No se encontró la columna 'Datetime' después de preparar los datos.")

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
            while True:
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

                print("[DEBUG] Verificando índice del DataFrame...")
                print(type(data_frame.index))
                print(data_frame.index[:5])  # Muestra las primeras 5 filas del índice

                # ✅ Asegurar que el índice es un DatetimeIndex
                if not isinstance(data_frame.index, pd.DatetimeIndex):
                    print("[WARNING] Índice no es de tipo DatetimeIndex. Convirtiendo...")
                    data_frame.index = pd.to_datetime(data_frame.index, errors='coerce')

                # ✅ Asegurar que el índice tiene timezone UTC
                if data_frame.index.tz is None:
                    data_frame.index = data_frame.index.tz_localize("UTC")

                # ✅ Eliminar valores nulos en el índice
                if data_frame.index.hasnans:
                    print("[WARNING] Se encontraron valores NaT en el índice. Eliminando...")
                    data_frame = data_frame.dropna(subset=["Datetime"])  # Suponiendo que "Datetime" existe

                if data_frame.empty:
                    print("[WARNING] El DataFrame está vacío. No hay datos para procesar.")
                    time.sleep(interval)
                    continue

                latest_row = self.get_latest_data(data_frame)


                # ✅ Validar que `latest_row.name` sea un Timestamp con timezone
                if not isinstance(latest_row.name, pd.Timestamp):
                    print(f"[ERROR] latest_row.name no es un Timestamp válido: {latest_row.name}")
                    time.sleep(interval)
                    continue

                if latest_row.name.tz is None:
                    latest_row.name = latest_row.name.tz_localize("UTC")

                try:
                    balance, positions = self.update_balance_and_positions()
                except Exception as e:
                    print(f"[ERROR] Error al actualizar saldo y posiciones: {e}")
                    time.sleep(interval)
                    continue

                # ✅ Obtener el estado usando el modelo con validación
                try:
                    input_features = [list(latest_row[self.features])]

                    if hasattr(self.model, "smoothed_marginal_probabilities"):
                        smoothed_probs = pd.DataFrame(self.model.smoothed_marginal_probabilities)
                        if not smoothed_probs.empty:
                            state = smoothed_probs.idxmax(axis=1).values[-1]  # Último estado detectado
                            print(f"[DEBUG] Estado calculado: {state}")
                        else:
                            print("[ERROR] El DataFrame de probabilidades marginales está vacío.")
                            state = None
                    else:
                        print("[ERROR] El modelo no tiene 'smoothed_marginal_probabilities'. No se puede calcular estado.")
                        state = None
                        continue
                except Exception as e:
                    print(f"[ERROR] Error al predecir el estado: {e}")
                    state = None
                    continue

                try:
                    self.process_data(row=latest_row, positions=positions, balance=balance, state=state)
                except Exception as e:
                    print(f"[ERROR] Error al procesar datos: {e}")

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
                    print(f"[ERROR] Error al evaluar posiciones abiertas: {e}")

                print("[INFO] Fila procesada exitosamente.")
                self.print_log()
                time.sleep(interval)

        except Exception as e:
            print(f"[ERROR] Error en el bucle principal: {e}")





    def descale_value(self, feature_name, value):
        """
        Desescala un valor utilizando las estadísticas del escalador.
        Si la característica es "Close" (que no se escala), se retorna el valor original.
        """
        try:
            if feature_name == "Close":
                print(f"[DEBUG] La característica {feature_name} no se escala. Usando valor original: {value}")
                return value
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
            return value

    
    def update_balance_and_positions(self):
        try:
            account_info = self.capital_ops.get_account_summary()
            if not account_info or "accounts" not in account_info:
                print("[ERROR] No se recibió información válida de la cuenta.")
                return 0, []
            
            accounts = account_info.get("accounts", [])
            if not accounts:
                print("[ERROR] No se encontraron cuentas.")
                return 0, []
            
            account_data = accounts[0]
            self.balance = account_data.get("balance", {}).get("available", 0)
            print("[INFO] Balance actualizado:", self.balance)
            
            positions = self.capital_ops.get_open_positions()
            print("[DEBUG] Respuesta de posiciones abiertas:", positions)
            
            if not isinstance(positions, dict) or "positions" not in positions:
                print("[ERROR] Formato inesperado en las posiciones abiertas.")
                return self.balance, []
            
            return self.balance, positions["positions"]

        except Exception as e:
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
                continue
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
            print("[INFO] No se encontró el archivo position_tracker.json. Inicializando diccionario vacío.")
            self.position_tracker = {}

    def format_datetime(self, timestamp):
        if isinstance(timestamp, (pd.Timestamp, datetime)):
            return timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            return pd.to_datetime(timestamp, unit='ms').strftime('%Y-%m-%d %H:%M:%S')

    def process_open_positions(self, account_id, capital_ops, current_price, features, state, previous_state):
        try:
            previous_state = self.previous_state
            print(f"[DEBUG] Estado previo antes de procesar: {previous_state}")

            # 1) Obtener solo posiciones SELL
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
                        print(f"[WARNING] `createdDateUTC` no encontrado para la posición {deal_id}")
                        hours_open = "N/A"
                except Exception as e:
                    print(f"[ERROR] No se pudo calcular las horas abiertas de {deal_id}: {e}")
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

            # 3) Desescalar valores
            unscaled_current_price = self.descale_value("Close", current_price)
            unscaled_features = {feat: self.descale_value(feat, val) if feat in self.features else val for feat, val in features.items()}

            # 4) Evaluar con la estrategia
            to_close = self.strategy.evaluate_positions(
                positions=formatted_positions,
                current_price=unscaled_current_price,
                state=state,
                features=unscaled_features,
                previous_state=previous_state
            )

            # 5) Cerrar posiciones si se indica
            for action in to_close:
                if action["action"] == "Close":
                    deal_id = action.get("dealId")
                    if deal_id:
                        capital_ops.close_position(deal_id)
                        print(f"[INFO] Cerrando posición con dealId={deal_id}")
                        self.position_tracker.pop(deal_id, None)
                    else:
                        print("[ERROR] No se proporcionó dealId para la posición a cerrar.")

            # 6) Actualizar max_profit
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

            # 7) Crear y registrar log
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

            print(f"[DEBUG] Entradef process_datada añadida al log desde process_open_positions: {log_entry}")
            print(f"[INFO] Evaluación completada. Acciones registradas: {to_close}")

            # 8) Guardar cambios en el position_tracker
            self.save_position_tracker()

        except Exception as e:
            print(f"[ERROR] Fallo durante el procesamiento de posiciones: {e}")

    def process_data(self, row, positions, balance, state):
        try:
            previous_state = self.previous_state

            print("\n[DEBUG] ==============================")
            print(f"[DEBUG] row.name: {row.name}")
            print(f"[DEBUG] Tipo de row.name: {type(row.name)}")

            if row.name is None or not isinstance(row.name, pd.Timestamp):
                print(f"[ERROR] La fila no tiene un índice válido. Índice actual: {row.name}")
                return

            # Construir el DataFrame de entrada a partir de la fila actual usando las features
            input_df = pd.DataFrame([row[self.features]])
            input_df.index = pd.RangeIndex(start=0, stop=len(input_df), step=1)
            print("[DEBUG] input_df:")
            print(input_df)
            print(f"[DEBUG] Valores para predicción: {input_df.values.tolist()}")

            if input_df.empty:
                print("[ERROR] input_df está vacío")
                return

            # En lugar de llamar a predict con exog (lo que genera el error), usamos las probabilidades suavizadas
            smoothed_probs = pd.DataFrame(self.model.smoothed_marginal_probabilities)
            current_state = smoothed_probs.iloc[-1].idxmax()
            print(f"[DEBUG] Estado predicho (usando smoothed probabilities): {current_state}")

            # Obtener posiciones abiertas actuales
            buy_positions, sell_positions = self.capital_ops.get_open_positions()
            num_buy_positions = len(buy_positions)
            max_buy_positions = self.capital_ops.max_buy_positions
            num_sell_positions = len(sell_positions)
            max_sell_positions = self.capital_ops.max_sell_positions
            print(f"[INFO] 📊 Posiciones actuales: BUY={num_buy_positions}, SELL={len(sell_positions)} (Máx permitido: {max_sell_positions})")

            # Si se ha alcanzado el límite de posiciones BUY, se registra y se sale
            if num_sell_positions >= max_sell_positions:
                print("[INFO] 🚨 Límite de posiciones Sell alcanzado. No se abrirá una nueva posición.")
                log_entry = {
                    "datetime": str(row.name),
                    "current_price": float(row["Close"]),
                    "balance": float(self.balance),
                    "decision": "HOLD - Límite de posiciones Sell alcanzado",
                    "state": int(current_state),
                    "previous_state": int(previous_state) if previous_state is not None else None
                }
                self.log_process_data.append(log_entry)
                return

            # Evaluar la estrategia para tomar la decisión
            decision = self.strategy.decide(
                state=current_state,
                current_price=row["Close"],
                balance=self.balance,
                features={key: row.get(key, 0) for key in ["RSI", "MACD", "ATR", "VolumeChange"]},
                previous_state=previous_state,
                market_id="ETHUSD"
            )

            log_entry = {
                "datetime": str(row.name),
                "current_price": float(row["Close"]),
                "balance": float(self.balance),
                "decision": decision["action"],
                "state": int(current_state),
                "previous_state": int(previous_state) if previous_state is not None else None
            }
            self.log_process_data.append(log_entry)

            # Si la estrategia indica comprar, se abre la posición
            if decision["action"] == "sell":
                self.capital_ops.open_position(
                    market_id=decision["market_id"],
                    direction="BUY",
                    size=decision["size"],
                    stop_loss=decision.get("stop_loss"),
                    take_profit=decision.get("take_profit")
                )

            print(f"[INFO] Log actualizado Desde Process Data (Decide): {json.dumps(log_entry, ensure_ascii=False, indent=4)}")

        except Exception as e:
            print(f"[ERROR] Error en process_data: {e}")







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
                else:
                    print(f"🔥 Decisión tomada: {entry['decision']}")
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
                print(f"📊 Posiciones abiertas: BUY={num_buy}, SELL={num_sell} (Máx permitido: 2)")
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
        # **Limpia los nombres de las columnas**
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
        print(f"[ERROR] Error durante la ejecución principal: {e}")
