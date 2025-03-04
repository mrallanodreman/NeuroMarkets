import asyncio
import curses
import time
import requests

# Configuración
BASE_URL = "https://api-capital.backend-capital.com"
SESSION_ENDPOINT = "/api/v1/session"
POSITIONS_ENDPOINT = "/api/v1/positions"  # Endpoint para consultar posiciones.
API_KEY = "dshUTxIDbHEtaOJS"
LOGIN = "odremanallanr@gmail.com"
PASSWORD = "Millo2025."

def authenticate():
    """
    Inicia sesión (POST /session) y retorna la respuesta JSON y los headers,
    que incluyen CST, X-SECURITY-TOKEN, currentAccountId y las cuentas disponibles.
    """
    url = BASE_URL + SESSION_ENDPOINT
    headers = {"X-CAP-API-KEY": API_KEY, "Content-Type": "application/json"}
    data = {"encryptedPassword": False, "identifier": LOGIN, "password": PASSWORD}
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json(), response.headers

def change_account(cst, security_token, account_id):
    """
    Cambia la cuenta activa mediante PUT /session con {"accountId": account_id}.
    Se espera que la respuesta actualice el token X-SECURITY-TOKEN.
    """
    url = BASE_URL + SESSION_ENDPOINT
    headers = {
        "X-CAP-API-KEY": API_KEY,
        "Content-Type": "application/json",
        "CST": cst,
        "X-SECURITY-TOKEN": security_token,
    }
    data = {"accountId": account_id}
    response = requests.put(url, headers=headers, json=data)
    response.raise_for_status()
    new_token = response.headers.get("X-SECURITY-TOKEN")
    if not new_token:
        print("No se recibió nuevo token; se usará el token actual.")
        new_token = security_token
    return new_token

def get_positions(cst, security_token):
    """
    Consulta el endpoint GET /positions y retorna la respuesta JSON.
    Se espera que la lista de posiciones esté en la clave "positions" (o "data").
    """
    url = BASE_URL + POSITIONS_ENDPOINT
    headers = {
        "X-CAP-API-KEY": API_KEY,
        "CST": cst,
        "X-SECURITY-TOKEN": security_token,
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

async def curses_main_async(stdscr, cst, security_token):
    # Configuración inicial de curses
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_RED, -1)    # Para valores negativos
    curses.init_pair(2, curses.COLOR_GREEN, -1)  # Para valores positivos

    mode = "monitor"  # Modo por defecto: Monitor
    update_interval = 5  # segundos para actualizar el polling de posiciones
    last_update = 0
    positions_list = []  # Lista de posiciones obtenidas
    # En modo evaluador se compararía con posiciones anteriores, pero por ahora usamos Monitor
    # (Se puede extender en el futuro)
    
    while True:
        # Chequear entrada del usuario sin bloquear
        try:
            key = stdscr.getch()
        except Exception:
            key = -1
        if key != -1:
            if key == ord('q'):
                break  # Salir
            elif key == ord('m'):
                mode = "monitor"
            elif key == ord('e'):
                mode = "evaluador"
        
        now = time.time()
        if now - last_update >= update_interval:
            try:
                data = await asyncio.to_thread(get_positions, cst, security_token)
                positions_list = data.get("positions") or data.get("data") or []
                last_update = now
            except Exception as e:
                positions_list = []
                stdscr.addstr(1, 0, f"Error al obtener posiciones: {e}")
        
        # Dibujar encabezado y menú
        stdscr.erase()
        header = f"Modo: {mode.upper()} | Presiona 'm' para Monitor, 'e' para Evaluador, 'q' para salir"
        stdscr.addstr(0, 0, header, curses.A_BOLD)
        
        # Dibujar encabezado de la tabla
        row = 2
        col = 0
        stdscr.addstr(row, col, f"{'Instrumento':20s} {'Dirección':10s} {'Tamaño':6s} {'Nivel':8s} {'UPL':>10s}", curses.A_BOLD)
        if mode == "evaluador":
            stdscr.addstr(row, 60, "Δ UPL", curses.A_BOLD)
        row += 1
        
        # En este ejemplo, solo implementamos el modo Monitor (sin comparación histórica)
        for pos in positions_list:
            market = pos.get("market", {})
            position = pos.get("position", {})
            instrument = market.get("instrumentName", "N/A")
            direction = position.get("direction", "N/A")
            size = str(position.get("size", ""))
            level = str(position.get("level", ""))
            try:
                upl_val = float(position.get("upl", 0))
            except Exception:
                upl_val = 0.0
            if upl_val < 0:
                upl_str = f"{upl_val:10.4f}"
                color = curses.color_pair(1)
            elif upl_val > 0:
                upl_str = f"{upl_val:10.4f}"
                color = curses.color_pair(2)
            else:
                upl_str = f"{upl_val:10.4f}"
                color = curses.A_NORMAL

            stdscr.addstr(row, col, f"{instrument:20s} {direction:10s} {size:6s} {level:8s} ")
            stdscr.addstr(upl_str, color)
            if mode == "evaluador":
                # Aquí se implementaría la comparación con el UPL previo (no implementado en este ejemplo)
                stdscr.addstr(row, 60, f"{'0.0000':8s}")
            row += 1
        
        stdscr.refresh()
        await asyncio.sleep(0.1)

def curses_main(stdscr, cst, security_token):
    asyncio.run(curses_main_async(stdscr, cst, security_token))

def main():
    # Autenticación y selección de cuenta (sin usar curses)
    try:
        auth_data, resp_headers = authenticate()
    except Exception as e:
        print(f"Error en la autenticación: {e}")
        return
    cst = resp_headers.get("CST")
    security_token = resp_headers.get("X-SECURITY-TOKEN")
    current_account = auth_data.get("currentAccountId")
    accounts = auth_data.get("accounts", [])
    print("Cuentas disponibles:")
    for idx, acc in enumerate(accounts, start=1):
        print(f"{idx}) {acc.get('accountName')}")
    try:
        choice = int(input("¿Qué cuenta quieres monitorear? (ingresa el número): "))
        if choice < 1 or choice > len(accounts):
            print("Opción no válida.")
            return
    except Exception as e:
        print(f"Entrada inválida: {e}")
        return
    selected_account = accounts[choice - 1]
    selected_account_id = selected_account.get("accountId")
    selected_account_name = selected_account.get("accountName")
    print(f"Has seleccionado: {selected_account_name}")
    if current_account != selected_account_id:
        try:
            security_token = change_account(cst, security_token, selected_account_id)
            print(f"Cuenta cambiada a {selected_account_name} correctamente.")
        except Exception as e:
            print(f"Error al cambiar de cuenta: {e}")
            return
    else:
        print("La cuenta actual ya es la seleccionada.")
    
    # Inicia la interfaz en curses
    curses.wrapper(curses_main, cst, security_token)

if __name__ == "__main__":
    main()







            # Calcular RSI
            historical_data['RSI'] = self.calculate_rsi(historical_data, period=5)
            rsi = historical_data['RSI'].iloc[-1]
            rsi_indicator = "green" if rsi < 30 else "red" if rsi > 70 else "white"








            # Obtener volumen en tiempo real
            real_time_volume = yf.Ticker(self.ticker).info.get("volume", None)
            if not real_time_volume:
                raise ValueError("Unable to fetch real-time volume.")









            # Calcular cambio porcentual del volumen usando promedio móvil reciente
            historical_volume = historical_data['Volume'].astype(float)
            recent_volume = historical_volume.rolling(window=3).mean().iloc[-1]  # Promedio de últimos 5 períodos
            volume_change = ((real_time_volume - recent_volume) / recent_volume) * 100

            # Clasificar el indicador de volumen
            if volume_change > 20:  # Incremento significativo en volumen
                volume_indicator = "green"
            elif volume_change < -20:  # Caída significativa en volumen
                volume_indicator = "red"
            else:
                volume_indicator = "white"


            # Log de indicadores
            self.log_indicators(histogram_value, rsi, volume_change)


            # Actualizar widgets visuales
            self.circle_widgets["rsi"].set_color(rsi_indicator)
            self.circle_widgets["macd"].set_color(macd_indicator)
            self.circle_widgets["volume"].set_color(volume_indicator)

            self.content_widgets["rsi_label"].setText(f"RSI: {rsi:.2f}")
            self.content_widgets["macd_label"].setText(f"MACD: {histogram_value:.2f}")
            self.content_widgets["volume_label"].setText(f"Volumen: {volume_change:.2f}%")

            # Imprimir señal informativa si hay un cambio fuerte
            if volume_indicator == "green" and histogram_value > 0 and rsi < 30:
                print(f"[BUY] Señal de compra: Volumen +{volume_change:.2f}%, MACD {histogram_value:.2f}, RSI {rsi:.2f}")
            elif volume_indicator == "red" and histogram_value < 0 and rsi > 70:
                print(f"[SELL] Señal de venta: Volumen {volume_change:.2f}%, MACD {histogram_value:.2f}, RSI {rsi:.2f}")

        except Exception as e:
            print(f"[ERROR] Failed to analyze {self.ticker}: {e}")


    def calculate_atr(self, data, period=5):
        """
        Calcula el Average True Range (ATR) para ajustar la escala del histograma.
        :param data: DataFrame con los datos históricos (debe incluir 'High', 'Low', 'Close').
        :param period: Período para el ATR.
        :return: Valor ATR calculado.
        """
        high_low = data['High'] - data['Low']
        high_close = (data['High'] - data['Close'].shift()).abs()
        low_close = (data['Low'] - data['Close'].shift()).abs()
        
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean().iloc[-1]  # ATR del último valor
        return atr


    def start_analysis(self):
        if self.running:
            print(f"[DEBUG] El análisis ya está corriendo para {self.ticker}.")
            return
        self.running = True
        self.thread = Thread(target=self.run_analysis)
        self.thread.daemon = True
        self.thread.start()


    def run_analysis(self):
        """Ejecuta el análisis de un ticker periódicamente."""
        while self.running:
            self.analyze_ticker()
            time.sleep((self.interval * 4000) / 1000)

    def stop_analysis(self):
        """Detiene el análisis periódico."""
        self.running = False
        if self.thread:
            self.thread.join()
