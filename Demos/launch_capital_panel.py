#!/usr/bin/env python3
"""
launch_capital_panel.py - Lanzador del panel de gestión de capital
Abre una ventana gráfica flotante con información financiera en tiempo real
"""
import subprocess
import sys
import os

def main():
    """Lanza el panel de capital en un proceso separado."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    panel_script = os.path.join(script_dir, "CapitalPanel.py")

    if not os.path.exists(panel_script):
        print(f"[ERROR] ❌ No se encontró CapitalPanel.py en {script_dir}")
        sys.exit(1)

    print("[INFO] 🚀 Lanzando panel de Gestión de Capital...")
    print("[INFO] 💡 El panel se actualizará automáticamente cada segundo")
    print("[INFO] 💡 Cierra la ventana con el botón ❌ en la esquina superior derecha")
    print()

    try:
        # Lanzar en proceso separado
        subprocess.Popen([sys.executable, panel_script],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
        print("[INFO] ✅ Panel lanzado exitosamente")
        print("[INFO] 📊 Verifica que aparezca la ventana flotante")
    except Exception as e:
        print(f"[ERROR] ❌ No se pudo lanzar el panel: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
