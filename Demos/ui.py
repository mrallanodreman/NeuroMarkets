"""
ui.py - Renderizador Rich UI para CLILive mode
Genera layout Rich basado en BotState
"""
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from datetime import datetime
from state import BotState


def render_ui(bot_state: BotState) -> Layout:
    """
    Genera el Layout completo de la UI basado en BotState.

    Args:
        bot_state: Instancia de BotState con información actual

    Returns:
        Layout: Layout Rich listo para display con Live
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

    # División izquierda: capital, cuenta, señal, razón, LOGS
    layout["left"].split_column(
        Layout(name="capital", size=10),
        Layout(name="account", size=7),
        Layout(name="signal", size=5),
        Layout(name="reason", size=10),
        Layout(name="logs")  # LOGS abajo ocupan resto del espacio
    )

    # División derecha: indicadores, tendencia/contexto
    layout["right"].split_column(
        Layout(name="indicators", size=15),
        Layout(name="context", size=10)
    )

    # Renderizar cada sección
    layout["header"].update(_render_header(bot_state))
    layout["capital"].update(_render_capital_management(bot_state))
    layout["account"].update(_render_account(bot_state))
    layout["signal"].update(_render_signal(bot_state))
    layout["reason"].update(_render_reason(bot_state))
    layout["indicators"].update(_render_indicators(bot_state))
    layout["context"].update(_render_context(bot_state))
    layout["logs"].update(_render_logs(bot_state))

    return layout


def _render_header(bot_state: BotState) -> Panel:
    """Renderiza el header con título y timestamp."""
    timestamp = bot_state.last_update.strftime("%Y-%m-%d %H:%M:%S UTC") if bot_state.last_update else "-"
    title = Text()
    title.append("🤖 ETHBOY CLILIVE MODE", style="bold cyan")
    title.append(f" | {timestamp}", style="dim")

    return Panel(
        title,
        border_style="cyan",
        box=box.DOUBLE
    )


def _render_capital_management(bot_state: BotState) -> Panel:
    """Renderiza panel de gestión de capital."""
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="cyan bold", width=22)
    table.add_column("Value", style="white")

    # Balance total (equity)
    balance_total = bot_state.balance_total or 0.0
    balance_available = bot_state.balance or 0.0
    balance_deposit = bot_state.balance_deposit or 0.0
    balance_pnl = bot_state.balance_profitloss or 0.0
    capital_pct = bot_state.capital_available_pct or 0.0

    # Color según estado de capital
    if capital_pct >= 70:
        status_emoji = "🟢"
        status_style = "bold green"
    elif capital_pct >= 50:
        status_emoji = "🟡"
        status_style = "bold yellow"
    elif capital_pct >= 30:
        status_emoji = "🟠"
        status_style = "bold orange1"
    else:
        status_emoji = "🔴"
        status_style = "bold red"

    # Capital comprometido
    capital_committed = balance_total - balance_available

    table.add_row("💰 Balance Total", f"${balance_total:.2f}")
    table.add_row("✅ Disponible", f"${balance_available:.2f}")
    table.add_row("📊 Capital Libre", Text(f"{status_emoji} {capital_pct:.1f}%", style=status_style))
    table.add_row("🔒 Comprometido", f"${capital_committed:.2f}")
    table.add_row("💵 Depósito", f"${balance_deposit:.2f}")

    # P&L con color
    pnl_style = "bold green" if balance_pnl >= 0 else "bold red"
    pnl_emoji = "📈" if balance_pnl >= 0 else "📉"
    table.add_row("📊 P&L", Text(f"{pnl_emoji} ${balance_pnl:+.2f}", style=pnl_style))

    # Estado de protección
    if capital_pct < 50:
        protection_msg = "🛡️ PROTECCIÓN ACTIVA"
        protection_style = "bold red blink"
    else:
        protection_msg = "✅ Operativo Normal"
        protection_style = "bold green"

    table.add_row("🛡️ Estado", Text(protection_msg, style=protection_style))

    return Panel(
        table,
        title="[bold]💰 GESTIÓN DE CAPITAL[/bold]",
        border_style="green" if capital_pct >= 50 else "red",
        box=box.DOUBLE
    )


def _render_account(bot_state: BotState) -> Panel:
    """Renderiza info de cuenta."""
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="cyan", width=20)
    table.add_column("Value", style="white")

    table.add_row("🏦 Cuenta", bot_state.account)
    table.add_row("💲 Precio ETH", f"${bot_state.price:.2f}")

    # Calcular tiempo desde última actualización
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        delta = (now - bot_state.last_update).total_seconds()
        table.add_row("⏱️ Actualización", f"hace {delta:.0f}s")
    except Exception:
        table.add_row("⏱️ Actualización", "-")

    return Panel(
        table,
        title="[bold]📋 Información General[/bold]",
        border_style="blue",
        box=box.ROUNDED
    )


def _render_signal(bot_state: BotState) -> Panel:
    """Renderiza la señal actual."""
    # Determinar color según señal
    signal_text = bot_state.signal or "HOLD ⚠️"
    if "BUY" in signal_text and "✅" in signal_text:
        signal_style = "bold green"
    elif "SELL" in signal_text and "❌" in signal_text:
        signal_style = "bold red"
    else:
        signal_style = "bold yellow"

    content = Text()
    content.append("Señal: ", style="cyan")
    content.append(signal_text, style=signal_style)
    content.append("\n")
    content.append("Acción: ", style="cyan")
    content.append(bot_state.action or "HOLD", style=signal_style)

    return Panel(
        content,
        title="[bold]🎯 Señal Actual[/bold]",
        border_style="yellow",
        box=box.ROUNDED
    )


def _render_reason(bot_state: BotState) -> Panel:
    """Renderiza la razón estratégica."""
    reason_text = bot_state.reason or "-"

    # Limpiar y formatear razon
    try:
        r = str(reason_text).strip()
        r = r.replace('\n', ' ').replace('\r', ' ')
        if len(r) > 500:
            r = r[:497] + "..."
        if r == "":
            r = "Esperando datos..."
    except Exception:
        r = "-"

    content = Text(r, style="white")

    return Panel(
        content,
        title="[bold]📋 Razón Estratégica[/bold]",
        border_style="blue",
        box=box.ROUNDED
    )


def _render_indicators(bot_state: BotState) -> Panel:
    """Renderiza indicadores técnicos."""
    if not bot_state.indicators:
        return Panel(
            Text("Sin indicadores disponibles", style="dim italic"),
            title="[bold]📊 Indicadores Técnicos[/bold]",
            border_style="magenta",
            box=box.ROUNDED
        )

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Indicador", style="cyan", no_wrap=True, width=12)
    table.add_column("Valor", style="white")

    # Mostrar indicadores más relevantes primero
    priority = ['RSI', 'MACD', 'ADX', 'ATR', 'EMA_20', 'EMA_50', 'Volume_Ratio']
    shown = set()

    # Primero los prioritarios
    for key in priority:
        if key in bot_state.indicators:
            val = bot_state.indicators[key]
            try:
                if isinstance(val, float):
                    display = f"{val:.2f}"
                else:
                    display = str(val)
            except Exception:
                display = str(val)
            table.add_row(key, display)
            shown.add(key)

    # Luego el resto (máximo 5 más)
    count = 0
    for k in sorted(bot_state.indicators.keys()):
        if k not in shown and count < 5:
            v = bot_state.indicators[k]
            try:
                if isinstance(v, float):
                    display = f"{v:.2f}"
                else:
                    display = str(v)
            except Exception:
                display = str(v)
            table.add_row(k, display)
            count += 1

    return Panel(
        table,
        title="[bold]📊 Indicadores Técnicos[/bold]",
        border_style="magenta",
        box=box.ROUNDED
    )


def _render_context(bot_state: BotState) -> Panel:
    """Renderiza contexto de tendencia y bias."""
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="cyan", width=15)
    table.add_column("Value", style="white")

    # Tendencia
    trend_text = bot_state.trend or "-"
    if "Alcista" in trend_text or "BULLISH" in trend_text:
        trend_style = "green"
    elif "Bajista" in trend_text or "BEARISH" in trend_text:
        trend_style = "red"
    else:
        trend_style = "yellow"
    table.add_row("📈 Tendencia", Text(trend_text, style=trend_style))

    # Market Bias
    bias_text = bot_state.bias or "N/A"
    bias_age = bot_state.bias_age or 0
    table.add_row("🎯 Market Bias", f"{bias_text} (age={bias_age})")

    # Micro confirmación
    micro_text = "✅ Confirmada" if bot_state.micro_confirm else "❌ No confirmada"
    micro_style = "green" if bot_state.micro_confirm else "red"
    table.add_row("🔍 Micro", Text(micro_text, style=micro_style))

    # Bad candle detection
    bad_candle_text = "⚠️ Detectada" if bot_state.bad_candle else "✅ Normal"
    bad_style = "red" if bot_state.bad_candle else "green"
    table.add_row("🕯️ Vela", Text(bad_candle_text, style=bad_style))

    return Panel(
        table,
        title="[bold]🌐 Tendencia & Contexto[/bold]",
        border_style="blue",
        box=box.ROUNDED
    )


def _render_logs(bot_state: BotState) -> Panel:
    """Renderiza logs recientes."""
    if not bot_state.logs or len(bot_state.logs) == 0:
        return Panel(
            Text("Sin logs recientes", style="dim italic"),
            title="[bold]📝 Log en Tiempo Real[/bold]",
            border_style="white",
            box=box.ROUNDED
        )

    # Calcular cuántos logs mostrar según espacio disponible
    try:
        import shutil
        size = shutil.get_terminal_size()
        total_lines = size.lines
    except Exception:
        total_lines = 30

    # Paneles arriba ocupan ~35 líneas, dejar resto para logs
    reserved = 35
    available_lines = max(5, total_lines - reserved - 4)

    # Obtener últimos N logs
    entries = list(bot_state.logs)

    # Mostrar desde el más antiguo al más reciente (reverse porque deque appendleft)
    slice_start = max(0, len(entries) - available_lines)
    visible = list(reversed(entries[slice_start:]))

    content = Text()
    for msg in visible:
        # Aplicar coloring básico según prefijos
        msg_str = str(msg)
        if "[ERROR]" in msg_str or "❌" in msg_str:
            style = "red"
        elif "[WARNING]" in msg_str or "⚠️" in msg_str:
            style = "yellow"
        elif "[INFO]" in msg_str or "✅" in msg_str:
            style = "green"
        elif "[DATAETH]" in msg_str:
            style = "cyan"
        elif "[MOMENTUM]" in msg_str:
            style = "magenta"
        else:
            style = "white"

        content.append(msg_str + "\n", style=style)

    title = f"[bold]📝 Log en Tiempo Real (últimos {len(visible)})[/bold]"

    return Panel(
        content,
        title=title,
        border_style="white",
        box=box.ROUNDED
    )
