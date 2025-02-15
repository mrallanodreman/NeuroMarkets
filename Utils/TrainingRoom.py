import yfinance as yf
import numpy as np
import pandas as pd
import pickle
from datetime import datetime, timedelta
import pytz
import matplotlib.pyplot as plt
import seaborn as sns
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, EMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from sklearn.preprocessing import StandardScaler
from hmmlearn.hmm import VariationalGaussianHMM  # 🚀 MODELO CORRECTO

def download_data(ticker="ETH-USD", interval="1h", period="1y", buffer_months=3):
    """Descarga datos de Yahoo Finance asegurando suficiente historial para cálculos."""
    print(f"[INFO] Descargando datos para {ticker}...")
    period_months = int(period[:-1]) if period.endswith("y") else int(period[:-2]) / 30
    total_months = int(period_months + buffer_months)
    data = yf.download(ticker, interval=interval, period=f"{total_months}mo")
    if data.empty:
        raise ValueError("[ERROR] No se obtuvieron datos desde Yahoo Finance.")
    start_date = (datetime.now(pytz.UTC) - timedelta(days=365)).strftime("%Y-%m-%d")
    data = data.loc[start_date:]
    print("[INFO] Datos descargados correctamente.")
    return data

def process_data(data):
    """Preprocesa los datos: limpieza y cálculo de log-returns."""
    print("[INFO] Procesando datos...")
    
    if not isinstance(data.index, pd.DatetimeIndex):
        data.index = pd.to_datetime(data.index)

    # ✅ Verifica si ya tiene zona horaria antes de convertir
    if data.index.tz is None:
        data.index = data.index.tz_localize('UTC')
    else:
        data.index = data.index.tz_convert('UTC')

    data['log_return'] = np.log(data['Close'] / data['Close'].shift(1))
    data.dropna(inplace=True)
    print("[INFO] Datos procesados correctamente.")
    return data

def compute_indicators(data):
    print("[INFO] Calculando indicadores técnicos...")

    close_series = data['Close'].squeeze()
    high_series = data['High'].squeeze()
    low_series = data['Low'].squeeze()

    # Aplicar indicadores técnicos correctamente
    data['RSI'] = RSIIndicator(close=close_series, window=14).rsi()
    data['MACD'] = MACD(close=close_series).macd()
    data['ATR'] = AverageTrueRange(high=high_series, low=low_series, close=close_series, window=14).average_true_range()
    data['STOCH'] = StochasticOscillator(high=high_series, low=low_series, close=close_series).stoch()
    data['EMA_50'] = EMAIndicator(close=close_series, window=50).ema_indicator()
    data['BB_width'] = BollingerBands(close=close_series, window=20).bollinger_wband()

    # Eliminar filas con valores NaN
    data.dropna(inplace=True)

    print("[INFO] Indicadores calculados correctamente.")
    return data

def prepare_features(data):
    print("[INFO] Preparando features...")
    features = ['log_return', 'RSI', 'MACD', 'ATR', 'STOCH', 'EMA_50', 'BB_width']
    return data[features].dropna().copy()

def scale_features(features_df):
    print("[INFO] Escalando features...")
    scaler = StandardScaler()
    return scaler.fit_transform(features_df), scaler

def train_vghmm(X, n_states=5, n_iter=1000):
    """Entrena el modelo Variational Gaussian Hidden Markov Model (VGHMM)."""
    print("[INFO] Entrenando modelo VGHMM con Variational Inference...")

    model = VariationalGaussianHMM(
        n_components=n_states,  # Número de estados ocultos
        covariance_type="diag",  # Matriz de covarianza diagonal (más estable)
        n_iter=n_iter,  # Número de iteraciones
        random_state=2222  # Semilla fija para replicabilidad
    )
    
    model.fit(X)
    print("[INFO] Modelo entrenado correctamente.")
    return model

def save_model(model, scaler, features, filename="vghmm_model.pkl"):
    """Guarda el modelo y el escalador en un archivo."""
    model_data = {
        "model": model,
        "features": features,
        "scaler_stats": {
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist()
        }
    }
    with open(filename, "wb") as f:
        pickle.dump(model_data, f)
    print(f"[INFO] Modelo guardado en {filename}")

def main():
    """Ejecuta el pipeline de entrenamiento con VGHMM."""
    ticker, interval, period = "ETH-USD", "1h", "1y"
    
    # 📥 Descargar y procesar datos
    data = download_data(ticker=ticker, interval=interval, period=period)
    data = process_data(data)
    data = compute_indicators(data)
    
    # 📊 Preparar features y entrenar modelo
    features_df = prepare_features(data)
    X, scaler = scale_features(features_df)
    vghmm_model = train_vghmm(X, n_states=5)  # 🚀 AHORA USA VGHMM
    
    # 📌 Guardar modelo
    save_model(vghmm_model, scaler, features_df.columns.tolist())

    # 📊 Obtener probabilidades de estado y matriz de transición
    hidden_states = vghmm_model.predict(X)
    features_df['State'] = hidden_states
    transition_matrix = vghmm_model.transmat_
    
    # 📊 Crear figura con dos subgráficos
    fig, axes = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1]})

    # 📈 Gráfico de evolución del precio con estados
    axes[0].plot(data.index, data['Close'], label="Precio ETH", color="blue")
    for state in np.unique(hidden_states):
        idx = features_df[features_df['State'] == state].index
        axes[0].scatter(idx, data.loc[idx, 'Close'], label=f"Estado {state}", s=10)
    axes[0].set_title("Evolución del Precio ETH y Estados (VGHMM)")
    axes[0].set_xlabel("Fecha")
    axes[0].set_ylabel("Precio")
    axes[0].legend()
    axes[0].grid(True)

    # 🔥 Heatmap de la matriz de transición
    sns.heatmap(transition_matrix, annot=True, fmt=".2f", cmap="coolwarm", cbar=True, ax=axes[1])
    axes[1].set_title("Heatmap de la Matriz de Transición (VGHMM)")
    axes[1].set_xlabel("Estado Siguiente")
    axes[1].set_ylabel("Estado Actual")

    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()
