from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QObject, pyqtSignal
from rich.columns import Columns
from rich.console import Console, Group
from rich.console import Console
from rich.layout import Layout
from rich.layout import Layout
from rich.panel import Panel
from rich.panel import Panel
from rich.table import Table
from rich.table import Table
from rich.text import Text
from datetime import datetime, timezone
from EthSession import CapitalOP
from EthStrategy import Strategia
from threading import Lock

import subprocess
import threading
import itertools
import pandas as pd
import textwrap
import json
import time
import sys
import os


class TradingOperator(QObject):

    positions_updated = pyqtSignal(list)

    def __init__(self, features, strategy, saldo_update_callback):
        super().__init__()
        self.features = [f.strip() for f in features]  # Características definidas (para validaciones o logs)
        self.strategy = strategy
        self.log_open_positions = []
        self.log_process_data = []
        # Se elimina el uso de estados y escalado/desescalado
        self.capital_ops = CapitalOP()
        self.account_id = "260494821678994628"
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
        Ejecuta DataEth.py para descargar y procesar los datos desde Capital.com.
        """
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            dataeth_path = os.path.join(script_dir, "DataEth.py")
            output_file = os.path.join(script_dir, "Reports", "ETHUSD_CapitalData.json")

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

            if not os.path.exists(output_file):
                print(f"[ERROR] ❌ No se encontró el archivo de datos después de ejecutar DataEth.py en {output_file}")
                return

            print(f"[INFO] 📂 Cargando datos desde {output_file}...")

            with open(output_file, 'r') as f:
                raw_data = json.load(f)

            if "data" not in raw_data or not isinstance(raw_data["data"], list):
                print("[ERROR] ❌ El archivo JSON no contiene la clave 'data' o no es una lista.")
                return

            self.historical_data = pd.DataFrame(raw_data["data"])

            if "Datetime" not in self.historical_data.columns:
                if "snapshotTime" in self.historical_data.columns:
                    print("[INFO] 🔄 Renombrando 'snapshotTime' a 'Datetime'...")
                    self.historical_data.rename(columns={'snapshotTime': 'Datetime'}, inplace=True)
                else:
                    print(f"[ERROR] ❌ No se encontró una columna de tiempo válida.")
                    return

            self.historical_data['Datetime'] = pd.to_datetime(self.historical_data['Datetime'], errors='coerce', utc=True)
            self.historical_data.dropna(subset=['Datetime'], inplace=True)

            if self.historical_data.empty:
                print("[ERROR] ❌ El DataFrame quedó vacío después de eliminar NaT en 'Datetime'.")
                return

            self.historical_data.set_index('Datetime', inplace=True)
            self.historical_data.sort_index(inplace=True)

            if not isinstance(self.historical_data.index, pd.DatetimeIndex):
                print(f"[ERROR] ❌ El índice del DataFrame no es un DatetimeIndex.")
                return

            print("[INFO] ✅ Datos históricos cargados exitosamente.")

        except Exception as e:
            print(f"[ERROR] ❌ Error al actualizar datos históricos: {e}")

    def run_main_loop(self, data_frame, interval=25):
        print("[INFO] Iniciando bucle principal de TradingOperator.")

        try:
            while True:
                try:
                    print("[INFO] 🔄 Iniciando actualización de datos históricos...")
                    self.update_historical_data()

                    if self.historical_data is not None and not self.historical_data.empty:
                        data_frame = self.historical_data
                        print("[INFO] ✅ Actualización de datos históricos completada.")
                    else:
                        print("[WARNING] ⚠️ Los datos históricos están vacíos después de la actualización.")
                        time.sleep(interval)
                        continue

                except Exception as e:
                    print(f"[ERROR] ❌ Error al actualizar datos históricos: {e}")
                    time.sleep(interval)
                    continue

                # Validar el índice de tiempo
                if not isinstance(data_frame.index, pd.DatetimeIndex):
                    print("[WARNING] ⚠️ Índice no es de tipo DatetimeIndex. Convirtiendo...")
                    data_frame.index = pd.to_datetime(data_frame.index, errors='coerce')

                if data_frame.index.tz is None:
                    data_frame.index = data_frame.tz_localize("UTC")

                if data_frame.index.hasnans:
                    print("[WARNING] ⚠️ Se encontraron valores NaT en el índice. Eliminando...")
                    data_frame = data_frame.dropna(subset=["Datetime"])

                if data_frame.empty:
                    print("[WARNING] ⚠️ El DataFrame está vacío. No hay datos para procesar.")
                    time.sleep(interval)
                    continue

                # Procesar la última fila de datos
                latest_row = self.get_latest_data(data_frame)

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

                try:
                    self.process_data(row=latest_row, positions=positions, balance=balance)
                except Exception as e:
                    print(f"[ERROR] ❌ Error al procesar datos: {e}")

                try:
                    # Verificar si las columnas críticas tienen valores válidos
                    if pd.isna(latest_row.get("Close")):
                        print("[ERROR] ❌ El valor de 'Close' es NaN. Saltando esta fila.")
                        time.sleep(interval)
                        continue

                    current_price = latest_row["Close"]
                    features_dict = latest_row.to_dict()

                    self.process_open_positions(
                        account_id=self.account_id,
                        capital_ops=self.capital_ops,
                        current_price=current_price,
                        features=features_dict
                    )
                except Exception as e:
                    print(f"[ERROR] ❌ Error al evaluar posiciones abiertas: {e}")

                print("[INFO] ✅ Fila procesada exitosamente.")
                self.print_log()

                time.sleep(interval)

        except KeyboardInterrupt:
            print("[INFO] 🛑 Bucle de trading detenido manualmente por el usuario.")
        except Exception as e:
            print(f"[ERROR] ❌ Error en el bucle principal: {e}")

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
            print("[DEBUG] Contenido de 'positions':", positions)

            if isinstance(positions, tuple):  
                positions = positions[1]

            if not isinstance(positions, list):
                print("[ERROR] Formato inesperado en posiciones abiertas. Contenido recibido:", positions)
                return self.balance, []

            return self.balance, positions

        except Exception as e:
            print(f"[ERROR] Error al actualizar saldo y posiciones: {e}")
            return 0, []

    def get_latest_data(self, data_frame):
        if data_frame.empty:
            raise ValueError("[ERROR] Los datos están vacíos.")
        print("[INFO] Última fila cargada:", data_frame.iloc[-1].to_dict())
        return data_frame.iloc[-1]

    def process_open_positions(self, account_id, capital_ops, current_price, features):
        try:
            print("[DEBUG] Procesando posiciones abiertas (BUY y SELL).")

            buy_positions, sell_positions = capital_ops.get_open_positions()
            all_positions = buy_positions + sell_positions  # ✅ Ahora manejamos ambas
            print(f"[INFO] Procesando {len(all_positions)} posiciones abiertas.")

            formatted_positions = []
            now_time = datetime.now(timezone.utc)

            for position in all_positions:
                position_data = position.get("position", {})
                market_data = position.get("market", {})

                required_keys = ["level", "direction", "size", "createdDateUTC"]
                if any(key not in position_data or position_data[key] is None for key in required_keys):
                    print(f"[ERROR] Posición incompleta: {position_data}")
                    continue

                deal_id = position_data.get("dealId") or f"temp_{id(position)}"

                # 📌 Calcular horas abiertas
                try:
                    created_date_str = position_data.get("createdDateUTC")
                    if created_date_str:
                        created_time = datetime.strptime(created_date_str, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
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
                    "hours_open": hours_open,
                    # Aquí se incorporará "reason" desde evaluate_positions
                    "reason": ""
                }
                formatted_positions.append(fpos)
                print(f"[DEBUG] Posición formateada: {fpos}")

            # ✅ Evaluar posiciones abiertas con la estrategia (actualiza cada posición con su 'reason')
            to_close = self.strategy.evaluate_positions(
                positions=formatted_positions,
                current_price=current_price,
                features=features
            )

            # ✅ Cerrar posiciones si es necesario
            for action in to_close:
                if action["action"] == "Close":
                    deal_id = action.get("dealId")
                    if deal_id:
                        capital_ops.close_position(deal_id)
                        print(f"[INFO] Cerrando posición con dealId={deal_id}")
                        self.position_tracker.pop(deal_id, None)
                    else:
                        print("[ERROR] dealId no proporcionado para cerrar posición.")

            # ✅ Actualizar el seguimiento de ganancias y pérdidas
            for fpos in formatted_positions:
                d_id = fpos["dealId"]
                direction = fpos["direction"].upper()
                entry_price = fpos["price"]

                if direction == "BUY":
                    current_profit = (current_price - entry_price) / entry_price
                elif direction == "SELL":
                    current_profit = (entry_price - current_price) / entry_price
                else:
                    print(f"[WARNING] Dirección desconocida: {direction}.")
                    continue

                self.position_tracker[d_id] = {
                    "max_profit": max(self.position_tracker.get(d_id, {}).get("max_profit", 0), current_profit)
                }
                fpos["max_profit"] = self.position_tracker[d_id]["max_profit"]

            # ✅ Construir el log de la evaluación
            # Aquí se recopilan las razones de cada posición evaluada
            evaluation_reasons = []
            for fpos in formatted_positions:
                evaluation_reasons.append({
                    "dealId": fpos["dealId"],
                    "reason": fpos.get("reason", ""),
                    "max_profit": fpos.get("max_profit", None)
                })

            log_entry = {
                "datetime": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                "current_price": current_price,
                "positions": formatted_positions,
                "actions_taken": to_close,
                "evaluation_reasons": evaluation_reasons,  # Aquí se incluyen las razones y max_profit de cada posición
                "features": {key: features[key] for key in ["Close", "RSI", "ATR", "VolumeChange"] if key in features},
            }
            self.log_open_positions.append(log_entry)

            print(f"[DEBUG] Log desde process_open_positions: {log_entry}")
            print(f"[INFO] Evaluación completada. Acciones: {to_close}")

            self.save_position_tracker()

        except Exception as e:
            print(f"[ERROR] Fallo en process_open_positions: {e}")



    def process_data(self, row, positions, balance):
        """
        Procesa los datos actuales usando la estrategia, validando las posiciones, registrando la tendencia 
        y abriendo nuevas posiciones según se reciba una señal de BUY o SELL, siempre respetando los máximos permitidos.
        """
        try:
            if row is None:
                print("[ERROR] ❌ La fila de datos es None.")
                return

            # Convertir la fila en diccionario si es necesario
            if isinstance(row, pd.Series):
                dt = row.name  # El índice contiene la fecha/hora
                row = row.to_dict()
                row["Datetime"] = self.format_datetime(dt)
            elif not isinstance(row, dict):
                print("[ERROR] ❌ La fila de datos no es válida.")
                return

            # Verificar si faltan características esenciales en la fila
            missing_features = [f for f in self.features if f not in row]
            if missing_features:
                print(f"[ERROR] ❌ Faltan estas características en `row`: {missing_features}")
                return

            # Cargar datos históricos y datos en 1M desde self.strategy
            historical_data, data = self.strategy.load_historical_data()

            if historical_data.empty or data.empty:
                print("[ERROR] ❌ No se pudieron cargar correctamente los datos históricos o de 1M (están vacíos).")
                return

            # Detectar tendencia usando historical_data
            trend = self.strategy.detect_trend(historical_data, data)

            # Obtener posiciones abiertas
            buy_positions, sell_positions = self.capital_ops.get_open_positions()
            num_buy_positions = len(buy_positions)
            num_sell_positions = len(sell_positions)
            max_buy_positions = self.capital_ops.max_buy_positions
            max_sell_positions = self.capital_ops.max_sell_positions
            print(f"[INFO] 📊 Posiciones actuales: BUY={num_buy_positions}, SELL={num_sell_positions} (Máx BUY: {max_buy_positions}, Máx SELL: {max_sell_positions})")

            # Usar valores originales sin escalado
            values = {
                "Datetime": self.format_datetime(row["Datetime"]),
                "Close": row["Close"],
                "RSI": row["RSI"],
                "MACD": row["MACD"],
                "ATR": row["ATR"],
                "VolumeChange": row.get("VolumeChange", 0)
            }

            # Decidir acción según la estrategia
            decision = self.strategy.decide(
                current_price=row["Close"],
                balance=self.balance,
                features={
                    "RSI": row["RSI"],
                    "MACD": row["MACD"],
                    "ATR": row["ATR"],
                    "VolumeChange": row.get("VolumeChange", 0)
                },
                market_id="ETHUSD",
                historical_data=historical_data,
                data=data,
                open_positions=positions
            )

            # Registro de la decisión
            log_entry = {
                "datetime": values["Datetime"],
                "current_price": float(row["Close"]),
                "balance": float(self.balance),
                "decision": decision["action"],
                "reason_decide": decision.get("reason", "Sin razón proporcionada"),
                "reason": decision.get("reason", "Sin razón proporcionada"),
                "trend": trend,
                "values": values
            }
            self.log_process_data.append(log_entry)

            # Verificar el límite según el tipo de acción
            if decision["action"] == "BUY":
                if num_buy_positions >= max_buy_positions:
                    print(f"[INFO] 🚨 Límite de posiciones LONG alcanzado ({max_buy_positions}). No se abrirá una nueva posición BUY.")
                    log_entry["decision"] = "HOLD"
                    log_entry["reason"] = "Límite de posiciones BUY alcanzado"
                    return
                self.capital_ops.open_position(
                    market_id=decision["market_id"],
                    direction="BUY",
                    size=decision["size"],
                    stop_loss=decision.get("stop_loss"),
                    take_profit=decision.get("take_profit")
                )
            elif decision["action"] == "SELL":
                if num_sell_positions >= max_sell_positions:
                    print(f"[INFO] 🚨 Límite de posiciones SHORT alcanzado ({max_sell_positions}). No se abrirá una nueva posición SELL.")
                    log_entry["decision"] = "HOLD"
                    log_entry["reason"] = "Límite de posiciones SELL alcanzado"
                    return
                self.capital_ops.open_position(
                    market_id=decision["market_id"],
                    direction="SELL",
                    size=decision["size"],
                    stop_loss=decision.get("stop_loss"),
                    take_profit=decision.get("take_profit")
                )
            else:
                print("[INFO] ⏳ No se cumple ninguna condición para abrir una nueva posición.")

            print(f"[INFO] Log actualizado desde Process Data:")
            print(f"📈 TREND DETECTADO: {trend}")
            print(json.dumps(log_entry, ensure_ascii=False, indent=4))

        except Exception as e:
            print(f"[ERROR] ❌ Error en process_data: {e}")



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
        # Si es un objeto datetime o pd.Timestamp, formateamos directamente.
        if isinstance(timestamp, (pd.Timestamp, datetime)):
            return timestamp.strftime('%Y-%m-%d %H:%M:%S')
        # Si es un número (por ejemplo, epoch en milisegundos)
        elif isinstance(timestamp, (int, float)):
            return pd.to_datetime(timestamp, unit='ms').strftime('%Y-%m-%d %H:%M:%S')
        else:
            # Intentar convertir sin unidad, asumiendo que es una cadena legible
            try:
                return pd.to_datetime(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            except Exception as conv_e:
                print(f"[ERROR] No se pudo convertir el timestamp: {timestamp}. Error: {conv_e}")
                return None



    def print_log(self):
        """Imprime el log detallado de las operaciones, formateado con Rich."""
        console = Console()

        console.print("[bold cyan][INFO] 📋 Registro de operaciones detallado:[/bold cyan]")

        if not self.log_open_positions and not self.log_process_data:
            console.print("[bold yellow][INFO] 🚫 Los logs están vacíos. No hay datos para imprimir.[/bold yellow]")
            return

         
       # 📌 📑 Logs desde `process_data` en dos columnas (usando una tabla sin bordes)
        if self.log_process_data:
            console.print("\n[bold magenta][INFO] 📑 Registro desde process_data:[/bold magenta]")
            for entry in self.log_process_data:
                trend_detected = entry.get("trend", "No disponible")
                # Usamos .strip() para eliminar espacios extra
                reason = entry.get("reason", "[❌] Razón no proporcionada.").strip()

                # En lugar de shortxen, usamos fill para envolver el texto en múltiples líneas
                trend_detected = textwrap.shorten(str(trend_detected), width=900, placeholder="...")

                reason = textwrap.shorten(str(reason), width=100, placeholder="...")
                trend_text = entry.get("trend", {}).get("trend", "No disponible")

                signal_text = entry.get("trend", {}).get("signal", "N/A")


                # Panel izquierdo: Información General sin incluir la Razón
                info_text = textwrap.dedent(f"""
                    [bold green]📉 Precio actual:[/bold green] {entry.get('current_price', 'N/A'):.2f}
                    [bold green]💰 Balance disponible:[/bold green] {entry.get('balance', 'N/A'):.2f}
                    [bold red]🔥 Decisión tomada:[/bold red] {entry.get('decision', 'N/A')}
                    [bold cyan]📝 Razón de decide:[/bold cyan] {entry.get('reason_decide', 'Sin razón proporcionada')}

                    [bold blue]📈 Tendencia detectada:[/bold blue]
                    {trend_text}
                    [bold yellow]🔔 Señal:[/bold yellow] {signal_text}

                """)
                panel_info = Panel(info_text, title="Información General")

                # Panel derecho: Tabla de valores de la decisión (limitando filas)
                tabla_valores = Table(title="📊 Valores de la Decisión", show_header=True, header_style="bold cyan")
                tabla_valores.add_column("Indicador", justify="left", style="dim")
                tabla_valores.add_column("Valor", justify="right")
                for key, value in itertools.islice(entry.get("values", {}).items(), 5):
                    if key != "Datetime":
                        tabla_valores.add_row(key, str(value))
                panel_detalles = Panel(tabla_valores, title="Detalles de la Decisión", height=10)

                # Distribuir en dos columnas sin bordes
                table_layout = Table(show_header=False, box=None, padding=(0,1))
                table_layout.add_column(justify="left")
                table_layout.add_column(justify="left")
                table_layout.add_row(panel_info, panel_detalles)

                # Panel para la Razón, que se muestra debajo
                panel_razon = Panel(f"[bold cyan]📝 Razón de la señal :[/bold cyan]\n{reason}", title="Razón", height=5)

                # Agrupar la parte superior (info y detalles) y el panel de Razón
                group_content = Group(table_layout, panel_razon)
                console.print(Panel(group_content, title="[bold yellow]📥 process_data[/bold yellow]", expand=False))



        # 📌 📑 Logs desde `process_open_positions`
        if self.log_open_positions:
            console.print("\n[bold magenta][INFO] 📑 Registro desde process_open_positions:[/bold magenta]")
            for entry in self.log_open_positions:
                # Preparar datos para la cabecera
                fecha = entry.get("datetime", "N/A")
                precio = entry.get("current_price", "N/A")
                if isinstance(precio, (int, float)):
                    precio = f"{precio:.2f}"
                buy_count = sum(1 for pos in entry.get("positions", []) if pos["direction"].upper() == "BUY")
                sell_count = sum(1 for pos in entry.get("positions", []) if pos["direction"].upper() == "SELL")
                max_sell = self.capital_ops.max_sell_positions
                max_buy = self.capital_ops.max_buy_positions

                col_width = 50
                left_line1 = f"📅 Fecha: {fecha}"
                right_line1 = "📊 Posiciones abiertas:"
                line1 = f"{left_line1:<{col_width}}{right_line1:>{col_width}}"
                left_line2 = f"📉 Precio actual: {precio}"
                right_line2 = f"BUY={buy_count}, SELL={sell_count}"
                line2 = f"{left_line2:<{col_width}}{right_line2:>{col_width}}"
                left_line3 = ""
                right_line3 = f"(Máx permitido Sell: {max_sell}) (Máx permitido Buy: {max_buy})"
                line3 = f"{left_line3:<{col_width}}{right_line3:>{col_width}}"

                # Agregar mensaje de max profit actualizado de forma resumida:
                max_profit_msgs = []
                for pos in entry.get("positions", []):
                    # Si el reason contiene el texto de actualización de max profit, lo extraemos
                    if "Max Profit" in pos.get("reason", ""):
                        # Extraer el tipo (BUY o SELL) y el instrumento corto
                        direction = pos.get("direction", "N/A").upper()
                        # Suponiendo que el campo "instrument" es el nombre completo; se puede recortar
                        instrument = pos.get("instrument", "N/A")
                        short_instrument = instrument if len(instrument) <= 8 else instrument[:8]  # Ejemplo
                        max_profit_msgs.append(f"{direction} de {short_instrument}")
                if max_profit_msgs:
                    if len(max_profit_msgs) == len(entry.get("positions", [])):
                        max_profit_info = "Todos los max profit han sido actualizados."
                    else:
                        max_profit_info = "Max profit actualizado para: " + ", ".join(max_profit_msgs)
                else:
                    max_profit_info = "Sin actualización de max profit."
                
                header_text = f"{line1}\n{line2}\n{line3}\n[bold cyan]{max_profit_info}[/bold cyan]"
                header_panel = Panel(header_text, title="[bold green]Información General[/bold green]", expand=False)

                # Tabla principal de posiciones evaluadas
                table = Table(title="📊 Posiciones Evaluadas", show_header=True, header_style="bold cyan")
                table.add_column("Instrumento", justify="left")
                table.add_column("Dirección", justify="center")
                table.add_column("Tamaño", justify="center")
                table.add_column("P.A", justify="center")  # Precio Apertura renombrado a "P.A"
                table.add_column("Horas", justify="center")  # Formateado a entero + "hrs"
                table.add_column("/Ganancias", justify="right")
                table.add_column("Reason", justify="left", overflow="fold")
                for pos in entry.get("positions", []):
                    # Instrumento: recortar el nombre si es muy largo
                    instrument = pos.get("instrument", "N/A")
                    short_instrument = instrument if len(instrument) <= 8 else instrument[:8]
                    direction = pos.get("direction", "N/A")
                    size = str(pos.get("size", "N/A"))
                    price = str(pos.get("price", "N/A"))
                    # Horas abiertas: redondear a entero y añadir "hrs"
                    hours = pos.get("hours_open", "N/A")
                    if isinstance(hours, (int, float)):
                        hours = f"{int(hours)}hrs"
                    else:
                        hours = str(hours)
                    upl = pos.get("upl", "N/A")
                    upl_str = (
                        f"[bold green]{upl:.5f} ✅" if isinstance(upl, (int, float)) and upl >= 0 
                        else f"[bold red]{upl:.5f} ❌" if isinstance(upl, (int, float))
                        else "N/A"
                    )
                    reason = pos.get("reason", "Sin información")
                    table.add_row(
                        short_instrument,
                        direction,
                        size,
                        price,
                        hours,
                        upl_str,
                        reason
                    )

                # Opción 1: Todo en un único panel vertical
                group_content = Group(header_panel, table)
                console.print(Panel(group_content, title="[bold yellow]📤 process_open_positions[/bold yellow]", expand=False))

                # Otras opciones:
                # Opción 2: Mostrar la cabecera y luego dos columnas (tabla principal y tabla de detalles)
                # Por ejemplo, podrías generar otra tabla solo con DealId, Max Profit y Reason y usar Columns.
                # Opción 3: Usar Layout para dividir la pantalla en secciones superiores e inferiores.

        # 🔹 Limpiar los registros después de imprimir
        self.log_open_positions = []
        self.log_process_data = []


if __name__ == "__main__":
    try:
        print("[INFO] Inicializando operador de trading...")

        features = ["RSI", "MACD", "ATR", "VolumeChange", "Close", "Datetime"]

        script_dir = os.path.dirname(os.path.abspath(__file__))
        DATA_FILE = os.path.join(script_dir, "Reports", "ETHUSD_CapitalData.json")

        if not os.path.exists(DATA_FILE):
            print("[WARNING] ⚠️ Archivo de datos no encontrado. Ejecutando DataEth.py para generar los datos...")
            dataeth_path = os.path.join(script_dir, "DataEth.py")

            if os.path.exists(dataeth_path):
                process = subprocess.Popen(["python3", dataeth_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for line in process.stdout:
                    print(f"[DATAETH] {line.strip()}")
                process.wait()

                if process.returncode == 0:
                    print("[INFO] ✅ DataEth.py ejecutado con éxito. Archivo de datos generado.")
                else:
                    print(f"[ERROR] ❌ Error al ejecutar DataEth.py. Código de salida: {process.returncode}")
                    sys.exit(1)
            else:
                print("[ERROR] ❌ No se encontró el script DataEth.py.")
                sys.exit(1)

        if not os.path.exists(DATA_FILE):
            print("[ERROR] ❌ No se pudo generar el archivo de datos. Finalizando ejecución.")
            sys.exit(1)

        with open(DATA_FILE, 'r') as file:
            raw_data = json.load(file)

        data_frame = pd.DataFrame(raw_data.get('data', []))
        data_frame.columns = data_frame.columns.str.strip()

        if 'Datetime' in data_frame.columns:
            data_frame['Datetime'] = pd.to_datetime(data_frame['Datetime'], errors='coerce', utc=True)
            data_frame.set_index('Datetime', inplace=True)
            data_frame.sort_index(inplace=True)
        else:
            print("[WARNING] No se encontró la columna 'Datetime' en los datos.")

        print("[DEBUG] Tipo de índice:", type(data_frame.index))
        print("[DEBUG] Primeros 5 valores del índice:", data_frame.index[:5])

        capital_ops = CapitalOP()
        strategy = Strategia(capital_ops=capital_ops, threshold_buy=0, threshold_sell=2)

        trading_operator = TradingOperator(
            features=features,
            strategy=strategy,
            saldo_update_callback=None
        )

        print("[INFO] Inicializando la aplicación PyQt5...")
        app = QApplication(sys.argv)
        trading_operator.run_main_loop(data_frame)
        sys.exit(app.exec_())

    except Exception as e:
        print(f"[ERROR] Error en la ejecución principal: {e}")
