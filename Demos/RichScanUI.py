"""
RichScanUI - Interfaz Rich Live para ScanMode
Paneles fijos que se actualizan sin desplazar la pantalla
"""
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from datetime import datetime
from collections import deque
import shutil
import threading
import numpy as np


class RichScanUI:
    """
    Interfaz Rich Live para ScanMode con paneles fijos.
    Los mensajes cambian dentro sin redesplegar toda la pantalla.
    """

    def __init__(self, max_logs=None):
        """
        Args:
            max_logs: Número máximo de logs a mantener en memoria. Si es `None`, se mantiene historial completo.
        """
        self.max_logs = max_logs
        self.logs = deque(maxlen=max_logs) if max_logs is not None else deque()

        # Estado inicial
        self.account = "EthOperator"
        self.balance = 0.0
        self.price = 0.0
        self.signal = "HOLD ⚠️"
        self.reason = "Esperando datos..."
        self.positions = []
        self.momentum_metrics = {}
        self.last_update = datetime.now()
        self.indicators = {}

        # 💰 Gestión de Capital
        self.balance_total = 0.0
        self.balance_deposit = 0.0
        self.balance_pnl = 0.0
        self.capital_pct = 0.0
        self.num_buy = 0
        self.num_sell = 0
        self.max_positions = 2
        self._refresh_lock = threading.Lock()

    def add_log(self, message, style="white"):
        """Añade un mensaje al log.

        Args:
            message: Texto del log.
            style: Estilo Rich opcional para el mensaje.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append((f"[{timestamp}] {message}", style))

    def update_account(self, balance, price):
        """Actualiza info de cuenta."""
        self.balance = balance
        self.price = price
        self.last_update = datetime.now()
        try:
            # Intentar forzar redraw inmediato si existe un Live asociado
            self.refresh()
        except Exception:
            pass

    def update_signal(self, signal, reason):
        """Actualiza señal y razón."""
        self.signal = signal
        # Normalizar y sanitizar la razón para evitar saltos de línea o contenido extraño
        try:
            r = str(reason or "").strip()
            r = r.replace('\n', ' ').replace('\r', ' ')
            if r == "":
                r = "-"
            # acortar si es demasiado larga
            if len(r) > 400:
                r = r[:397] + "..."
            self.reason = r
        except Exception:
            self.reason = "-"
        try:
            # Forzar redraw del panel de decisión al actualizar señal/razón
            self.refresh()
        except Exception:
            pass

    def update_positions(self, positions):
        """Actualiza lista de posiciones."""
        self.positions = positions

    def update_indicators(self, indicators):
        """Actualiza el panel de indicadores con un dict de clave->valor."""
        try:
            # normalizar valores simples para display
            out = {}
            for k, v in (indicators or {}).items():
                try:
                    if isinstance(v, (int, float, np.floating, np.integer)):
                        out[k] = float(v)
                    else:
                        out[k] = v
                except Exception:
                    out[k] = str(v)
            self.indicators = out
        except Exception:
            self.indicators = {}

    def update_momentum(self, metrics):
        """Actualiza métricas de momentum."""
        self.momentum_metrics = metrics

    def update_capital(self, balance_total, balance_available, balance_deposit, balance_pnl, capital_pct, num_buy, num_sell, max_positions):
        """
        Actualiza información de gestión de capital.

        Args:
            balance_total: Balance total (equity)
            balance_available: Balance disponible
            balance_deposit: Depósito original
            balance_pnl: P&L acumulado
            capital_pct: % de capital disponible
            num_buy: Número de posiciones BUY activas
            num_sell: Número de posiciones SELL activas
            max_positions: Máximo de posiciones permitidas
        """
        self.balance_total = balance_total
        self.balance_deposit = balance_deposit
        self.balance_pnl = balance_pnl
        self.capital_pct = capital_pct
        self.num_buy = num_buy
        self.num_sell = num_sell
        self.max_positions = max_positions
        try:
            self.refresh()
        except Exception:
            pass

    def render(self):
        """
        Genera el Layout completo de la UI.

        Returns:
            Layout: Layout Rich listo para display
        """
        # Crear layout principal
        layout = Layout()

        # División: Header arriba, Body abajo
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body")
        )

        # División del body: izquierda y derecha
        layout["body"].split_row(
            Layout(name="left", ratio=2),
            Layout(name="right", ratio=1)
        )

        # División izquierda: capital, cuenta, señal, LOGS
        layout["left"].split_column(
            Layout(name="capital", size=11),
            Layout(name="account", size=4),
            Layout(name="signal", size=8),
            Layout(name="logs")  # LOGS debajo de señal
        )

        # División derecha: momentum, posiciones
        layout["right"].split_column(
            Layout(name="momentum", size=12),
            Layout(name="positions", size=8),
            Layout(name="indicators", size=12)
        )

        # Renderizar cada sección
        layout["header"].update(self._render_header())
        layout["capital"].update(self._render_capital_management())
        layout["account"].update(self._render_account())
        layout["signal"].update(self._render_signal())
        layout["positions"].update(self._render_positions())
        layout["momentum"].update(self._render_momentum())
        layout["logs"].update(self._render_logs())
        layout["indicators"].update(self._render_indicators())

        return layout

    def _render_header(self):
        """Renderiza el header."""
        timestamp = self.last_update.strftime("%Y-%m-%d %H:%M:%S")
        title = Text()
        title.append("🤖 ETHBOY SCANMODE", style="bold cyan")
        title.append(f" | {timestamp}", style="dim")

        return Panel(
            title,
            border_style="cyan",
            box=box.DOUBLE
        )

    def _render_account(self):
        """Renderiza info de cuenta con precio tick-a-tick."""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")

        # Precio tick-a-tick desde momentum (si disponible)
        tick_price = self.momentum_metrics.get('price', self.price) if self.momentum_metrics else self.price
        table.add_row("💲 Precio Actual", f"${tick_price:.2f}")

        return Panel(
            table,
            title="[bold]📋 Info General[/bold]",
            border_style="blue",
            box=box.ROUNDED
        )

    def _render_capital_management(self):
        """
        Renderiza panel de gestión de capital con métricas financieras.
        """
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Key", style="cyan bold", width=20)
        table.add_column("Value", style="white")

        # Balance total
        table.add_row("💰 Balance Total", f"${self.balance_total:.2f}")

        # Disponible
        table.add_row("✅ Disponible", f"${self.balance:.2f}")

        # Capital Libre con color dinámico
        if self.capital_pct >= 70:
            status_emoji = "🟢"
            pct_style = "bold green"
        elif self.capital_pct >= 50:
            status_emoji = "🟡"
            pct_style = "bold yellow"
        elif self.capital_pct >= 30:
            status_emoji = "🟠"
            pct_style = "bold orange1"
        else:
            status_emoji = "🔴"
            pct_style = "bold red"

        capital_text = Text()
        capital_text.append(f"{status_emoji} {self.capital_pct:.1f}%", style=pct_style)
        table.add_row("📊 Capital Libre", capital_text)

        # Comprometido
        committed = self.balance_total - self.balance
        table.add_row("🔒 Comprometido", f"${committed:.2f}")

        # Depósito
        table.add_row("💵 Depósito", f"${self.balance_deposit:.2f}")

        # P&L con color
        pnl_emoji = "📈" if self.balance_pnl >= 0 else "📉"
        pnl_style = "bold green" if self.balance_pnl >= 0 else "bold red"
        pnl_text = Text(f"{pnl_emoji} ${self.balance_pnl:+.2f}", style=pnl_style)
        table.add_row("📊 P&L", pnl_text)

        # Estado de protección
        if self.capital_pct < 70:
            status_text = Text("🛡️ PROTECCIÓN ACTIVA", style="bold red")
            border_color = "red"
        else:
            status_text = Text("✅ Operativo Normal", style="bold green")
            border_color = "green"
        table.add_row("🛡️ Estado", status_text)

        # Posiciones
        total_pos = self.num_buy + self.num_sell
        table.add_row("📊 Posiciones", f"{total_pos}/{self.max_positions} (BUY:{self.num_buy}, SELL:{self.num_sell})")

        return Panel(
            table,
            title="[bold]💰 GESTIÓN DE CAPITAL[/bold]",
            border_style=border_color,
            box=box.DOUBLE
        )

    def _render_signal(self):
        """Renderiza la señal actual."""
        # Determinar color según señal
        if "BUY" in self.signal:
            signal_style = "bold green"
        elif "SELL" in self.signal:
            signal_style = "bold red"
        else:
            signal_style = "bold yellow"

        content = Text()
        content.append("🎯 Señal: ", style="cyan")
        content.append(self.signal, style=signal_style)
        content.append("\n\n")
        content.append("📋 Razón:\n", style="cyan")
        content.append(self.reason, style="white")

        return Panel(
            content,
            title="[bold]🔍 DECISIÓN ACTIVA[/bold]",
            border_style="yellow",
            box=box.ROUNDED
        )

    def _render_positions(self):
        """Renderiza tabla de posiciones."""
        if not self.positions or len(self.positions) == 0:
            return Panel(
                Text("Sin posiciones abiertas", style="dim italic"),
                title="[bold]📊 POSICIONES[/bold]",
                border_style="blue",
                box=box.ROUNDED
            )

        table = Table(box=box.SIMPLE)
        table.add_column("Dir", style="cyan", width=6)
        table.add_column("Size", style="white", width=8)
        table.add_column("UPL", style="white", width=10)
        table.add_column("Deal ID", style="dim", width=8)

        for pos in self.positions[:5]:  # Máximo 5 posiciones
            pos_data = pos.get("position", {})
            direction = pos_data.get("direction", "N/A")
            size = pos_data.get("size", 0)
            upl = float(pos_data.get("upl", 0))
            deal_id = pos_data.get("dealId", "N/A")[-6:]

            # Color según UPL
            if upl > 0:
                upl_style = "green"
            elif upl < 0:
                upl_style = "red"
            else:
                upl_style = "white"

            upl_text = Text(f"${upl:+.2f}", style=upl_style)

            table.add_row(
                direction,
                str(size),
                upl_text,
                deal_id
            )

        return Panel(
            table,
            title=f"[bold]📊 POSICIONES ({len(self.positions)})[/bold]",
            border_style="blue",
            box=box.ROUNDED
        )

    def _render_momentum(self):
        """Renderiza métricas de momentum (sin precio, ya está en Info General)."""
        # Mostrar panel de recopilación solo si no hay ningún tick
        if not self.momentum_metrics or self.momentum_metrics.get("tick_count", 0) == 0:
            return Panel(
                Text("Recopilando datos de momentum...", style="dim italic"),
                title="[bold]🎯 MOMENTUM TICK-A-TICK[/bold]",
                border_style="magenta",
                box=box.ROUNDED
            )

        m = self.momentum_metrics

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Métrica", style="cyan")
        table.add_column("Valor", style="white")

        # Velocidad con signo
        velocity = m.get('velocity', 0)
        vel_style = "green" if velocity > 0 else "red" if velocity < 0 else "white"
        table.add_row("⚡ Velocidad", Text(f"{velocity:+.3f} $/s", style=vel_style))

        # Aceleración con signo
        accel = m.get('acceleration', 0)
        accel_style = "green" if accel > 0 else "red" if accel < 0 else "white"
        table.add_row("🚀 Aceleración", Text(f"{accel:+.3f} $/s²", style=accel_style))

        # Score
        score = m.get('momentum_score', 0)
        score_style = "bold green" if score >= 60 else "yellow" if score >= 30 else "dim"
        table.add_row("📈 Score", Text(f"{score:.0f}/100", style=score_style))

        # Dirección
        direction = m.get('direction', 'NEUTRAL')
        if "BULLISH" in direction:
            dir_style = "bold green"
        elif "BEARISH" in direction:
            dir_style = "bold red"
        else:
            dir_style = "yellow"
        table.add_row("🧭 Dirección", Text(direction, style=dir_style))

        # Ticks capturados
        table.add_row("📊 Ticks", f"{m.get('tick_count', 0)}/30")

        # Si hay pocos ticks, indicar que aún se están estabilizando
        if m.get('tick_count', 0) < 5:
            table.add_row("ℹ️ Nota", "Recopilando — métricas parciales", style="dim")

        return Panel(
            table,
            title="[bold]🎯 MOMENTUM TICK-A-TICK[/bold]",
            border_style="magenta",
            box=box.ROUNDED
        )

    def _render_indicators(self):
        """Renderiza todos los indicadores calculados (tabla clave-valor)."""
        if not self.indicators:
            return Panel(
                Text("Sin indicadores disponibles", style="dim italic"),
                title="[bold]📈 INDICADORES[/bold]",
                border_style="cyan",
                box=box.ROUNDED
            )

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Indicador", style="cyan", no_wrap=True)
        table.add_column("Valor", style="white")

        # Ordenar por nombre para consistencia
        for k in sorted(self.indicators.keys()):
            v = self.indicators[k]
            try:
                if isinstance(v, float):
                    display = f"{v:.6g}"
                else:
                    display = str(v)
            except Exception:
                display = str(v)
            table.add_row(k, display)

        return Panel(
            table,
            title="[bold]📈 INDICADORES (última fila)[/bold]",
            border_style="cyan",
            box=box.ROUNDED
        )

    def _render_logs(self):
        """Renderiza logs recientes."""
        if not self.logs:
            return Panel(
                Text("Sin logs recientes", style="dim italic"),
                title="[bold]📝 LOGS[/bold]",
                border_style="white",
                box=box.ROUNDED
            )

        # Calcular espacio disponible en terminal para el panel de logs
        try:
            size = shutil.get_terminal_size()
            total_lines = size.lines
        except Exception:
            total_lines = 24

        # Paneles con tamaño fijo arriba en esta UI: header=3, capital=11, account=4, signal=8
        reserved = 3 + 11 + 4 + 8
        available_lines = max(3, total_lines - reserved - 4)  # -4 por bordes/títulos/padding

        # Cada registro usualmente ocupa 1 línea; ajustar para mostrar las últimas `available_lines` entradas
        # Garantizar que siempre se muestre la última línea
        logs_to_show = []
        try:
            # Convertir deque entries (message, style) en texto, pero mostrar solo la cantidad que cabe
            entries = list(self.logs)
            if not entries:
                return Panel(
                    Text("Sin logs recientes", style="dim italic"),
                    title="[bold]📝 LOGS[/bold]",
                    border_style="white",
                    box=box.ROUNDED
                )

            # Mostrar las últimas `available_lines` entradas
            slice_start = max(0, len(entries) - available_lines)
            visible = entries[slice_start:]

            content = Text()
            for item in visible:
                if isinstance(item, tuple):
                    msg, style = item
                else:
                    msg, style = (str(item), "white")
                content.append(msg + "\n", style=style)

            title = f"[bold]📝 LOGS (mostrando {len(visible)})[/bold]"
            return Panel(
                content,
                title=title,
                border_style="white",
                box=box.ROUNDED
            )
        except Exception:
            # Fallback sencillo
            content = Text()
            for item in list(self.logs)[-10:]:
                if isinstance(item, tuple):
                    msg, style = item
                else:
                    msg, style = (str(item), "white")
                content.append(msg + "\n", style=style)
            return Panel(content, title="[bold]📝 LOGS[/bold]", border_style="white", box=box.ROUNDED)

    def refresh(self):
        """Forzar redraw del Live asociado si existe (llamable desde callbacks)."""
        lock = getattr(self, '_refresh_lock', None)
        if lock is not None and not lock.acquire(blocking=False):
            return  # otro hilo ya está actualizando, saltar
        try:
            live = getattr(self, '_live', None)
            if live is not None:
                live.update(self.render())
        except Exception:
            pass
        finally:
            if lock is not None:
                lock.release()
