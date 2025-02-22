import sys
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QListWidget, QHBoxLayout
from PyQt6.QtCore import QTimer
from EthSession import CapitalOP

class TradingDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trading Dashboard")
        self.setGeometry(100, 100, 600, 400)
        
        self.capital_ops = CapitalOP()
        self.capital_ops.authenticate()
        self.capital_ops.set_account_id("260383560551191748")
        
        layout = QVBoxLayout()
        
        # Sección de Cuenta
        self.account_label = QLabel("Cuenta: Cargando...")
        self.balance_label = QLabel("Saldo Disponible: Cargando...")
        layout.addWidget(self.account_label)
        layout.addWidget(self.balance_label)
        
        # Sección de Posiciones Abiertas
        self.positions_label = QLabel("Posiciones Abiertas:")
        layout.addWidget(self.positions_label)
        self.positions_list = QListWidget()
        layout.addWidget(self.positions_list)
        
        # Sección de Watchlist
        self.watchlist_label = QLabel("Watchlist:")
        layout.addWidget(self.watchlist_label)
        self.watchlist = QListWidget()
        layout.addWidget(self.watchlist)
        
        # Sección de Control de Bots
        self.bot_status = QLabel("Bots de Trading: OFF")
        layout.addWidget(self.bot_status)
        
        bot_layout = QHBoxLayout()
        self.start_bot_button = QPushButton("Iniciar Bots")
        self.start_bot_button.clicked.connect(self.start_bots)
        bot_layout.addWidget(self.start_bot_button)
        
        self.stop_bot_button = QPushButton("Detener Bots")
        self.stop_bot_button.clicked.connect(self.stop_bots)
        bot_layout.addWidget(self.stop_bot_button)
        layout.addLayout(bot_layout)
        
        self.setLayout(layout)
        
        # Temporizador para actualizar los datos cada 60 segundos
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_dashboard)
        self.timer.start(60000)  # 60 segundos
        
        self.update_dashboard()
    
    def update_dashboard(self):
        account_info = self.capital_ops.get_account_summary()
        
        if account_info and "accounts" in account_info:
            account = account_info["accounts"][0]
            self.account_label.setText(f"Cuenta: {account['accountName']} ({account['currency']})")
            self.balance_label.setText(f"Saldo Disponible: {account['balance']['available']} {account['currency']}")
        
        self.positions_list.clear()
        buy_positions, sell_positions = self.capital_ops.get_open_positions()
        for pos in buy_positions + sell_positions:
            self.positions_list.addItem(f"{pos['position']['direction']} {pos['market']['instrumentName']} - {pos['position']['size']}")
        
        self.watchlist.clear()
        # Aquí podrías cargar precios de activos de interés
        self.watchlist.addItem("ETH-USD: $3000")
        self.watchlist.addItem("BTC-USD: $45000")
    
    def start_bots(self):
        self.bot_status.setText("Bots de Trading: ON")
        print("[INFO] Bots activados")
    
    def stop_bots(self):
        self.bot_status.setText("Bots de Trading: OFF")
        print("[INFO] Bots detenidos")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TradingDashboard()
    window.show()
    sys.exit(app.exec())
