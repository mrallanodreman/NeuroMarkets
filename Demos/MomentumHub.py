from MomentumAnalyzer import MomentumAnalyzer
import threading

# Singleton momentum analyzer shared across modules
momentum = MomentumAnalyzer()
_lock = threading.Lock()

def add_tick(price, timestamp=None):
    with _lock:
        return momentum.add_tick(price, timestamp)

def get_metrics():
    with _lock:
        return momentum.get_metrics()

def get_debug_info():
    with _lock:
        return momentum.get_debug_info()
