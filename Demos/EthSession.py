import os
import requests
import json
from datetime import datetime, timedelta
import time
from EthConfig import BASE_URL, API_KEY, LOGIN, PASSWORD
from colorama import Fore, Style

class CapitalOP:
    def __init__(self, ui=None):

        self.base_url = BASE_URL.rstrip('/')
        self.api_key = API_KEY
        self.login = LOGIN
        self.password = PASSWORD
        self.session_token = None
        self.x_security_token = None
        self.streaming_host = None
        self.account_id = os.environ.get("CAPITAL_ACCOUNT_ID", "")  # Configurar via variable de entorno CAPITAL_ACCOUNT_ID
        # 🔹 Límites de posiciones (por defecto, se pueden ajustar)
        self.max_buy_positions = 3   # Default (Francia: hasta 3 posiciones)
        self.max_sell_positions = 1  # Default
        # Tiempo para considerar una posición "legacy" (horas)
        self.legacy_hours = 24
        # UI para logs
        self.ui = ui
        # 🔹 Rate limiting y gestión de tokens
        self.token_expiry = None
        self.token_lifetime_minutes = 10  # Tokens válidos por 10 minutos
        self.last_auth_attempt = None
        self.min_auth_interval = 60  # Mínimo 60 segundos entre autenticaciones
        self.max_retries = 3
        self.retry_delay_base = 5  # Segundos base para backoff exponencial
        # 🔹 Caché de leverages por tipo de instrumento
        self._leverages = None
        # 🔹 Caché de tipo de instrumento por epic (market_id)
        self._market_types = {}
        # 🔹 NO autenticar aquí - dejar que cada bot configure su account_id primero


    def get_current_account(self):
        """Obtiene el `currentAccountId` de la sesión activa."""
        try:
            session_url = f"{self.base_url}/api/v1/session"
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token,
            }
            response = requests.get(session_url, headers=headers)

            if response.status_code == 200:
                session_data = response.json()
                msg = f"[DEBUG] 🔍 Respuesta `get_current_account()`: {json.dumps(session_data, indent=4)}"
                if self.ui:
                    self.ui.add_log(msg, style="dim")
                else:
                    print(msg)
                return session_data.get("accountId")  # 🔹 CORRECTO: La clave real en la respuesta es "accountId"

            else:
                msg = f"[ERROR] ❌ No se pudo obtener `currentAccountId`: {response.status_code} - {response.text}"
                if self.ui:
                    self.ui.add_log(msg, style="dim")
                else:
                    print(msg)
                return None
        except Exception as e:
            msg = f"[ERROR] ❌ Error en `get_current_account()`: {e}"
            if self.ui:
                self.ui.add_log(msg, style="dim")
            else:
                print(msg)
            return None

    def is_legacy_position(self, pos):
        """
        Determina si una posición es legacy según su fecha de creación.
        Acepta tanto un wrapper {'position': {...}} como un dict de posición directa.
        """
        try:
            if not pos:
                return False
            # Aceptar wrapper
            if isinstance(pos, dict) and 'position' in pos and isinstance(pos['position'], dict):
                p = pos['position']
            else:
                p = pos

            created = p.get('createdDate') or p.get('created') or p.get('open_time')
            if not created:
                return False

            # Parsear timestamp/ISO
            if isinstance(created, str):
                if 'T' in created:
                    # usar pandas si está disponible
                    import pandas as _pd
                    created_dt = _pd.to_datetime(created, utc=True)
                    created_ts = created_dt.timestamp()
                else:
                    created_ts = float(created)
            else:
                created_ts = float(created)

            import time
            hours_open = (time.time() - created_ts) / 3600
            return hours_open >= float(self.legacy_hours)
        except Exception:
            return False

    def ensure_correct_account(self):
        """Verifica que la cuenta activa sea la correcta y la cambia si es necesario."""
        current_account = self.get_current_account()

        # 🔹 Si no obtenemos `currentAccountId`, intentar UNA SOLA VEZ reautenticar
        if not current_account:
            msg = "[WARNING] ⚠️ No se pudo verificar la cuenta activa."
            if self.ui:
                self.ui.add_log(msg, style="dim")
            else:
                print(msg)
            # Solo intentar reautenticar si los tokens no son válidos
            if not self.tokens_are_valid():
                msg = "[INFO] 🔄 Intentando reautenticación única..."
                if self.ui:
                    self.ui.add_log(msg, style="dim")
                else:
                    print(msg)
                if self.authenticate():
                    current_account = self.get_current_account()  # 🔄 Un solo reintento

            if not current_account:
                msg = "[ERROR] ❌ No se pudo obtener `currentAccountId`. Continuando sin verificación de cuenta."
                if self.ui:
                    self.ui.add_log(msg, style="dim")
                else:
                    print(msg)
                return False

        msg = f"[DEBUG] 🧐 Verificando cuenta activa: API -> {current_account}, Configurada -> {self.account_id}"
        if self.ui:
            self.ui.add_log(msg, style="dim")
        else:
            print(msg)

        if current_account != self.account_id:
            msg = f"[INFO] 🔄 Cambiando de cuenta: {current_account} → {self.account_id}"
            if self.ui:
                self.ui.add_log(msg, style="dim")
            else:
                print(msg)
            if self.switch_account():  # 🔹 Verificar si el cambio de cuenta fue exitoso
                msg = f"[INFO] ✅ Cuenta cambiada correctamente a {self.account_id}."
                if self.ui:
                    self.ui.add_log(msg, style="dim")
                else:
                    print(msg)
                return True
            else:
                msg = f"[ERROR] ❌ No se pudo cambiar la cuenta a {self.account_id}."
                if self.ui:
                    self.ui.add_log(msg, style="dim")
                else:
                    print(msg)
                return False
        else:
            msg = f"[INFO] ✅ La cuenta activa ya es la correcta: {self.account_id}"
            if self.ui:
                self.ui.add_log(msg, style="dim")
            else:
                print(msg)
            return True

    def switch_account(self):
        """Cambia la cuenta activa usando `PUT /api/v1/session`."""
        try:
            switch_url = f"{self.base_url}/api/v1/session"
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token,
            }
            payload = {"accountId": self.account_id}
            response = requests.put(switch_url, headers=headers, json=payload)

            if response.status_code == 200:
                print(f"[INFO] ✅ Cuenta cambiada correctamente a {self.account_id}.")
                return True
            else:
                print(f"[ERROR] ❌ No se pudo cambiar la cuenta: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"[ERROR] ❌ Error en `switch_account()`: {e}")
            return False



    def set_account_id(self, account_id):
        """Configura el account_id que se utilizará en las consultas."""
        self.account_id = account_id
        print(f"[INFO] Account ID configurado: {self.account_id}")

    def tokens_are_valid(self):
        """Verifica si los tokens actuales están vigentes."""
        if not self.session_token or not self.x_security_token:
            return False

        if not self.token_expiry:
            return False

        return datetime.now() < self.token_expiry

    def can_attempt_auth(self):
        """Verifica si ha pasado suficiente tiempo desde el último intento de autenticación."""
        if not self.last_auth_attempt:
            return True

        elapsed = (datetime.now() - self.last_auth_attempt).total_seconds()
        return elapsed >= self.min_auth_interval


    def authenticate(self):
        """Autentica con la API y obtiene los tokens de sesión con rate limiting y backoff exponencial."""

        # 🔹 Verificar si los tokens actuales son válidos
        if self.tokens_are_valid():
            print("[INFO] ✅ Tokens vigentes. No es necesario reautenticar.")
            return True

        # 🔹 Verificar rate limiting
        if not self.can_attempt_auth():
            time_to_wait = self.min_auth_interval - (datetime.now() - self.last_auth_attempt).total_seconds()
            print(f"[WARNING] ⏳ Rate limiting activo. Espere {time_to_wait:.1f} segundos antes de reautenticar.")
            return False

        session_url = f"{self.base_url}/api/v1/session"
        payload = {"identifier": self.login, "password": self.password, "encryptedPassword": False}
        headers = {"Content-Type": "application/json", "X-CAP-API-KEY": self.api_key}

        # 🔹 Implementar backoff exponencial
        for attempt in range(self.max_retries):
            print(f"[INFO] 🔄 Iniciando autenticación (intento {attempt + 1}/{self.max_retries})...")

            self.last_auth_attempt = datetime.now()

            try:
                response = requests.post(session_url, json=payload, headers=headers, timeout=10)

                if response.status_code == 200:
                    session_data = response.json()
                    self.session_token = response.headers.get("CST")
                    self.x_security_token = response.headers.get("X-SECURITY-TOKEN")

                    if not self.session_token or not self.x_security_token:
                        print("[ERROR] ❌ No se pudieron obtener los tokens de sesión.")
                        return False

                    # 🔹 Guardar streamingHost desde la respuesta de sesión
                    self.streaming_host = session_data.get("streamingHost") or session_data.get("streamEndpoint") or ""

                    # 🔹 Configurar expiración de tokens
                    self.token_expiry = datetime.now() + timedelta(minutes=self.token_lifetime_minutes)
                    print(f"[INFO] ✅ Autenticación exitosa. Tokens válidos hasta {self.token_expiry.strftime('%H:%M:%S')}")
                    return session_data

                elif response.status_code == 429:
                    # 🔹 Error de rate limiting
                    retry_after = int(response.headers.get('Retry-After', self.retry_delay_base * (2 ** attempt)))
                    print(f"[WARNING] ⚠️ Rate limit (429). Esperando {retry_after} segundos...")
                    time.sleep(retry_after)
                    continue

                else:
                    print(f"[ERROR] ❌ Error en autenticación: {response.status_code} - {response.text}")

                    if attempt < self.max_retries - 1:
                        wait_time = self.retry_delay_base * (2 ** attempt)
                        print(f"[INFO] ⏳ Reintentando en {wait_time} segundos...")
                        time.sleep(wait_time)
                    else:
                        return False

            except requests.exceptions.RequestException as e:
                print(f"[ERROR] ❌ Error de conexión: {e}")
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay_base * (2 ** attempt)
                    print(f"[INFO] ⏳ Reintentando en {wait_time} segundos...")
                    time.sleep(wait_time)
                else:
                    return False

        print("[ERROR] ❌ Máximo de intentos de autenticación alcanzado.")
        return False

    def ensure_authenticated(self):
        """Valida que la autenticación sea válida antes de realizar operaciones."""
        if not self.tokens_are_valid():
            print("[INFO] ⚠️ Tokens expirados o inválidos. Reautenticando...")
            success = self.authenticate()
            if not success:
                print("[ERROR] ❌ No se pudo completar la autenticación.")
                return False
        return True

    def get_account_summary(self):
        """Obtiene todos los datos de la cuenta activa usando el account_id configurado."""
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
                accounts_data = response.json()
                if accounts_data is None:
                    raise ValueError(
                        f"Respuesta vacía (None) al consultar {account_url} "
                        f"[GET, status={response.status_code}, body={response.text!r}]"
                    )
                accounts_list = accounts_data.get("accounts", [])

                # Buscar la cuenta que coincide con el account_id configurado
                selected_account = None
                for account in accounts_list:
                    if account.get("accountId") == self.account_id:
                        selected_account = account
                        break
                if selected_account:
                    account_info = {
                        "accountId": selected_account.get("accountId"),
                        "accountName": selected_account.get("accountName"),
                        "accountType": selected_account.get("accountType"),
                        "currency": selected_account.get("currency"),
                        "symbol": selected_account.get("symbol"),
                        "balance": selected_account.get("balance", {}).get("balance", 0),
                        "available": selected_account.get("balance", {}).get("available", 0),
                        "deposit": selected_account.get("balance", {}).get("deposit", 0),
                        "profitLoss": selected_account.get("balance", {}).get("profitLoss", 0),
                        "preferred": selected_account.get("preferred", False),
                        "clientId": accounts_data.get("clientId", ""),
                        "timezoneOffset": accounts_data.get("timezoneOffset", 0),
                        "streamingHost": accounts_data.get("streamingHost") or self.streaming_host or "",
                        "leverages": self.get_account_leverages()
                    }
                    print(f"[INFO] ✅ Datos de la cuenta activa ({selected_account.get('accountName')}): {json.dumps(account_info, indent=4)}")
                    return account_info
                else:
                    print(f"[ERROR] ❌ No se encontró la cuenta con account_id {self.account_id} en la respuesta.")
                    return {}

            elif response.status_code == 401:
                print("[INFO] 🔄 Token inválido o expirado. Renovando autenticación...")
                self.authenticate()
                return self.get_account_summary()
            else:
                print(f"[ERROR] ❌ Error al obtener los datos de la cuenta: {response.status_code} - {response.text}")
                return {}

        except Exception as e:
            print(f"[ERROR] ❌ Fallo al obtener los datos de la cuenta: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def get_account_leverages(self):
        """
        Obtiene (y cachea) el diccionario completo de apalancamientos configurados
        para la cuenta activa, vía GET /api/v1/accounts/preferences.
        Formato: {instrument_type: {"current": x, "min": x, "max": x}, ...}
        """
        if self._leverages is not None:
            return self._leverages
        try:
            self.ensure_authenticated()
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token
            }
            pr = requests.get(f"{self.base_url}/api/v1/accounts/preferences", headers=headers, timeout=10)
            if pr.status_code == 200:
                self._leverages = pr.json().get("leverages", {})
                return self._leverages
            print(f"[WARNING] ⚠️ No se pudo obtener leverages de la cuenta: {pr.status_code}")
            return {}
        except Exception as e:
            print(f"[ERROR] ❌ Fallo al obtener leverages de la cuenta: {e}")
            return {}

    def get_leverage_for_market(self, market_id):
        """
        Obtiene el apalancamiento real de la cuenta para un mercado específico.
        Consulta /accounts/preferences y /markets/{epic} para determinar el tipo de instrumento.
        Resultado se cachea para evitar llamadas repetidas.
        """
        try:
            self.ensure_authenticated()
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token
            }

            # Obtener tipo de instrumento si no está en caché
            if market_id not in self._market_types:
                mr = requests.get(f"{self.base_url}/api/v1/markets/{market_id}", headers=headers, timeout=10)
                if mr.status_code == 200:
                    inst = mr.json().get("instrument", {})
                    self._market_types[market_id] = inst.get("type", "")
                else:
                    print(f"[WARNING] ⚠️ No se pudo obtener market type para {market_id}: {mr.status_code}")
                    return 20

            instrument_type = self._market_types[market_id]

            leverages = self.get_account_leverages()
            if not leverages:
                return 20

            leverage_info = leverages.get(instrument_type, {})
            leverage = leverage_info.get("current", 20)
            print(f"[INFO] 🔧 Leverage real para {market_id} ({instrument_type}): {leverage}x")
            return leverage

        except Exception as e:
            print(f"[ERROR] ❌ Fallo al obtener leverage: {e}")
            return 20

    def get_open_positions(self):
        """Obtiene las posiciones abiertas para la cuenta activa (self.account_id)."""
        try:
            self.ensure_authenticated()

            # 🔹 Endpoint correcto para obtener TODAS las posiciones
            positions_url = f"{self.base_url}/api/v1/positions"
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token
            }

            print(f"[DEBUG] 📤 Solicitando posiciones abiertas para la cuenta: {self.account_id}")
            response = requests.get(positions_url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                print(f"[DEBUG] 📥 Respuesta completa del API de posiciones:\n{json.dumps(data, indent=4)}")

                all_positions = data.get("positions", [])

                # 🔹 FILTRAR explícitamente por accountId para evitar mezcla de cuentas
                positions = []
                for pos in all_positions:
                    pos_data = pos.get("position", {})
                    # Intentamos sacar accountId del objeto 'position', si no existe, probamos en la raíz
                    # Y si sigue sin existir, usamos 'UNKNOWN'
                    pos_acc_id_val = pos_data.get("accountId")
                    if pos_acc_id_val is None:
                         pos_acc_id_val = pos.get("accountId")

                    pos_acc_id = str(pos_acc_id_val) if pos_acc_id_val is not None else "UNKNOWN"
                    target_acc_id = str(self.account_id)

                    # CORRECCIÓN DE EMERGENCIA:
                    # Si la API no devuelve accountId (devuelve 'UNKNOWN'), pero el usuario ya está autenticado en la sesión correcta,
                    # asumimos que la posición pertenece a esta cuenta.
                    if pos_acc_id == "UNKNOWN":
                        print(f"[WARNING] ⚠️ La posición {pos_data.get('dealId')} no trajo 'accountId'. Asumiendo pertenencia por contexto de sesión.")
                        positions.append(pos)
                    elif pos_acc_id == target_acc_id:
                        positions.append(pos)
                    else:
                        print(f"[DEBUG] ⚠️ Ignorando posición {pos_data.get('dealId')} - AccountID: {pos_acc_id} != {target_acc_id}")

               # positions = [
               #     pos for pos in all_positions
               #     if str(pos.get("position", {}).get("accountId")) == str(self.account_id)
               # ]

                print(f"[DEBUG] 🔍 Total posiciones API: {len(all_positions)}, filtradas para cuenta {self.account_id}: {len(positions)}")

                if not positions and not all_positions: # Si no hay nada en absoluto
                    print(f"[INFO] ❌ No hay posiciones abiertas.")
                    return {"BUY": [], "SELL": []}

                # ✅ Clasificar posiciones en BUY y SELL
                buy_positions = [
                    pos for pos in positions if pos["position"]["direction"].upper() == "BUY"
                ]
                sell_positions = [
                    pos for pos in positions if pos["position"]["direction"].upper() == "SELL"
                ]

                print(f"[INFO] ✅ Posiciones abiertas para {self.account_id} - BUY: {len(buy_positions)}, SELL: {len(sell_positions)}")
                return {"BUY": buy_positions, "SELL": sell_positions}

            elif response.status_code == 401:
                print("[ERROR] ❌ Token inválido o expirado. Intentando reautenticación...")
                self.authenticate()
                return self.get_open_positions()  # 🔄 Reintentar después de autenticar

            else:
                print(f"[ERROR] ❌ Error al obtener posiciones abiertas: {response.status_code} - {response.text}")
                return {"BUY": [], "SELL": []}

        except Exception as e:
            print(f"[ERROR] ❌ Fallo en `get_open_positions()`: {e}")
            return {"BUY": [], "SELL": []}



    def close_position(self, deal_id):
        """
        Cierra una posición específica por dealId.

        Returns:
            dict: Resultado del cierre con información de éxito/fallo
            None: Si hubo un error crítico
        """
        if not deal_id:
            print("[ERROR] ❌ No se puede cerrar posición sin dealId válido")
            return None

        try:
            self.ensure_authenticated()

            close_url = f"{self.base_url}/api/v1/positions/{deal_id}"
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token
            }

            print(f"[INFO] 🔄 Intentando cerrar posición {deal_id}...")
            response = requests.delete(close_url, headers=headers, timeout=10)

            if response.status_code == 200:
                print(f"[SUCCESS] ✅ Posición {deal_id} cerrada exitosamente")
                return response.json() if response.text else {"status": "success", "dealId": deal_id}

            elif response.status_code == 404:
                print(f"[WARNING] ⚠️ Posición {deal_id} no encontrada (puede que ya esté cerrada)")
                return {"status": "not_found", "dealId": deal_id}

            elif response.status_code == 401 or response.status_code == 403:
                print(f"[ERROR] ❌ Error de autenticación al cerrar {deal_id}: {response.status_code}")
                return None

            else:
                print(f"[ERROR] ❌ Error al cerrar la posición {deal_id}: {response.status_code} - {response.text}")
                return None

        except requests.exceptions.Timeout:
            print(f"[ERROR] ⏱️ Timeout al intentar cerrar la posición {deal_id}")
            return None

        except requests.exceptions.ConnectionError as e:
            print(f"[ERROR] 🔌 Error de conexión al cerrar {deal_id}: {e}")
            return None

        except Exception as e:
            print(f"[ERROR] ❌ Fallo inesperado al cerrar la posición {deal_id}: {type(e).__name__} - {e}")
            import traceback
            traceback.print_exc()
            return None

    def open_position(self, market_id, direction, size, level=None, stop_loss=None, take_profit=None, guaranteed_stop=True):
        """
        Abre una nueva posición en la cuenta activa después de asegurarse de que sea la correcta.

        :param market_id: El ID del mercado (ej: "BTC-USD").
        :param direction: "BUY" o "SELL".
        :param size: Tamaño de la posición.
        :param level: Precio de entrada (para órdenes limitadas, opcional).
        :param stop_loss: Nivel de Stop Loss (opcional).
        :param take_profit: Nivel de Take Profit (opcional).
        :param guaranteed_stop: Si True (por defecto), el Stop Loss será GARANTIZADO
            (no sufre slippage). Capital.com SOLO acepta `guaranteedStop` cuando se
            envía un `stop_loss`; si no hay `stop_loss`, este flag se ignora para
            evitar el rechazo de la orden. El stop garantizado suele tener un
            recargo (premium) por parte del broker.
        :return: Respuesta de la API como JSON o detalles de error.
        """
        try:
            self.ensure_authenticated()

            # 🔹 Obtener la cuenta activa desde la API antes de abrir una posición
            active_account = self.get_current_account()

            if not active_account:
                print("[ERROR] ❌ No se pudo obtener `currentAccountId` de la API.")
                return {"error": True, "message": "No se pudo verificar la cuenta activa antes de abrir la posición."}

            if active_account != self.account_id:
                print(f"[WARNING] ⚠️ La cuenta activa ({active_account}) no es la esperada ({self.account_id}). Cambiando de cuenta...")

                if not self.switch_account():
                    return {"error": True, "message": "No se pudo cambiar la cuenta activa antes de abrir la posición."}
                else:
                    print(f"[INFO] ✅ Cuenta cambiada correctamente a {self.account_id}.")

            print(f"[INFO] ✅ La cuenta activa es la correcta: {self.account_id}")

            # 🔹 Validar balance antes de abrir posición
            account_info = self.get_account_summary()
            if account_info and 'balance' in account_info:
                balance = account_info['balance']

                # 🚨 ESTIMACIÓN ACTUALIZADA PARA PREVENIR LIQUIDACIONES
                # Precios conservadores actualizados Febrero 2026
                estimated_price = 2100  # ETH precio estimado conservador
                if "ETH" in market_id.upper():
                    estimated_price = 2100  # 🔹 Actualizado de 3500 a 2100
                elif "BTC" in market_id.upper():
                    estimated_price = 95000  # 🔹 Actualizado de 88000 a 95000

                # Obtener apalancamiento real de la cuenta para este mercado
                leverage = self.get_leverage_for_market(market_id)
                estimated_margin = (size * estimated_price) / leverage

                print(f"[INFO] 💰 Balance disponible: ${balance:.2f}")
                print(f"[INFO] 📊 Margen estimado requerido: ${estimated_margin:.2f}")

                if estimated_margin > balance * 0.95:  # Usar 95% como límite de seguridad
                    print(f"[ERROR] ❌ Balance insuficiente para abrir posición")
                    print(f"[ERROR]    Requerido: ${estimated_margin:.2f} | Disponible: ${balance:.2f}")
                    return {
                        "error": True,
                        "message": f"Balance insuficiente. Requerido: ${estimated_margin:.2f}, Disponible: ${balance:.2f}"
                    }

            # 🔹 Obtener posiciones abiertas para validar límites
            # 🔹 Obtener posiciones abiertas para validar límites
            positions = self.get_open_positions()
            buy_positions = positions.get("BUY", [])
            sell_positions = positions.get("SELL", [])

            # Filtrar legacy aquí para que los límites reflejen lo que EthBoy considera activo
            buy_active = [p for p in buy_positions if not self.is_legacy_position(p)]
            sell_active = [p for p in sell_positions if not self.is_legacy_position(p)]
            total_positions = len(buy_active) + len(sell_active)

            if direction.upper() == "SELL" and len(sell_active) >= self.max_sell_positions:
                print(f"[WARNING] ⚠️  Límite de posiciones SELL alcanzado ({len(sell_active)}/{self.max_sell_positions}). No se abrirá una nueva posición.")
                return {"error": True, "message": f"Límite de posiciones SELL alcanzado ({len(sell_active)}/{self.max_sell_positions})."}
            elif direction.upper() == "BUY" and len(buy_active) >= self.max_buy_positions:
                print(f"[WARNING] ⚠️  Límite de posiciones BUY alcanzado ({len(buy_active)}/{self.max_buy_positions}). No se abrirá una nueva posición.")
                return {"error": True, "message": f"Límite de posiciones BUY alcanzado ({len(buy_active)}/{self.max_buy_positions})."}

            print(f"[INFO] 📊 Posiciones antes de abrir: {total_positions} total (BUY={len(buy_positions)}, SELL={len(sell_positions)})")

            # 🔹 Construcción del payload para apertura de posición
            open_url = f"{self.base_url}/api/v1/positions"
            payload = {
                "epic": market_id,
                "direction": direction.upper(),
                "size": size,
                "type": "MARKET",
            }

            if stop_loss is not None:
                payload["stopLevel"] = stop_loss
                # El stop garantizado SOLO es válido junto a un stopLevel.
                if guaranteed_stop:
                    payload["guaranteedStop"] = True
                    print("[INFO] 🛡️ Stop Loss GARANTIZADO activado (sin slippage, puede tener recargo).")
            elif guaranteed_stop:
                print("[WARNING] ⚠️ guaranteed_stop=True ignorado: requiere un stop_loss. Abriendo sin stop garantizado.")
            if take_profit is not None:
                payload["limitLevel"] = take_profit
            if level is not None:
                payload["level"] = level  # Solo si se trata de una orden limitada

            print(f"[INFO] 📤 Enviando solicitud para abrir posición en la cuenta {self.account_id}...")

            # 🔹 Enviar solicitud de apertura de posición
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token
            }

            response = requests.post(open_url, json=payload, headers=headers)

            if response.status_code == 200:
                position_data = response.json()
                deal_reference = position_data.get("dealReference")
                print(f"[INFO] ✅ Posición abierta exitosamente: {position_data}")

                if not deal_reference:
                    print("[ERROR] ❌ El dealReference no fue proporcionado en la respuesta.")
                    return {"error": True, "message": "El dealReference no está presente en la respuesta."}

                # 🔹 Confirmar la posición
                print("[INFO] 🔄 Confirmando posición...")
                confirm_url = f"{self.base_url}/api/v1/confirms/{deal_reference}"
                confirm_response = requests.get(confirm_url, headers=headers)

                if confirm_response.status_code == 200:
                    confirmation = confirm_response.json()

                    # 🔹 Verificar si la orden fue RECHAZADA
                    deal_status = confirmation.get('dealStatus', '')
                    reject_reason = confirmation.get('rejectReason', '')

                    if deal_status == 'REJECTED':
                        print(f"[ERROR] ❌ Posición RECHAZADA por Capital.com")
                        print(f"[ERROR]    Razón: {reject_reason}")

                        if reject_reason == 'RISK_CHECK':
                            print(f"[ERROR]    💡 Sugerencia: Balance insuficiente o límite de riesgo alcanzado")
                            print(f"[ERROR]    💡 Reduzca el tamaño de la posición o deposite más fondos")

                        return {
                            "error": True,
                            "message": f"Orden rechazada: {reject_reason}",
                            "confirmation": confirmation
                        }

                    print(f"[INFO] ✅ Confirmación de posición exitosa: {confirmation}")
                    return confirmation
                else:
                    print(f"[ERROR] ❌ Fallo en la confirmación de la posición: {confirm_response.status_code} - {confirm_response.text}")
                    return {
                        "error": True,
                        "status_code": confirm_response.status_code,
                        "message": confirm_response.text
                    }

            else:
                print(f"[ERROR] ❌ Fallo al abrir posición: {response.status_code} - {response.text}")
                return {
                    "error": True,
                    "status_code": response.status_code,
                    "message": response.text
                }

        except Exception as e:
            print(f"[ERROR] ❌ Error en `open_position()`: {e}")
            return {
                "error": True,
                "message": str(e)
            }


    def get_last_price(self, epic):
        """Obtiene el último precio (mid) de un mercado dado su EPIC vía /api/v1/markets/{epic}."""
        try:
            self.ensure_authenticated()
            url = f"{self.base_url}/api/v1/markets/{epic}"
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token
            }
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                snapshot = data.get("snapshot", {})
                bid = float(snapshot.get("bid", 0))
                offer = float(snapshot.get("offer", 0))
                if bid > 0 and offer > 0:
                    return (bid + offer) / 2
            return None
        except Exception:
            return None

    def get_1m_candles(self, epic, limit=40):
        """Obtiene velas de 1 minuto desde Binance API pública (sin auth).
        Retorna lista de dicts con keys: timestamp, Open, High, Low, Close, Volume."""
        try:
            import pandas as pd
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': 'ETHUSDT',
                'interval': '1m',
                'limit': limit
            }
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if not data:
                    return []
                candles = []
                for k in data:
                    candles.append({
                        'timestamp': pd.Timestamp(k[0], unit='ms', tz='UTC'),
                        'Open': float(k[1]),
                        'High': float(k[2]),
                        'Low': float(k[3]),
                        'Close': float(k[4]),
                        'Volume': float(k[5])
                    })
                return candles
            return []
        except Exception as e:
            print(f"[WARNING] Error obteniendo 1m candles desde Binance: {e}")
            return []

    def get_available_accounts(self):
        """Obtiene la lista de cuentas (accountId y accountName) disponibles para el usuario autenticado."""
        try:
            self.ensure_authenticated()
            url = f"{self.base_url}/api/v1/accounts"
            headers = {
                "Content-Type": "application/json",
                "X-CAP-API-KEY": self.api_key,
                "CST": self.session_token,
                "X-SECURITY-TOKEN": self.x_security_token
            }
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                accounts_data = response.json() or {}
                return [
                    {"accountId": acc.get("accountId"), "accountName": acc.get("accountName")}
                    for acc in accounts_data.get("accounts", [])
                ]
            print(f"[ERROR] ❌ No se pudo obtener la lista de cuentas: {response.status_code} - {response.text}")
            return []
        except Exception as e:
            print(f"[ERROR] ❌ Fallo al obtener la lista de cuentas: {e}")
            return []

    def print_account_details(self):
        """Imprime un resumen detallado de la cuenta, incluyendo el saldo y las operaciones abiertas con formato mejorado."""
        try:
            if not self.account_id:
                raise ValueError("[ERROR] No se ha configurado el account_id.")

            account_summary = self.get_account_summary()
            positions = self.get_open_positions()  # 🔹 Accede correctamente a las posiciones
            buy_positions = positions.get("BUY", [])
            sell_positions = positions.get("SELL", [])

            print("\n[INFO] Resumen de la Cuenta:")
            if account_summary and isinstance(account_summary, dict):
                # Usar directamente account_summary porque ya contiene la información filtrada
                print(f"  - Account ID: {account_summary.get('accountId')}")
                print(f"    Nombre: {account_summary.get('accountName')}")
                print(f"    Saldo: {account_summary.get('balance')} {account_summary.get('currency')}")
                print(f"    Disponible: {account_summary.get('available')}")
                leverages = account_summary.get('leverages') or {}
                if leverages:
                    print(f"    Apalancamiento:")
                    for instrument_type, lev in leverages.items():
                        print(f"      - {instrument_type}: {lev.get('current', 'N/A')}x (min {lev.get('min', 'N/A')}x, max {lev.get('max', 'N/A')}x)")
                print()

            print(f"\n[INFO] Posiciones Abiertas para la cuenta: {self.account_id}")

            all_positions = buy_positions + sell_positions
            if all_positions:
                # 🔹 Muestra el conteo total de posiciones en BUY y SELL
                print(f"[INFO] 📊 Total de posiciones abiertas: {len(all_positions)}")
                print(f"       📈 BUY: {len(buy_positions)} | 📉 SELL: {len(sell_positions)}")

                # Define un separador (por ejemplo, una línea de guiones) para usarlo en el log
                separator = "-" * 40
                for index, pos in enumerate(all_positions, start=1):
                    position_details = pos.get("position", {})
                    market_details = pos.get("market", {})

                    # Datos básicos
                    instrument_name = market_details.get('instrumentName', 'N/A')
                    direction = position_details.get('direction', 'N/A')
                    size = position_details.get('size', 'N/A')
                    price = position_details.get('level', 'N/A')
                    profit_loss = position_details.get('upl', 0)
                    currency = position_details.get('currency', 'N/A')

                    # Determinar color para ganancia/pérdida
                    profit_color = Fore.GREEN if profit_loss >= 0 else Fore.RED
                    direction_emoji = "📈" if direction.upper() == "BUY" else "📉"
                    position_number = f"{index}\ufe0f️⃣"  # Número con emoji

                    # Imprimir separador y datos de la posición
                    print(f"\n{Style.BRIGHT}{Fore.BLACK}{separator}{Style.RESET_ALL}")
                    print(f"{position_number} - 🎯 Instrumento: {instrument_name}")
                    print(f"    Dirección: {direction_emoji} {direction}")
                    print(f"    Tamaño: {size}")
                    print(f"    Precio de apertura: {price}")
                    print(f"    Ganancia/Pérdida: {profit_color}{profit_loss} {currency}{Style.RESET_ALL}")

                # Fin de la impresión
                print(f"\n{Style.BRIGHT}{Fore.BLACK}{'=' * 40}{Style.RESET_ALL}")

            else:
                print("  No hay posiciones abiertas.")

        except Exception as e:
            print(f"{Fore.RED}[ERROR] Fallo al imprimir detalles de la cuenta: {e}{Style.RESET_ALL}")



if __name__ == "__main__":
    try:
        capital_ops = CapitalOP()
        # Autenticación inicial
        capital_ops.ensure_authenticated()

        # Verificamos que el account_id configurado corresponda a una cuenta real disponible.
        available_accounts = capital_ops.get_available_accounts()
        available_ids = [acc["accountId"] for acc in available_accounts]

        if not capital_ops.account_id or capital_ops.account_id not in available_ids:
            print("[ERROR] El account_id no está configurado o no es válido para esta cuenta.")
            if available_accounts:
                print("[INFO] Cuentas disponibles:")
                for acc in available_accounts:
                    print(f"  - {acc['accountId']} ({acc['accountName']})")
            else:
                print("[WARNING] No se pudieron recuperar las cuentas disponibles.")
            exit(1)

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
