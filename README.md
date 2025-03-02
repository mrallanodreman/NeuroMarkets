# NeuroMarkets               


Diseñado para facilitar el desarrollo y la automatización de estrategias de trading basadas en el análisis avanzado de datos de mercado y el uso de Modelos de HiddenMarkov. Utiliza la API de Capital.com para realizar operaciones de trading, gestionar posiciones y acceder a datos de mercado en tiempo real.

El repositorio incluye los módulos basicos que permiten la integración de indicadores técnicos para la toma de decisiones de compra o venta, así como la gestión de posiciones abiertas y el seguimiento de su rentabilidad. Además, se pueden ajustar las estrategias de trading a través de modelos de aprendizaje automático, optimizando las decisiones comerciales según el estado del mercado.

#  Lista De Bots funcionales :
- 🐂 BullBOy - Ethereum bot - Bullysh Only 
- 🦈 SharkBoy - Ethereum Bot - Shorts Only

#  Lista De funciones generales  :
- Soporte de Api Capital
- Soporte MultiCuenta

# 🗃️ Estructura del Proyecto : 

#### El proyecto se organiza en varios módulos que interactúan entre sí para ofrecer las funcionalidades necesarias de trading, análisis y gestión de datos

# ‼  Cómo Empezar ‼ 

Requisitos: 

- Crea un Enviroment unicamente para tu Bot.

- Instala las dependencias

  > pip install -r requirements.txt

  
Paquetes de Python necesarios: 

- Python 3.7 o superior
- Librerías Python:
  - `requests`
  - `pandas`
  - `numpy`
  - `PyQt5`
  - `rich`
  - `colorama`
  - `ta`
  - `yfinance`
- Acceso a la API de Capital.com con  credenciales correspondientes.

## ⚙️ Configuración Inicial: ⚙️

Configura tus credenciales:

Ejecuta el autoconfigurador para actualizar las credenciales de forma interactiva:

> python EthConfig.py

Al ejecutar el comando:
Se inicia un script interactivo que se encarga de configurar las credenciales y parámetros necesarios para que el bot se comunique correctamente con la API de Capital.com. Aquí tienes una explicación detallada de lo que hace este proceso:


# 💽 Módulos y Funciones 

### ⚙️ 1. EthConfig.py - Configuración Global
Define las configuraciones globales del proyecto, como la clave de API, la URL base de la API y otros parámetros esenciales para la conexión.

### ⚙️ 2. EthSession.py - Gestión de Sesiones de Trading

Este módulo establece y mantiene una sesión activa con la API de Capital.com para realizar solicitudes de trading. Es fundamental para la autenticación y el manejo de la sesión.


### ⚙️  3. EthOperator.py - Operaciones de Trading
Este módulo se encarga de realizar las operaciones de trading: abrir, cerrar posiciones y colocar órdenes. Permite la ejecución de transacciones en los mercados de forma automatizada.

### ⚙️  4.  EthStrategy.py - Estrategias de Trading
Define y aplica estrategias de trading basadas en datos históricos en tiempo real. Este módulo permite ajustar y optimizar las estrategias de inversión.


### ⚙️ 5. DataEth.py - Gestión de Datos de Mercado
Este módulo permite obtener y analizar datos de mercado en tiempo real, además de recuperar información histórica de precios y sentiment analysis.


### ⚙️  6. position_tracker.json - Seguimiento de Posiciones
Archivo JSON que almacena las posiciones abiertas, incluyendo detalles sobre las órdenes activas y su estado actual.



### ⚙️  7 Visualización Técnica (VisorTecnico.py):
Proporciona herramientas para el análisis  de indicadores técnicos... 

## ⚙️ DEPLOYMENTS ⚙️
Algunas herramientas que ayudan en el trading y monitoreo de mecados..


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



### 📚  Recursos Adicionales 📚  

- Que son los Modelos de Hiden markov ?       | https://www.youtube.com/watch?v=lnOkyvWcAtQ
- Que es un indicador tecnico?                | RSI : https://www.youtube.com/watch?v=m-r-ZfD7emc
- Que es un indicador tecnico?                | MACD : https://www.youtube.com/watch?v=feXocPTRxMQ
- Como se usa el volumen dentro del traiding? | https://www.youtube.com/watch?v=vBGtXSmtkDk
- Documentacion de la api de Capital          | https://open-api.capital.com/ 

