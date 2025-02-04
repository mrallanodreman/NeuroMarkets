import requests
import json
from datetime import datetime
import time
from EthConfig import BASE_URL, API_KEY, LOGIN, PASSWORD
from colorama import Fore, Style

class CapitalOP:
    def __init__(self):

        self.base_url = BASE_URL
        self.api_key = API_KEY
        self.login = LOGIN
        self.password = PASSWORD
        self.session_token = None
        self.x_security_token = None
        self.account_id = None  # Atributo para almacenar el account_id actual
        # 🔹 Límites de posiciones para cada bot
        self.max_buy_positions = 1   # Límite para EthOperator
        self.max_sell_positions = 1  # Límite para SharkBoy

    def set_account_id(self, account_id):
        """Configura el account_id que se utilizará en las consultas."""
        self.account_id = account_id
        print(f"[INFO] Account ID configurado: {self.account_id}")


    def authenticate(self):
        """Autentica con la API de Capital y obtiene los datos necesarios."""
        try:
            session_url = f"{self.base_url}/api/v1/session"
            payload = {
                "identifier": self.login,
                "password": self.password,
                "encryptedPassword": False
            }
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key
            }

            print("[DEBUG] Enviando solicitud de autenticación...")
            response = requests.post(session_url, json=payload, headers=headers)

            if response.status_code == 200:
                session_data = response.json()
                print(f"[DEBUG] Respuesta completa:\n{json.dumps(session_data, indent=4)}")

                # Obtener tokens de los encabezados
                self.session_token = response.headers.get("CST")
                self.x_security_token = response.headers.get("X-SECURITY-TOKEN")

                if not self.session_token or not self.x_security_token:
                    print("[ERROR] Tokens no obtenidos durante la autenticación.")
                    return

                print("[INFO] Autenticación exitosa.")
            else:
                print(f"[ERROR] Error al autenticar: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"[ERROR] Fallo en la autenticación: {e}")


    def ensure_authenticated(self):
        """Valida que la autenticación sea válida antes de realizar operaciones."""
        if not self.session_token or not self.x_security_token:
            print("[INFO] Autenticación inválida. Reautenticando...")
            self.authenticate()
        else:
            print("[INFO] Autenticación válida. No se necesita reautenticación.")

    def get_account_summary(self):
        """Obtiene un resumen de la cuenta, incluido el saldo disponible."""
        try:
            self.ensure_authenticated()

            account_url = f"{self.base_url}/api/v1/accounts"
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token
            }

            response = requests.get(account_url, headers=headers)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401:  # Código para "Unauthorized"
                print("[INFO] Token inválido o expirado. Renovando...")
                self.authenticate()
                return self.get_account_summary()
            else:
                print(f"[ERROR] Error al obtener resumen de cuenta: {response.text}")
                return {}
        except Exception as e:
            print(f"[ERROR] Fallo al obtener resumen de cuenta: {e}")
            return {}

    def get_open_positions(self):
        """Obtiene las posiciones abiertas para la cuenta activa."""
        try:
            self.ensure_authenticated()

            # Endpoint para obtener posiciones abiertas
            positions_url = f"{self.base_url}/api/v1/positions"
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token
            }

            print(f"[DEBUG] Solicitando posiciones abiertas para la cuenta activa.")
            response = requests.get(positions_url, headers=headers)

            print("[DEBUG] URL de consulta:", response.url)
            print("[DEBUG] Respuesta completa:", response.text)

            if response.status_code == 200:
                data = response.json()
                positions = data.get("positions", [])

                # Separar posiciones por tipo de operación
                buy_positions = [pos for pos in positions if pos["position"]["direction"] == "BUY"]
                sell_positions = [pos for pos in positions if pos["position"]["direction"] == "SELL"]

                print(f"[INFO] Posiciones abiertas - BUY: {len(buy_positions)}, SELL: {len(sell_positions)}")
                return buy_positions, sell_positions  # ✅ Ahora sí retorna correctamente

            print(f"[ERROR] Error al obtener posiciones abiertas: {response.status_code} - {response.text}")
            return [], []  # ✅ Manejo de error

        except Exception as e:
            print(f"[ERROR] Fallo al obtener posiciones abiertas: {e}")
            return [], []



    def close_position(self, deal_id):
        """Cierra una posición específica por dealId."""
        try:
            self.ensure_authenticated()

            close_url = f"{self.base_url}/api/v1/positions/{deal_id}"
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token
            }

            response = requests.delete(close_url, headers=headers)
            if response.status_code == 200:
                print(f"[INFO] Posición cerrada exitosamente. dealId: {deal_id}")
                return response.json()  # Podrías retornar el JSON resultante
            else:
                print(f"[ERROR] Error al cerrar la posición {deal_id}: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"[ERROR] Fallo al cerrar la posición {deal_id}: {e}")
            return None

    def open_position(self, market_id, direction, size, level=None, stop_loss=None, take_profit=None):
        """
        Opens a new position in the specified market and confirms the position.

        :param market_id: The market ID (e.g., "BTC-USD").
        :param direction: "BUY" or "SELL".
        :param size: Position size.
        :param level: Price level for the order (optional).
        :param stop_loss: Stop loss price level (optional).
        :param take_profit: Take profit price level (optional).
        :return: API response as JSON or error details.
        """
        try:
            self.ensure_authenticated()

             # Obtener posiciones abiertas actuales
            buy_positions, sell_positions = self.get_open_positions()
        
            # Verificar si se excede el límite
            if direction.upper() == "BUY" and len(buy_positions) >= self.max_buy_positions:
                print(f"[WARNING] Límite de posiciones BUY alcanzado ({self.max_buy_positions}). No se abrirá una nueva posición.")
                return None
            
            if direction.upper() == "SELL" and len(sell_positions) >= self.max_sell_positions:
                print(f"[WARNING] Límite de posiciones SELL alcanzado ({self.max_sell_positions}). No se abrirá una nueva posición.")
                return None

            open_url = f"{self.base_url}/api/v1/positions"
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token
            }

            # Build the payload dynamically
            payload = {
                "epic": market_id,  # Cambiar la clave de "marketId" a "epic"
                "direction": direction.upper(),  # Ensure capitalization for API compatibility
                "size": size,
                "type": "MARKET",  # Assuming "MARKET" type for real-time execution
            }

            if stop_loss is not None:
                payload["stopLevel"] = stop_loss
            if take_profit is not None:
                payload["limitLevel"] = take_profit
            if level is not None:
                payload["level"] = level

            print("[INFO] Enviando solicitud para abrir posición...")
            # Open position
            response = requests.post(open_url, json=payload, headers=headers)
            if response.status_code == 200:
                position_data = response.json()
                deal_reference = position_data.get("dealReference")
                print(f"[INFO] Posición abierta exitosamente: {position_data}")
                
                if deal_reference:
                    print("[INFO] Confirmando posición...")
                    # Confirm position
                    confirm_url = f"{self.base_url}/api/v1/confirms/{deal_reference}"
                    confirm_response = requests.get(confirm_url, headers=headers)
                    if confirm_response.status_code == 200:
                        confirmation = confirm_response.json()
                        print(f"[INFO] Confirmación de posición exitosa: {confirmation}")
                        return confirmation
                    else:
                        print(f"[ERROR] Fallo en la confirmación de la posición: {confirm_response.status_code} - {confirm_response.text}")
                        return {
                            "error": True,
                            "status_code": confirm_response.status_code,
                            "message": confirm_response.text
                        }
                else:
                    print("[ERROR] El dealReference no fue proporcionado en la respuesta.")
                    return {
                        "error": True,
                        "message": "El dealReference no está presente en la respuesta."
                    }
            else:
                print(f"[ERROR] Fallo al abrir posición: {response.status_code} - {response.text}")
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "message": response.text
                }
        except Exception as e:
            print(f"[ERROR] Error en open_position: {e}")
            return {
                "error": True,
                "message": str(e)
            }

    def print_account_details(self):
        """Imprime un resumen detallado de la cuenta, incluyendo el saldo y las operaciones abiertas con formato mejorado."""
        try:
            if not self.account_id:
                raise ValueError("[ERROR] No se ha configurado el account_id.")

            account_summary = self.get_account_summary()
            buy_positions, sell_positions = self.get_open_positions()  # ⚠️ Desempaquetar correctamente

            print("\n[INFO] Resumen de la Cuenta:")
            if account_summary and isinstance(account_summary, dict):
                for account in account_summary.get("accounts", []):
                    print(f"  - Account ID: {account['accountId']}")
                    print(f"    Nombre: {account['accountName']}")
                    print(f"    Saldo: {account['balance']['balance']} {account['currency']}")
                    print(f"    Disponible: {account['balance']['available']}\n")

            print(f"\n[INFO] Posiciones Abiertas para la cuenta: {self.account_id}")

            all_positions = buy_positions + sell_positions
            if all_positions:
                for index, pos in enumerate(all_positions, start=1):
                    position_details = pos.get("position", {})
                    market_details = pos.get("market", {})

                    # 🏷️ Datos básicos
                    instrument_name = market_details.get('instrumentName', 'N/A')
                    direction = position_details.get('direction', 'N/A')
                    size = position_details.get('size', 'N/A')
                    price = position_details.get('level', 'N/A')
                    profit_loss = position_details.get('upl', 0)
                    currency = position_details.get('currency', 'N/A')

                    # 📊 Determinar color de ganancia/pérdida
                    profit_color = Fore.GREEN if profit_loss >= 0 else Fore.RED
                    direction_emoji = "📈" if direction == "BUY" else "📉"
                    position_number = f"{index}\ufe0f️⃣"  # Número con emoji (1️⃣, 2️⃣, 3️⃣...)

                    # 🏳️ Separador con fondo blanco
                    print(f"\n{Style.BRIGHT}{Fore.BLACK}{"=" * 40}{Style.RESET_ALL}")

                    # 📝 Imprimir datos de la posición
                    print(f"{position_number} - 🎯 Instrumento: {instrument_name}")
                    print(f"    Dirección: {direction_emoji} {direction}")
                    print(f"    Tamaño: {size}")
                    print(f"    Precio de apertura: {price}")
                    print(f"    Ganancia/Pérdida: {profit_color}{profit_loss} {currency}{Style.RESET_ALL}")

                # 🎭 Fin de la impresión
                print(f"\n{Style.BRIGHT}{Fore.BLACK}{"=" * 40}{Style.RESET_ALL}")

            else:
                print("  No hay posiciones abiertas.")
        except Exception as e:
            print(f"{Fore.RED}[ERROR] Fallo al imprimir detalles de la cuenta: {e}{Style.RESET_ALL}")







if __name__ == "__main__":
    try:
        capital_ops = CapitalOP()

        # Autenticación inicial

        capital_ops.ensure_authenticated()
        capital_ops.set_account_id("260383560551191748")  # Cambia al ID de cuenta deseado

        print("[INFO] El programa está corriendo. Presiona Ctrl+C para detenerlo.")
        while True:
            try:
                # Obtener detalles de la cuenta específica
                capital_ops.print_account_details()
                time.sleep(60)
            except Exception as e:
                print(f"[ERROR] Error en el ciclo principal: {e}")
                time.sleep(5)

    except KeyboardInterrupt:
        print("\n[INFO] Interrupción manual detectada. Programa finalizado.")
