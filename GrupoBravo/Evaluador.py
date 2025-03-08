import asyncio
import curses
import time
import requests
import json
from datetime import datetime, timezone
from EthConfig import BASE_URL, API_KEY, LOGIN, PASSWORD

# ------------------- Configuración de la API ------------------- #
SESSION_ENDPOINT = "/api/v1/session"
POSITIONS_ENDPOINT = "/api/v1/positions"

def authenticate():
    url = BASE_URL + SESSION_ENDPOINT
    headers = {"X-CAP-API-KEY": API_KEY, "Content-Type": "application/json"}
    data = {"encryptedPassword": False, "identifier": LOGIN, "password": PASSWORD}
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json(), response.headers

def log_closed_position(details):
    try:
        with open("closed_positions.txt", "a", encoding="utf-8") as file:
            timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            entry = (f"{timestamp} | DealID: {details['dealId']} | EPIC: {details['epic']} | "
                     f"Direction: {details['direction']} | Size: {details['size']} | "
                     f"Reason: {details['reason']}\n")
            file.write(entry)
    except Exception as e:
        print(f"[ERROR] No se pudo registrar cierre en archivo: {e}")

def log_debug_message(panel, messages, message=None):
    """
    Registra un mensaje de debug en el panel.
    Se limita a 10 mensajes.
    """
    if message:
        messages.append(message)
        if len(messages) > 10:
            messages.pop(0)
    panel.erase()
    panel.box()
    safe_addstr(panel, 0, 2, "DEBUG LOG", curses.A_BOLD)
    row = 1
    for msg in messages:
        safe_addstr(panel, row, 2, msg[:panel.getmaxyx()[1]-4])
        row += 1
    panel.refresh()

def change_account(cst, security_token, account_id):
    url = f"{BASE_URL.rstrip('/')}/api/v1/session"
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
        new_token = security_token
    return new_token

def get_positions(cst, security_token):
    url = BASE_URL + POSITIONS_ENDPOINT
    headers = {
        "X-CAP-API-KEY": API_KEY,
        "CST": cst,
        "X-SECURITY-TOKEN": security_token,
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

# ------------------- Funciones auxiliares para curses ------------------- #
def safe_addstr(win, y, x, text, attr=curses.A_NORMAL):
    max_y, max_x = win.getmaxyx()
    if y < max_y and x < max_x:
        try:
            win.addnstr(y, x, text, max_x - x, attr)
        except curses.error:
            pass

def calc_open_time(created_str):
    try:
        if created_str.endswith("Z"):
            created_str = created_str.replace("Z", "+00:00")
        dt_created = datetime.fromisoformat(created_str)
        if dt_created.tzinfo is None:
            dt_created = dt_created.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt_created
        total_hours = delta.days * 24 + delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        return f"{total_hours}h{minutes:02d}"
    except Exception:
        return "N/A"

def draw_positions_table(panel, positions_list, mode, previous_upl):
    panel.erase()
    panel.box()
    header = f"POSICIONES - Modo: {mode.upper()} (Presiona 'm','e','q')"
    safe_addstr(panel, 0, 2, header, curses.A_BOLD)
    
    columns = [
        ("Instrumento", 15),
        ("Epic", 8),
        ("Dirección", 10),
        ("Tamaño", 6),
        ("Nivel", 8),
        ("UPL", 10),
        ("GStop", 6),
        ("Abierto", 12)
    ]
    
    row = 2
    col = 2
    header_items = [f"{title:<{width}}" for title, width in columns]
    header_line = " │ ".join(header_items)
    safe_addstr(panel, row, col, header_line, curses.A_BOLD)
    row += 1
    sep_line = "─" * len(header_line)
    safe_addstr(panel, row, col, sep_line, curses.A_DIM)
    row += 1

    even_attr = curses.color_pair(3)
    odd_attr = curses.A_NORMAL

    for pos in positions_list:
        attr_row = even_attr if positions_list.index(pos) % 2 == 0 else odd_attr
        market = pos.get("market", {})
        position = pos.get("position", {})
        instrument = market.get("instrumentName", "N/A")[:20]
        epic = str(market.get("epic", "N/A"))[:8]
        direction = str(position.get("direction", "N/A"))[:10]
        size = str(position.get("size", ""))
        level = str(position.get("level", ""))
        try:
            upl_val = float(position.get("upl", 0))
        except Exception:
            upl_val = 0.0
        upl_str = f"{upl_val:10.4f}"
        gstop = "Si" if position.get("guaranteedStop", False) else "No"
        created_str = position.get("createdDateUTC") or position.get("createdDate")
        open_time = calc_open_time(created_str) if created_str else "N/A"
        
        items = [
            f"{instrument:<20}",
            f"{epic:<8}",
            f"{direction:<10}",
            f"{size:<6}",
            f"{level:<8}",
            f"{upl_str:<10}",
            f"{gstop:<6}",
            f"{open_time:<12}"
        ]
        
        line = " │ ".join(items)
        safe_addstr(panel, row, col, line, attr_row)
        row += 1

    panel.refresh()

def get_hours_open(created_str):
    try:
        if created_str.endswith("Z"):
            created_str = created_str.replace("Z", "+00:00")
        dt_created = datetime.fromisoformat(created_str)
        if dt_created.tzinfo is None:
            dt_created = dt_created.replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        delta = now_utc - dt_created
        return delta.total_seconds() / 3600.0
    except Exception:
        return 0.0

def draw_decisions_table(panel, positions_list, width, mode):
    needed_height = 3 + len(positions_list) + 1
    try:
        panel.resize(needed_height, width)
    except Exception:
        pass

    panel.erase()
    panel.box()
    
    header = "DECISIONES"
    header_line = f"{'DealID':<12} │ {'Max Profit':>12} │ {'Mensaje':<{width - 30}}"
    
    safe_addstr(panel, 0, 2, header, curses.A_BOLD)
    safe_addstr(panel, 1, 2, header_line, curses.A_BOLD)
    
    sep = "─" * (width - 4)
    safe_addstr(panel, 2, 2, sep, curses.A_DIM)
    
    row = 3
    for pos in positions_list:
        # Para la visualización se muestra el dealId truncado, pero en la lista se debe tener el dealId completo
        full_deal_id = pos.get("position", {}).get("dealId", "N/A")
        deal_id_trunc = full_deal_id[-4:] if full_deal_id != "N/A" else "N/A"
        mensaje = pos.get("reason", "")
        max_profit = pos.get("max_profit", 0.0)
        line = f"{deal_id_trunc:<12} │ {max_profit:>12.2f} │ {mensaje:<{width - 30}}"
        safe_addstr(panel, row, 2, line)
        row += 1

    panel.refresh()

def evaluate_positions(positions, features, profittracker, debug_callback=None):
    to_close = []
    now_time = datetime.now(timezone.utc)
    min_threshold = 0.03
    closure_pct = 0.90

    for position in positions:
        # Obtener el dealId completo (sin truncar) para usar en la solicitud de cierre
        full_deal_id = position.get("position", {}).get("dealId", "N/A")
        # Para visualización se puede truncar, pero para el cierre se usará el full_deal_id
        deal_id_trunc = full_deal_id[-4:] if full_deal_id != "N/A" else "N/A"
        created_str = position.get("position", {}).get("createdDateUTC") or position.get("position", {}).get("createdDate")
        hours_open = None
        if created_str:
            try:
                if created_str.endswith("Z"):
                    created_str = created_str.replace("Z", "+00:00")
                dt_created = datetime.fromisoformat(created_str)
                if dt_created.tzinfo is None:
                    dt_created = dt_created.replace(tzinfo=timezone.utc)
                delta = now_time - dt_created
                hours_open = delta.total_seconds() / 3600
            except Exception:
                hours_open = None
        position["hours_open"] = hours_open if hours_open is not None else "N/A"
        position["reason"] = ""
        try:
            upl = float(position.get("position", {}).get("upl", 0))
        except Exception:
            upl = 0.0
        upl_percent = upl * 100.0

        if debug_callback:
            debug_callback(f"DEBUG: Evaluando posición {deal_id_trunc} -> upl: {upl}")

        if upl < 0:
            position["reason"] += f"UPL negativo ({upl_percent:.2f}%). Sin acción."
            continue

        if full_deal_id not in profittracker:
            profittracker[full_deal_id] = {"max_profit": 0}
        prev_max = profittracker[full_deal_id].get("max_profit", 0)

        if upl > prev_max:
            profittracker[full_deal_id]["max_profit"] = upl
            position["max_profit"] = upl
            position["reason"] += f"Max Profit actualizado a {upl_percent:.2f}%. "
        else:
            position["max_profit"] = prev_max
            position["reason"] += f"Sin actualización en el Max Profit (permanece en {prev_max*100:.2f}%). "

        if position["max_profit"] >= 0.10 and upl < position["max_profit"]:
            position["reason"] += f"Cerrar recomendado por alta ganancia: retracción de {position['max_profit']*100:.2f}% a {upl_percent:.2f}%."
            to_close.append({
                "action": "Close",
                "dealId": full_deal_id,
                "size": position.get("size"),
                "reason": position["reason"],
                "direction": position.get("position", {}).get("direction", "N/A"),
                "epic": position.get("market", {}).get("epic", "N/A")
            })
        elif upl > min_threshold and upl < position["max_profit"] * closure_pct:
            rsi = features.get("RSI", 0)
            macd = features.get("MACD", 0)
            vol = features.get("VolumeChange", 0)
            if rsi > 50 and macd > 0 and vol > 0:
                position["reason"] += f"Mantener recomendado (UPL: {upl_percent:.2f}%)."
            else:
                position["reason"] += f"Cerrar recomendado (UPL: {upl_percent:.2f}% < 90% del max profit)."
                to_close.append({
                    "action": "Close",
                    "dealId": full_deal_id,
                    "size": position.get("size"),
                    "reason": position["reason"],
                    "direction": position.get("position", {}).get("direction", "N/A"),
                    "epic": position.get("market", {}).get("epic", "N/A")
                })
        else:
            position["reason"] += f"No es necesario cerrar (UPL: {upl_percent:.2f}% es adecuado). "

        if isinstance(hours_open, (int, float)) and hours_open >= 24 and upl >= 0.5:
            position["reason"] += f"Cierre forzado: Abierta {hours_open:.1f}h, UPL {upl_percent:.2f}%."
            to_close.append({
                "action": "Close",
                "dealId": full_deal_id,
                "size": position.get("size"),
                "reason": position["reason"],
                "direction": position.get("position", {}).get("direction", "N/A"),
                "epic": position.get("market", {}).get("epic", "N/A")
            })

    try:
        with open("profittracker.json", "w") as file:
            json.dump(profittracker, file, indent=4)
        if debug_callback:
            debug_callback("[INFO] profittracker.json actualizado y guardado correctamente.")
    except Exception as e:
        if debug_callback:
            debug_callback(f"[ERROR] No se pudo guardar profittracker.json: {e}")

    return to_close

def close_position(action, cst, security_token):
    """
    Cierra una posición específica usando DELETE /api/v1/positions/{dealId}.
    Se espera que 'action' contenga al menos:
      - "dealId": identificador completo de la posición.
    Los tokens (cst y security_token) se usan directamente.
    """
    deal_id = action.get("dealId")
    try:
        url = f"{BASE_URL.rstrip('/')}/api/v1/positions/{deal_id}"
        headers = {
            "Content-Type": "application/json",
            "X-CAP-API-KEY": API_KEY,
            "CST": cst,
            "X-SECURITY-TOKEN": security_token,
        }
        response = requests.delete(url, headers=headers)
        response.raise_for_status()

        # Registrar posición cerrada exitosamente
        log_closed_position(action)

        return response.json() if response.text else {"message": "Posición cerrada sin contenido."}
    except Exception as e:
        print(f"[ERROR] Fallo al cerrar la posición {deal_id}: {e}")
        return None

# ------------------- Función principal con curses ------------------- #
async def curses_main_async(stdscr, cst, security_token):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_RED, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLUE)

    mode = "monitor"
    evaluator_message = ""
    update_interval = 5
    last_update = 0
    positions_list = []
    previous_upl = {}

    try:
        with open("profittracker.json", "r") as file:
            profittracker = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        profittracker = {}

    debug_messages = []

    while True:
        max_y, max_x = stdscr.getmaxyx()
        header_lines = 3
        debug_panel_height = min(30, max_y // 4)
        available_height = max_y - header_lines - debug_panel_height
        pos_height = available_height // 2
        dec_height = available_height - pos_height

        pos_panel = stdscr.subwin(pos_height, max_x - 2, header_lines, 1)
        dec_panel = stdscr.subwin(dec_height, max_x - 2, header_lines + pos_height, 1)
        # Se quita el "- 1" para que el debug log comience justo después de las decisiones
        debug_panel = stdscr.subwin(debug_panel_height, max_x - 2, header_lines + pos_height + dec_height, 1)


        try:
            key = stdscr.getch()
        except Exception:
            key = -1

        if key != -1:
            if key == ord('q'):
                break
            elif key == ord('m'):
                mode = "monitor"
                evaluator_message = "Modo MONITOR: Evaluación desactivada"
                log_debug_message(debug_panel, debug_messages, evaluator_message)
            elif key == ord('e'):
                mode = "evaluador"
                evaluator_message = "Modo EVALUADOR: Evaluación activada"
                for pos in positions_list:
                    pos["reason"] = ""
                log_debug_message(debug_panel, debug_messages, evaluator_message)

        now = time.time()
        if now - last_update >= update_interval:
            try:
                data = await asyncio.to_thread(get_positions, cst, security_token)
                positions_list = data.get("positions") or data.get("data") or []
                for pos in positions_list:
                    pos_details = pos.get("position", {})
                    created_str = pos_details.get("createdDateUTC") or pos_details.get("createdDate")
                    hours_open_value = 0.0
                    if created_str:
                        hours_open_value = get_hours_open(created_str)
                    pos["hours_open"] = hours_open_value
                    pos["dealId"] = pos_details.get("dealId")
                    pos["direction"] = pos_details.get("direction")
                    pos["size"] = pos_details.get("size")
                    pos["upl"] = pos_details.get("upl")
                last_update = now
            except Exception as e:
                positions_list = []
                log_debug_message(debug_panel, debug_messages, f"Error al obtener posiciones: {e}")

            if mode == "evaluador":
                features = {"RSI": 55, "MACD": 1, "VolumeChange": 1}
                actions = evaluate_positions(
                    positions_list,
                    features,
                    profittracker,
                    lambda msg: log_debug_message(debug_panel, debug_messages, msg)
                )

                if actions:
                    evaluator_message = f"Modo EVALUADOR activado | Posiciones a cerrar: {len(actions)}"
                    log_debug_message(debug_panel, debug_messages, evaluator_message)

                    for action in actions:
                        result = await asyncio.to_thread(close_position, action, cst, security_token)
                        if result:
                            log_closed_position(action)  # Registro exitoso del cierre
                            log_debug_message(debug_panel, debug_messages, f"✅ Posición {action['dealId']} cerrada correctamente.")
                        else:
                            log_debug_message(debug_panel, debug_messages, f"[ERROR] Al cerrar posición {action['dealId']}")
                else:
                    evaluator_message = "Modo EVALUADOR activado | Ninguna posición cumple criterios para cierre."
                    log_debug_message(debug_panel, debug_messages, evaluator_message)

        draw_positions_table(pos_panel, positions_list, mode, previous_upl)
        draw_decisions_table(dec_panel, positions_list, max_x - 2, mode)
        log_debug_message(debug_panel, debug_messages)
        stdscr.refresh()
        await asyncio.sleep(0.1)

def curses_main(stdscr, cst, security_token):
    asyncio.run(curses_main_async(stdscr, cst, security_token))

def main():
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
    
    curses.wrapper(curses_main, cst, security_token)

if __name__ == "__main__":
    main()
