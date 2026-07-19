from dataclasses import dataclass, field
from collections import deque
from typing import Dict, Any, Deque
from datetime import datetime, timezone


@dataclass
class BotState:
    # --- Cuenta ---
    account: str = "EthOperator"
    balance: float = 0.0
    price: float = 0.0
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # --- Decisión ---
    signal: str = "HOLD ⚠️"
    action: str = "HOLD"
    reason: str = "-"
    trend: str = "-"
    bias: str | None = None
    bias_age: int = 0
    micro_confirm: bool = True
    bad_candle: bool = False

    # --- Indicadores ---
    indicators: Dict[str, Any] = field(default_factory=dict)

    # --- Logs ---
    logs: Deque[str] = field(default_factory=lambda: deque(maxlen=200))

    def log(self, msg: str):
        ts = msg
        self.logs.appendleft(ts)
