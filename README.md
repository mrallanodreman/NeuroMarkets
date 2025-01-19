# NeuroMarkets 


diseñado para facilitar el desarrollo y la automatización de estrategias de trading basadas en el análisis avanzado de datos de mercado y el uso de Modelos de HiddenMarkov. Utiliza la API de Capital.com para realizar operaciones de trading, gestionar posiciones y acceder a datos de mercado en tiempo real.

El repositorio incluye los módulos basicos que permiten la integración de indicadores técnicos para la toma de decisiones de compra o venta, así como la gestión de posiciones abiertas y el seguimiento de su rentabilidad. Además, se pueden ajustar las estrategias de trading a través de modelos de aprendizaje automático, optimizando las decisiones comerciales según el estado del mercado.

#  Lista De Bots funcionales :
- 🗿 EthOperator - Ethereum bot - Bullysh 


# 🗃️ Estructura del Proyecto : 

#### El proyecto se organiza en varios módulos que interactúan entre sí para ofrecer las funcionalidades necesarias de trading, análisis y gestión de datos


# ‼  Cómo Empezar ‼ 

Requisitos:

Paquetes de Python necesarios: 

 > pip install -r requirements.txt

- json

- pandas

- ta (para indicadores técnicos)

- yfinance (para obtener datos de Yahoo Finance)

- PyQt5 (si se desea utilizar la interfaz gráfica)


## ⚙️ Configuración Inicial: ⚙️
- Registra una API Key en Capital.com y habilita la autenticación de dos factores.
- Configura las credenciales en el archivo EthConfig.py.
- Ejecuta el script EthOperator.py para iniciar el bot 🗿


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

## ** 💲 Allan Odreman **
