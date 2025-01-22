import os
import pickle
import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler  # Cambiamos a MinMaxScaler
from hmmlearn.hmm import GaussianHMM
import json
import matplotlib
matplotlib.use('TkAgg')  # Configura el backend interactivo
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider

import yfinance as yf
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import AverageTrueRange
import pytz
from datetime import datetime, timedelta


class TrainingRoom:
    def __init__(self, data_dir="Reports", model_file="Intuicion.pkl", features=None, n_components=3):
        self.data_dir = data_dir
        self.model_file = model_file
        self.features = features if features else ['Close', 'Volume', 'MACD', 'RSI', 'ATR']
        self.n_components = n_components
        self.scaler = None
        self.hmm_model = None

        # Crear el directorio de datos si no existe
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

    def load_data_from_json(self, json_file_path):
        """
        Carga los datos procesados desde un archivo JSON.

        :param json_file_path: Ruta al archivo JSON generado por InitialData.py
        :return: DataFrame con los datos cargados
        """
        print(f"[DEBUG] Cargando datos desde {json_file_path}...")
        try:
            with open(json_file_path, 'r') as f:
                json_data = json.load(f)
            df = pd.DataFrame(json_data['data'])
            
            # Convertir 'Datetime' de vuelta a formato datetime
            df['Datetime'] = pd.to_datetime(df['Datetime'], unit='ms', utc=True)
            df.set_index('Datetime', inplace=True)
            
            print(f"[DEBUG] Datos cargados desde {json_file_path}, filas: {len(df)}")
            return df
        except Exception as e:
            print(f"[ERROR] Error al cargar datos desde JSON: {e}")
            return pd.DataFrame()

    def download_data_from_scratch(self, ticker="BTC-USD", interval="1h", period="1y"):
        """
        (Método original que puedes mantener o eliminar según tu preferencia)
        Descarga datos crudos de Yahoo Finance, procesa columnas e indicadores,
        y retorna un DataFrame sin escalar.
        """
        print(f"[DEBUG] Descargando datos de {ticker} con interval={interval}, period={period} via yfinance...")
        data = yf.download(ticker, interval=interval, period=period)
        if data.empty:
            print("[ERROR] No se obtuvieron datos desde Yahoo Finance.")
            return pd.DataFrame()

        # Procesar columnas, renombrar, etc.
        data.reset_index(inplace=True)
        if 'Datetime' not in data.columns:
            data.rename(columns={'Date': 'Datetime'}, inplace=True)
        data['Datetime'] = pd.to_datetime(data['Datetime'], errors='coerce')
        data.set_index('Datetime', inplace=True)

        # Verificar y asegurar que 'Close' es una Serie unidimensional
        if isinstance(data['Close'], pd.DataFrame):
            data['Close'] = data['Close'].squeeze()

        print(f"[DEBUG] Tipo de 'Close': {type(data['Close'])}, shape: {data['Close'].shape}")

        # Calcular indicadores técnicos
        print("[INFO] Calculando indicadores técnicos...")
        try:
            # Asegurarse de que 'Close' es una Serie unidimensional antes de calcular RSI
            if not isinstance(data['Close'], pd.Series):
                data['Close'] = data['Close'].squeeze()
                print(f"[DEBUG] 'Close' convertido a Serie: {type(data['Close'])}, shape: {data['Close'].shape}")

            data['RSI'] = RSIIndicator(close=data['Close'], window=14).rsi()
            macd = MACD(close=data['Close'])
            data['MACD'] = macd.macd()
            data['MACD_Signal'] = macd.macd_signal()
            atr = AverageTrueRange(high=data['High'], low=data['Low'], close=data['Close'], window=14)
            data['ATR'] = atr.average_true_range()
        except Exception as e:
            print(f"[ERROR] Error al calcular indicadores técnicos: {e}")
            return pd.DataFrame()

        # Cálculo del cambio en el volumen y volumen promedio diario
        try:
            data['VolumeChange'] = data['Volume'].pct_change().fillna(0)
            daily_volume = data.groupby(data.index.date)['Volume'].transform('sum')
            data['AvgDailyVolume'] = daily_volume.rolling(window=7).mean().fillna(0)
        except Exception as e:
            print(f"[ERROR] Error al calcular cambios en volumen: {e}")
            return pd.DataFrame()

        # Corregir volúmenes
        data = self.correct_volumes(data)

        # Filtrar datos según el período
        start_date_original = datetime.now(pytz.UTC) - timedelta(days=365)
        data = data[data.index >= start_date_original]

        # Manejo de NaNs
        data.fillna(0, inplace=True)

        print(f"[DEBUG] Descarga y procesamiento completados. Filas: {len(data)}")
        return data

    def correct_volumes(self, data):
        """
        Corrige los volúmenes en 0 mediante interpolación basada en valores válidos anteriores y posteriores.
        """
        if 'Volume' not in data.columns:
            print("[WARNING] Columna 'Volume' no encontrada. Saltando corrección.")
            return data
        zero_indices = data[data['Volume'] == 0].index
        for idx in zero_indices:
            prev_value = data.loc[:idx, 'Volume'][data['Volume'] != 0].last_valid_index()
            next_value = data.loc[idx:, 'Volume'][data['Volume'] != 0].first_valid_index()
            prev_volume = data.loc[prev_value, 'Volume'] if prev_value is not None else 0
            next_volume = data.loc[next_value, 'Volume'] if next_value is not None else 0
            if prev_volume and next_volume:
                corrected_volume = int((prev_volume + next_volume) / 2)
            elif prev_volume:
                corrected_volume = int(prev_volume)
            elif next_volume:
                corrected_volume = int(next_volume)
            else:
                corrected_volume = 0
            data.at[idx, 'Volume'] = corrected_volume
        print("[INFO] Volúmenes corregidos.")
        return data

    def process_features(self, data):
        """
        Procesa las características del conjunto de datos asegurando que todas las definidas en self.features se procesen correctamente.
        Aplica escalado utilizando MinMaxScaler con rango [-1, 1].
        """
        # Verificar que todas las características requeridas estén presentes
        missing_features = [feature for feature in self.features if feature not in data.columns]
        if missing_features:
            print(f"[WARNING] Las siguientes características faltan en los datos históricos: {missing_features}")
            for col in missing_features:
                data[col] = 0  # Completar características faltantes con ceros

        # Manejar valores infinitos o NaN
        data.replace([np.inf, -np.inf], np.nan, inplace=True)
        data.fillna(0, inplace=True)

        # Seleccionar las características necesarias
        selected_data = data[self.features]

        # Escalar los datos numéricos
        self.scaler = MinMaxScaler(feature_range=(-1, 1))
        try:
            scaled_data = pd.DataFrame(
                self.scaler.fit_transform(selected_data),
                index=selected_data.index,
                columns=self.features
            )
        except Exception as e:
            print(f"[ERROR] Error al escalar los datos: {e}")
            return None

        # Mostrar datos procesados para diagnóstico
        print("[INFO] Primeros valores procesados (escalados):")
        print(scaled_data.head(5))
        return scaled_data

    def train_model(self, json_file_path):
        """
        Entrena el modelo HMM utilizando datos cargados desde un archivo JSON.
        """
        # 1) Cargar y procesar datos desde el archivo JSON
        data = self.load_data_from_json(json_file_path)
        if data.empty or not isinstance(data, pd.DataFrame):
            print("[ERROR] Los datos cargados no están en formato válido o están vacíos.")
            return

        # 2) Procesar las características (incluye escalado)
        scaled_data = self.process_features(data)
        if scaled_data is None or scaled_data.empty:
            print("[ERROR] No se pudieron procesar las características.")
            return

        print("[INFO] Características procesadas y listas para entrenamiento.")

        # 3) Entrenar el modelo HMM
        print(f"[INFO] Entrenando modelo HMM con {self.n_components} componentes...")
        try:
            self.hmm_model = GaussianHMM(
                n_components=self.n_components,
                covariance_type="diag",
                n_iter=300,  # Más iteraciones para ajustar mejor el modelo
                tol=0.01,    # Tolerancia para detener la convergencia
                random_state=42
            )
            self.hmm_model.fit(scaled_data)
            print(f"[DEBUG] Tipo de covarianza del modelo: {self.hmm_model.covariance_type}")
        except Exception as e:
            print(f"[ERROR] Error al entrenar el modelo HMM: {e}")
            return

        # Ajustar las probabilidades iniciales
        try:
            self.hmm_model.startprob_ = np.full(self.hmm_model.n_components, 1 / self.n_components)
            print("[DEBUG] Probabilidades iniciales ajustadas:")
            print(self.hmm_model.startprob_)
        except Exception as e:
            print(f"[ERROR] Error al ajustar las probabilidades iniciales: {e}")

        # Regularizar la matriz de transición
        try:
            print("[INFO] Regularizando matriz de transición...")
            self.hmm_model.transmat_ += 0.05  # Incrementar probabilidades para fomentar transiciones
            np.fill_diagonal(self.hmm_model.transmat_, np.diag(self.hmm_model.transmat_) - 0.5)
            self.hmm_model.transmat_ = np.maximum(self.hmm_model.transmat_, 0.015)  # Evitar valores negativos
            self.hmm_model.transmat_ /= self.hmm_model.transmat_.sum(axis=1, keepdims=True)  # Normalizar
            print("[DEBUG] Matriz de transición regularizada:")
            print(self.hmm_model.transmat_)
        except Exception as e:
            print(f"[ERROR] Error al regularizar la matriz de transición: {e}")

        print("[INFO] Modelo HMM entrenado correctamente.")
        self.scaled_data = scaled_data.reset_index()  # Asegurar que 'Datetime' esté incluido

        # Verificar las formas de means_ y covars_
        print(f"[DEBUG] Shape of means_: {self.hmm_model.means_.shape}")
        print(f"[DEBUG] Shape of covars_: {self.hmm_model.covars_.shape}")

        # 4) Guardar el modelo entrenado junto con las estadísticas del escalador
        self.save_model()

        # 5) Analizar y mostrar los estados asignados
        self.analyze_states(data, scaled_data)
        print("[DEBUG] Validando dimensiones del modelo entrenado...")

        expected_dimensions = len(self.features)
        if self.hmm_model.means_.shape[1] != expected_dimensions:
            raise ValueError(f"[ERROR] El modelo fue entrenado con dimensiones incorrectas. "
                             f"Esperado: {expected_dimensions}, Obtenido: {self.hmm_model.means_.shape[1]}")

    def save_model(self):
        """
        Guarda el modelo HMM entrenado en un archivo junto con los features utilizados y las estadísticas del escalador.
        """
        if self.hmm_model is None:
            print("[ERROR] No hay un modelo entrenado para guardar.")
            return

        if self.scaler is not None:
            # Si usas MinMaxScaler, calcula y guarda las estadísticas equivalentes de 'mean' y 'scale'
            data_min = self.scaler.data_min_
            data_max = self.scaler.data_max_
            scaler_stats = {
                "mean": ((data_max + data_min) / 2).tolist(),  # Promedio
                "scale": ((data_max - data_min) / 2).tolist()  # Rango dividido entre 2
            }
        else:
            scaler_stats = {"mean": [], "scale": []}

        # Preparar el diccionario que se guardará
        model_data = {
            'model': self.hmm_model,
            'features': self.features,
            'scaler_stats': scaler_stats
        }

        # Guardar en un archivo pickle dentro del directorio de datos
        model_path = os.path.join(self.data_dir, self.model_file)
        try:
            with open(model_path, 'wb') as file:
                pickle.dump(model_data, file)
            print(f"[INFO] Modelo guardado exitosamente en {model_path}.")
        except Exception as e:
            print(f"[ERROR] Error al guardar el modelo: {e}")



    def load_model(self):
        """
        Carga el modelo HMM entrenado desde un archivo, junto con los features utilizados y las estadísticas del escalador.
        """
        model_path = os.path.join(self.data_dir, self.model_file)
        if not os.path.exists(model_path):
            print(f"[ERROR] No se encontró el modelo en {model_path}.")
            return

        try:
            with open(model_path, "rb") as file:
                model_data = pickle.load(file)
        except Exception as e:
            print(f"[ERROR] Error al cargar el modelo: {e}")
            return

        if isinstance(model_data, dict) and 'model' in model_data:
            self.hmm_model = model_data['model']
            self.features = model_data.get('features', [])
            scaler_stats = model_data.get('scaler_stats', {})
            if scaler_stats and 'mean' in scaler_stats and 'scale' in scaler_stats:
                self.scaler = MinMaxScaler(feature_range=(-1, 1))
                # Reconstruir 'data_min_' y 'data_max_' a partir de 'mean' y 'scale'
                self.scaler.data_min_ = np.array(scaler_stats['mean']) - np.array(scaler_stats['scale'])
                self.scaler.data_max_ = np.array(scaler_stats['mean']) + np.array(scaler_stats['scale'])
            print(f"[INFO] Modelo cargado exitosamente desde {model_path}.")
            print(f"[INFO] Características utilizadas durante el entrenamiento: {self.features}")
        else:
            print("[ERROR] El archivo no contiene el modelo esperado.")
            self.hmm_model = None


    def analyze_states(self, data, features):
        """
        Analiza las características promedio de cada estado, muestra la matriz de transición
        y la evolución de los estados en una sola ventana.
        """
        if not self.hmm_model:
            print("[ERROR] No se ha cargado un modelo para analizar los estados.")
            return

        try:
            # Predicción de estados
            states = self.hmm_model.predict(features.values)
            data['State'] = states
        except Exception as e:
            print(f"[ERROR] Error al predecir los estados: {e}")
            return

        # Diagnóstico básico
        print(f"[DEBUG] Total de estados calculados: {len(states)}")
        print(f"[DEBUG] Longitud del DataFrame original: {len(data)}")
        print(f"[DEBUG] Rango de fechas: {data.index.min()} - {data.index.max()}")
        print(f"[DEBUG] Total de filas enviadas al modelo HMM: {len(features)}")

        # Crear una figura con dos subplots
        fig, axs = plt.subplots(3, 1, figsize=(12, 12), gridspec_kw={'height_ratios': [1, 2, 1]})
        
        # 1. Graficar el heatmap de la matriz de transición
        print("[INFO] Matriz de transición (transmat_):")
        print(self.hmm_model.transmat_)
        try:
            import seaborn as sns
            sns.heatmap(
                self.hmm_model.transmat_,
                annot=True,
                fmt=".2f",
                cmap="coolwarm",
                xticklabels=[f"State {i}" for i in range(self.hmm_model.n_components)],
                yticklabels=[f"State {i}" for i in range(self.hmm_model.n_components)],
                ax=axs[0]
            )
            axs[0].set_title("Matriz de Transición del Modelo HMM")
            axs[0].set_xlabel("Estado siguiente")
            axs[0].set_ylabel("Estado actual")
        except ImportError:
            print("[WARNING] seaborn no está instalado. Instálalo para visualizar la matriz de transición.")

        # 2. Graficar la evolución de los precios
        axs[1].plot(data.index, data['Close'], label='Precio (Close)', color='blue')
        axs[1].set_title("Evolución del Precio y Estados")
        axs[1].set_ylabel("Precio")
        axs[1].legend()
        axs[1].grid()

        # 3. Graficar los estados predichos
        scatter_colors = ['red', 'green', 'orange', 'purple', 'blue', 'black']
        for state in sorted(set(states)):
            indices = data.index[data['State'] == state]
            axs[2].scatter(indices, [state] * len(indices), label=f'State {state}',
                           color=scatter_colors[state % len(scatter_colors)], s=10)
        axs[2].set_title("Estados Predichos por el Modelo")
        axs[2].set_xlabel("Fecha")
        axs[2].set_ylabel("Estados")
        axs[2].legend()
        axs[2].grid()

        # Ajustar los márgenes y mostrar la figura
        plt.tight_layout()
        plt.show()




    def plot_states(self, data, states):
        """
        Grafica la evolución de los precios y los estados predichos por el modelo HMM.
        """
        print(f"[DEBUG] Total de filas enviadas al gráfico: {len(data)}")
        print(f"[DEBUG] Rango de fechas enviadas al gráfico: {data.index.min()} - {data.index.max()}")
        print(f"[DEBUG] Total de estados únicos: {len(set(states))}")

        # Verificar que el índice sea de tipo datetime
        if not isinstance(data.index, pd.DatetimeIndex):
            print("[ERROR] El índice de los datos no es de tipo datetime. Revisa los datos.")
            return

        # Configurar el gráfico
        fig, axs = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

        # Graficar los precios
        axs[0].plot(data.index, data['Close'], label='Precio (Close)', color='blue')
        axs[0].set_title("Evolución del Precio y Estados")
        axs[0].set_ylabel("Precio")
        axs[0].legend()
        axs[0].grid()

        # Graficar los estados predichos
        scatter_colors = ['red', 'green', 'orange', 'purple', 'blue', 'black']
        for state in sorted(set(states)):
            indices = data.index[data['State'] == state]
            axs[1].scatter(indices, [state] * len(indices), label=f'State {state}',
                           color=scatter_colors[state % len(scatter_colors)], s=10)
        axs[1].set_title("Estados Predichos por el Modelo")
        axs[1].set_xlabel("Fecha")
        axs[1].set_ylabel("Estados")
        axs[1].legend()
        axs[1].grid()

        # Crear slider para navegación (todo el rango de datos)
        ax_slider = plt.axes([0.1, 0.02, 0.8, 0.03], facecolor='lightgrey')
        slider = Slider(ax_slider, 'Fecha',
                        valmin=data.index.min().timestamp(),
                        valmax=data.index.max().timestamp(),
                        valinit=data.index.min().timestamp())

        def update_plot(val):
            """Actualiza el gráfico basándose en la fecha seleccionada por el slider."""
            selected_time = pd.to_datetime(val, unit='s')

            if selected_time in data.index:
                axs[0].cla()  # Limpiar y redibujar el gráfico principal
                axs[0].plot(data.index, data['Close'], label='Precio (Close)', color='blue')
                axs[0].axvline(selected_time, color='red', linestyle='--', label='Fecha seleccionada')
                axs[0].legend()
                axs[0].grid()

                axs[1].cla()  # Limpiar y redibujar los estados
                for state in sorted(set(states)):
                    indices = data.index[data['State'] == state]
                    axs[1].scatter(indices, [state] * len(indices), label=f'State {state}',
                                   color=scatter_colors[state % len(scatter_colors)], s=10)
                axs[1].axvline(selected_time, color='red', linestyle='--')
                axs[1].legend()
                axs[1].grid()

                fig.canvas.draw_idle()

        # Conectar el slider con la función de actualización
        slider.on_changed(update_plot)

        # Ajustar márgenes y mostrar el gráfico
        plt.subplots_adjust(top=0.95, bottom=0.15, left=0.1, right=0.95, hspace=0.3)
        plt.show()


if __name__ == "__main__":
    # Configurable variables
    ticker = "ETH-USD"
    interval = "1h"
    period = "1y"  # Período solicitado
    model_file = "NeoModel.pkl"
    features = ['Close', 'Volume', 'MACD', 'RSI', 'ATR']    # Asegúrate de incluir todos los features necesarios

    n_components = 4  # Número de componentes

    training_room = TrainingRoom(model_file=model_file, features=features, n_components=n_components)
    
    # Ruta al archivo JSON generado por InitialData.py
    json_file_path = f'/home/hobeat/MoneyMakers/Reports/{ticker.replace("-", "_")}_1Y1HM2.json'
    
    # Entrenar el modelo usando los datos cargados desde el JSON
    training_room.train_model(json_file_path)
