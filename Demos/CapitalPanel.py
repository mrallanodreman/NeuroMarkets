"""
CapitalPanel.py - Panel gráfico flotante para Gestión de Capital
Muestra información financiera en tiempo real del bot de trading
"""
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QProgressBar, QApplication)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPalette, QColor
import json
import os
from datetime import datetime
import sys


class CapitalPanel(QWidget):
    """Panel gráfico que muestra información de gestión de capital."""

    def __init__(self, data_file="capital_state.json"):
        super().__init__()
        self.data_file = data_file
        self.init_ui()

        # Timer para actualizar cada segundo
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(1000)  # Actualizar cada 1 segundo

    def init_ui(self):
        """Inicializa la interfaz gráfica."""
        self.setWindowTitle("💰 Gestión de Capital - EthBoy")
        self.setGeometry(100, 100, 500, 400)

        # Configurar ventana siempre al frente
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)

        # Layout principal
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(10)

        # ═══════════════════════════════════════════════════════════
        # TÍTULO
        # ═══════════════════════════════════════════════════════════
        title_frame = QFrame()
        title_frame.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
                border: 2px solid #4CAF50;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        title_layout = QHBoxLayout()

        self.title_label = QLabel("💰 GESTIÓN DE CAPITAL")
        self.title_label.setStyleSheet("""
            QLabel {
                color: #4CAF50;
                font-size: 18px;
                font-weight: bold;
            }
        """)
        title_layout.addWidget(self.title_label)

        # Botón cerrar
        close_btn = QLabel("❌")
        close_btn.setStyleSheet("QLabel { color: #ff4444; font-size: 16px; cursor: pointer; }")
        close_btn.mousePressEvent = lambda e: self.close()
        title_layout.addWidget(close_btn)

        title_frame.setLayout(title_layout)
        main_layout.addWidget(title_frame)

        # ═══════════════════════════════════════════════════════════
        # INFORMACIÓN DE CAPITAL
        # ═══════════════════════════════════════════════════════════
        info_frame = QFrame()
        info_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border: 1px solid #444;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        info_layout = QVBoxLayout()

        # Balance Total
        self.balance_total_label = self.create_info_label("💰 Balance Total:", "$0.00")
        info_layout.addWidget(self.balance_total_label)

        # Disponible
        self.balance_available_label = self.create_info_label("✅ Disponible:", "$0.00")
        info_layout.addWidget(self.balance_available_label)

        # Capital Libre (con barra de progreso)
        capital_layout = QHBoxLayout()
        capital_text = QLabel("📊 Capital Libre:")
        capital_text.setStyleSheet("QLabel { color: #aaa; font-size: 14px; }")
        capital_layout.addWidget(capital_text)

        self.capital_pct_label = QLabel("0.0%")
        self.capital_pct_label.setStyleSheet("QLabel { color: #4CAF50; font-size: 14px; font-weight: bold; }")
        capital_layout.addWidget(self.capital_pct_label)
        capital_layout.addStretch()
        info_layout.addLayout(capital_layout)

        # Barra de progreso para capital libre
        self.capital_progress = QProgressBar()
        self.capital_progress.setRange(0, 100)
        self.capital_progress.setValue(0)
        self.capital_progress.setTextVisible(False)
        self.capital_progress.setFixedHeight(25)
        self.update_progress_style(0)
        info_layout.addWidget(self.capital_progress)

        # Comprometido
        self.committed_label = self.create_info_label("🔒 Comprometido:", "$0.00")
        info_layout.addWidget(self.committed_label)

        # Separador
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("QFrame { color: #444; }")
        info_layout.addWidget(separator)

        # Depósito
        self.deposit_label = self.create_info_label("💵 Depósito:", "$0.00")
        info_layout.addWidget(self.deposit_label)

        # P&L
        self.pnl_label = self.create_info_label("📊 P&L:", "$0.00")
        info_layout.addWidget(self.pnl_label)

        info_frame.setLayout(info_layout)
        main_layout.addWidget(info_frame)

        # ═══════════════════════════════════════════════════════════
        # ESTADO DE PROTECCIÓN
        # ═══════════════════════════════════════════════════════════
        self.status_frame = QFrame()
        self.status_frame.setStyleSheet("""
            QFrame {
                background-color: #1e4d1e;
                border: 2px solid #4CAF50;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        status_layout = QHBoxLayout()

        self.status_label = QLabel("✅ Operativo Normal")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #4CAF50;
                font-size: 14px;
                font-weight: bold;
            }
        """)
        status_layout.addWidget(self.status_label, alignment=Qt.AlignCenter)

        self.status_frame.setLayout(status_layout)
        main_layout.addWidget(self.status_frame)

        # ═══════════════════════════════════════════════════════════
        # POSICIONES
        # ═══════════════════════════════════════════════════════════
        pos_frame = QFrame()
        pos_frame.setStyleSheet("""
            QFrame {
                background-color: #2d2d2d;
                border: 1px solid #444;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        pos_layout = QVBoxLayout()

        self.positions_label = self.create_info_label("📊 Posiciones:", "0/2 (BUY: 0, SELL: 0)")
        pos_layout.addWidget(self.positions_label)

        pos_frame.setLayout(pos_layout)
        main_layout.addWidget(pos_frame)

        # ═══════════════════════════════════════════════════════════
        # ÚLTIMA ACTUALIZACIÓN
        # ═══════════════════════════════════════════════════════════
        self.last_update_label = QLabel("⏱️ Última actualización: -")
        self.last_update_label.setStyleSheet("QLabel { color: #666; font-size: 11px; }")
        main_layout.addWidget(self.last_update_label, alignment=Qt.AlignCenter)

        main_layout.addStretch()

        # Aplicar layout
        self.setLayout(main_layout)

        # Estilo general de la ventana
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: white;
            }
        """)

    def create_info_label(self, title, value):
        """Crea un label de información con título y valor."""
        container = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        title_label = QLabel(title)
        title_label.setStyleSheet("QLabel { color: #aaa; font-size: 14px; }")
        layout.addWidget(title_label)

        value_label = QLabel(value)
        value_label.setStyleSheet("QLabel { color: white; font-size: 14px; font-weight: bold; }")
        value_label.setObjectName("value")
        layout.addWidget(value_label)

        layout.addStretch()
        container.setLayout(layout)
        return container

    def update_progress_style(self, value):
        """Actualiza el estilo de la barra de progreso según el valor."""
        if value >= 70:
            color = "#4CAF50"  # Verde
        elif value >= 50:
            color = "#FFC107"  # Amarillo
        elif value >= 30:
            color = "#FF9800"  # Naranja
        else:
            color = "#F44336"  # Rojo

        self.capital_progress.setStyleSheet(f"""
            QProgressBar {{
                border: 2px solid #444;
                border-radius: 5px;
                background-color: #1e1e1e;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
        """)

    def update_data(self):
        """Lee el archivo JSON y actualiza la interfaz."""
        try:
            if not os.path.exists(self.data_file):
                return

            with open(self.data_file, 'r') as f:
                data = json.load(f)

            # Actualizar valores
            balance_total = data.get('balance_total', 0)
            balance_available = data.get('balance_available', 0)
            balance_deposit = data.get('balance_deposit', 0)
            balance_pnl = data.get('balance_pnl', 0)
            capital_pct = data.get('capital_pct', 0)

            # Balance total
            self.update_label_value(self.balance_total_label, f"${balance_total:.2f}")

            # Disponible
            self.update_label_value(self.balance_available_label, f"${balance_available:.2f}")

            # Capital libre
            self.capital_pct_label.setText(f"{capital_pct:.1f}%")
            self.capital_progress.setValue(int(capital_pct))
            self.update_progress_style(int(capital_pct))

            # Color del porcentaje según nivel
            if capital_pct >= 70:
                color = "#4CAF50"
            elif capital_pct >= 50:
                color = "#FFC107"
            elif capital_pct >= 30:
                color = "#FF9800"
            else:
                color = "#F44336"
            self.capital_pct_label.setStyleSheet(f"QLabel {{ color: {color}; font-size: 14px; font-weight: bold; }}")

            # Comprometido
            committed = balance_total - balance_available
            self.update_label_value(self.committed_label, f"${committed:.2f}")

            # Depósito
            self.update_label_value(self.deposit_label, f"${balance_deposit:.2f}")

            # P&L
            pnl_emoji = "📈" if balance_pnl >= 0 else "📉"
            pnl_color = "#4CAF50" if balance_pnl >= 0 else "#F44336"
            pnl_value = f"{pnl_emoji} ${balance_pnl:+.2f}"
            self.update_label_value(self.pnl_label, pnl_value, pnl_color)

            # Estado de protección
            if capital_pct < 50:
                self.status_label.setText("🛡️ PROTECCIÓN ACTIVA")
                self.status_label.setStyleSheet("QLabel { color: #F44336; font-size: 14px; font-weight: bold; }")
                self.status_frame.setStyleSheet("""
                    QFrame {
                        background-color: #4d1e1e;
                        border: 2px solid #F44336;
                        border-radius: 8px;
                        padding: 10px;
                    }
                """)
            else:
                self.status_label.setText("✅ Operativo Normal")
                self.status_label.setStyleSheet("QLabel { color: #4CAF50; font-size: 14px; font-weight: bold; }")
                self.status_frame.setStyleSheet("""
                    QFrame {
                        background-color: #1e4d1e;
                        border: 2px solid #4CAF50;
                        border-radius: 8px;
                        padding: 10px;
                    }
                """)

            # Posiciones
            num_buy = data.get('num_buy', 0)
            num_sell = data.get('num_sell', 0)
            total_positions = num_buy + num_sell
            max_positions = data.get('max_positions', 2)
            positions_text = f"{total_positions}/{max_positions} (BUY: {num_buy}, SELL: {num_sell})"
            self.update_label_value(self.positions_label, positions_text)

            # Última actualización
            now = datetime.now().strftime("%H:%M:%S")
            self.last_update_label.setText(f"⏱️ Última actualización: {now}")

        except Exception as e:
            print(f"[ERROR] No se pudo actualizar panel de capital: {e}")

    def update_label_value(self, container, value, color="white"):
        """Actualiza el valor de un label dentro de su container."""
        value_label = container.findChild(QLabel, "value")
        if value_label:
            value_label.setText(value)
            value_label.setStyleSheet(f"QLabel {{ color: {color}; font-size: 14px; font-weight: bold; }}")


def main():
    """Función principal para lanzar el panel."""
    app = QApplication(sys.argv)
    panel = CapitalPanel()
    panel.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
