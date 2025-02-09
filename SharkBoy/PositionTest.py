import time
from EthSession import CapitalOP

def open_test_position():
    """
    Abre una posición de prueba para verificar la funcionalidad de apertura de posiciones.
    """
    try:
        # Configuración inicial
        market_id = "ETH-USD"  # Instrumento a negociar
        direction = "BUY"  # Dirección de la operación: "BUY" o "SELL"
        size = 0.01  # Tamaño de la posición
        stop_loss = 3000  # Nivel de Stop Loss (opcional)
        take_profit = 4000  # Nivel de Take Profit (opcional)

        # Instanciar y autenticar el operador
        capital_ops = CapitalOP()
        capital_ops.ensure_authenticated()
        capital_ops.set_account_id("260383560551191748")  # Configura tu account_id

        print("[INFO] Intentando abrir posición de prueba...")
        response = capital_ops.open_position(
            market_id=market_id,
            direction=direction,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit
        )

        # Validar y mostrar resultados
        if response.get("error"):
            print(f"[ERROR] Fallo al abrir posición: {response.get('message')}")
        else:
            print("[INFO] Posición abierta exitosamente:")
            print(response)
        
        # Esperar unos segundos antes de finalizar
        time.sleep(2)

    except Exception as e:
        print(f"[ERROR] Error al ejecutar el test de posición: {e}")


if __name__ == "__main__":
    try:
        open_test_position()
    except KeyboardInterrupt:
        print("\n[INFO] Prueba interrumpida manualmente.")
