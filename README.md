# NeuroMarkets               


Diseñado para facilitar el desarrollo y la automatización de estrategias de trading basadas en el análisis avanzado de datos de mercado y el uso de Modelos de HiddenMarkov. Utiliza la API de Capital.com para realizar operaciones de trading, gestionar posiciones y acceder a datos de mercado en tiempo real.

El repositorio incluye los módulos basicos que permiten la integración de indicadores técnicos para la toma de decisiones de compra o venta, así como la gestión de posiciones abiertas y el seguimiento de su rentabilidad. Además, se pueden ajustar las estrategias de trading a través de modelos de aprendizaje automático, optimizando las decisiones comerciales según el estado del mercado.

#  Lista De Bots funcionales :
- 🗿 EthOperator - Ethereum bot - Bullysh Only 
- 🦈 SharkBoy - Ethereum Bot - Shorts Only

#  Lista De funciones generales  :
- Soporte de Api Capital
- Soporte MultiCuenta

# 🗃️ Estructura del Proyecto : 

#### El proyecto se organiza en varios módulos que interactúan entre sí para ofrecer las funcionalidades necesarias de trading, análisis y gestión de datos

###### ⚠️  Necesitas crear una carpeta llamada /Reports  e incluir los siguientes archivos  ⚠️  

 > ETH_USD_historical_data.json  

 > ETH_USD_1Y1HM2.json

###### ⚠️ El resto de archivos deben estar en una misma ubicacion juntos ⚠️  



# ‼  Cómo Empezar ‼ 

Requisitos: 

- Crea un Enviroment unicamente para tu Bot. 
- Instala las dependencias
  
Paquetes de Python necesarios: 

- json

- pandas

- ta (para indicadores técnicos)

- yfinance (para obtener datos de Yahoo Finance)

- PyQt5 (si se desea utilizar la interfaz gráfica)

Puedes instalarlos de forma automatica con el comando 

> pip install -r requirements.txt 

## ⚙️ Configuración Inicial: ⚙️

- Registra una API Key en Capital.com y habilita la autenticación de dos factores.
- Configura las credenciales en el archivo EthConfig.py.
- Ejecuta el script EthSession.py para iniciar la autenticacion y obtener el AccountID de tu cuenta de trading.
- Al obtener el AccountId Configuralo dentro de los sigueintes archivos : 
  
> EthSession.py  - Linea 287 - capital_ops.set_account_id (" Tu Account ID " )

> EthOperator.py - Linea 31 -  self.account_id = "Tu account ID "


- Abre una posicion de prueba y confirma ejecutando nuevamente EthSession.py que estas obteniendo las posiciones correcamente para tu cuenta
  Una vez confirmado que tu EthSessions.py obtiene correctamente el saldo y las posicones de tu cuenta, estas listo. 

>  Ejecuta EthOperator.py 


# 💽 Módulos y Funciones 

### ⚙️ 1. EthConfig.py - Configuración Global
Define las configuraciones globales del proyecto, como la clave de API, la URL base de la API y otros parámetros esenciales para la conexión.

### ⚙️ 2. EthSession.py - Gestión de Sesiones de Trading

Este módulo establece y mantiene una sesión activa con la API de Capital.com para realizar solicitudes de trading. Es fundamental para la autenticación y el manejo de la sesión.


### ⚙️  3. EthOperator.py - Operaciones de Trading
Este módulo se encarga de realizar las operaciones de trading: abrir, cerrar posiciones y colocar órdenes. Permite la ejecución de transacciones en los mercados de forma automatizada.

### ⚙️  4.  EthStrategy.py - Estrategias de Trading
Define y aplica estrategias de trading basadas en datos históricos o en tiempo real. Este módulo permite ajustar y optimizar las estrategias de inversión.


### ⚙️ 5. DataEth.py - Gestión de Datos de Mercado
Este módulo permite obtener y analizar datos de mercado en tiempo real, además de recuperar información histórica de precios y sentiment analysis.


### ⚙️  6. position_tracker.json - Seguimiento de Posiciones
Archivo JSON que almacena las posiciones abiertas, incluyendo detalles sobre las órdenes activas y su estado actual.

Contenido:

- dealReference: Identificador único de la operación.
- direction: Dirección de la operación (compra/venta).
- epic: Activo relacionado (por ejemplo, "SILVER").
- size: Tamaño de la posición.
- stopLevel: Nivel de stop loss.
- profitLevel: Nivel de take profit.
- status: Estado de la posición (abierta, cerrada, etc.).

---
### Entrenamiento y Administracion de Modelos 🚀 TrainingRoom & Model Viewer:

Entender los estados (clusters de comportamiento)

Cada estado representa un patrón recurrente en las características del mercado (Close, Volume, MACD, RSI, ATR). Analizando las estadísticas del modelo (means_ y covars_), puedes identificar qué tipo de comportamiento o volatilidad corresponde a cada estado

Cada activo, accion  o crypto a analizar, necesita un modelo nuevo, ya que estos pueden detectar los patrones unicamente basados en los datos de entrenamiento 



🌟 TrainingRoom

Es tu asistente para entrenar modelos Hidden Markov Model (HMM) usando datos financieros como precios, volumen, indicadores técnicos (RSI, MACD, ATR) y más. Aquí hay un resumen de lo que puedes hacer:

1️⃣ Entrenamiento de Modelos

Carga un archivo JSON con tus datos históricos procesados.

Esto puedes configurarlo en el archivo 

> DataEth.py


### ❕ Como Comprender los Estados de prediccion ❕ 


- means_: Representa el valor promedio de cada característica para cada estado.
- covars_: Representa la variabilidad (varianzas) de cada característica en cada estado.
- Estados: Cada uno corresponde a un régimen de mercado o patrón, como:
- Estado 0: Mercado en calma (baja volatilidad y cambios pequeños).
- Estado 1: Mercado con tendencias fuertes (alta volatilidad y volumen).
- Estado 2: Correcciones o consolidaciones.
- Estado 3: Máxima volatilidad o movimientos abruptos.

### 🎯 Cómo usarlo:

### 🔧 Variables Configurables
Modifica las siguientes variables según tus necesidades de análisis:

Ticker y Parámetros de Mercado

- ticker: El símbolo del activo que deseas analizar. Ejemplo: "ETH-USD".
- interval: Intervalo de tiempo entre puntos de datos. Ejemplo: "1h" (una hora).
- period: Duración del histórico que quieres usar. Ejemplo: "1y" (un año).

Características (Features)
Asegúrate de incluir todos los indicadores y columnas relevantes para tu modelo HMM.
Ejemplo:

###### Ejemplo: 

    features = ['Close', 'Volume', 'MACD', 'RSI', 'ATR']

### 🔎 ModelViewer - Visor de modelos Pkl. 
Es una herramienta para que poder verificar que el entranmiento es correcto. ChatGpt puede analziar cada entrenamiento sin problemas. 

###### Directorio base donde buscar el modelo 

    base_directory = "  Aqui debes colocar la ruta a tu Modelo.pkl "

### Luego puedes ejecutar 

> ModelViewer.py


#
### 📚  Recursos Adicionales 📚  

- Que son los Modelos de Hiden markov ?       | https://www.youtube.com/watch?v=lnOkyvWcAtQ
- Que es un indicador tecnico?                | RSI : https://www.youtube.com/watch?v=m-r-ZfD7emc
- Que es un indicador tecnico?                | MACD : https://www.youtube.com/watch?v=feXocPTRxMQ
- Como se usa el volumen dentro del traiding? | https://www.youtube.com/watch?v=vBGtXSmtkDk
- Documentacion de la api de Capital | https://open-api.capital.com/ 

