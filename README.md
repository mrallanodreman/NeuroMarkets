# NeuroMarkets 


diseñado para facilitar el desarrollo y la automatización de estrategias de trading basadas en el análisis avanzado de datos de mercado y el uso de Modelos de HiddenMarkov. Utiliza la API de Capital.com para realizar operaciones de trading, gestionar posiciones y acceder a datos de mercado en tiempo real.

El repositorio incluye los módulos basicos que permiten la integración de indicadores técnicos para la toma de decisiones de compra o venta, así como la gestión de posiciones abiertas y el seguimiento de su rentabilidad. Además, se pueden ajustar las estrategias de trading a través de modelos de aprendizaje automático, optimizando las decisiones comerciales según el estado del mercado.



🗃️ Estructura del Proyecto

El proyecto se organiza en varios módulos que interactúan entre sí para ofrecer las funcionalidades necesarias de trading, análisis y gestión de datos:

 🐍 Módulos Python: Scripts que gestionan la conexión con la API de Capital.com, operaciones de trading, análisis de mercado, y gestión de configuraciones.
  📑 Archivo JSON: Usado para almacenar las posiciones abiertas y su estado.


# 💽 Módulos y Funciones 

1. # EthConfig.py # - Configuración Global
Define las configuraciones globales del proyecto, como la clave de API, la URL base de la API y otros parámetros esenciales para la conexión.

Funciones:
load_config(file_path)
Carga configuraciones desde un archivo, como la clave de API y los parámetros del servidor de Capital.com.

save_config(config_data, file_path)
Guarda la configuración personalizada del usuario, incluyendo la clave de API y otros ajustes necesarios.

validate_api_key(api_key)
Verifica que la clave de API proporcionada sea válida y tenga los permisos necesarios para operar con la API.


2. EthSession.py - Gestión de Sesiones de Trading
Este módulo establece y mantiene una sesión activa con la API de Capital.com para realizar solicitudes de trading. Es fundamental para la autenticación y el manejo de la sesión.

Funciones:
create_session(api_key, api_password)
Inicia una nueva sesión utilizando la clave de API y la contraseña proporcionada. La sesión es necesaria para interactuar con la API.

get_session_details()
Recupera detalles de la sesión actual, como el token de autenticación y el ID de la cuenta activa.

refresh_session()
Mantiene la sesión activa o la renueva si ha expirado, garantizando que se pueda continuar operando sin interrupciones.



Gracias por la aclaración. A continuación, te proporciono una descripción más precisa de NeuroMarkets, basada en los detalles proporcionados:

NeuroMarkets
NeuroMarkets es un repositorio de GitHub orientado a la integración y automatización de estrategias de trading utilizando la API de Capital.com. El proyecto permite realizar operaciones de trading en tiempo real, obtener datos de mercado como precios, volúmenes y sentimiento del cliente, y gestionar posiciones y órdenes. NeuroMarkets también incluye la capacidad de almacenar y analizar datos históricos para optimizar y evaluar estrategias de inversión.

El repositorio está diseñado para facilitar la creación y personalización de bots de trading, automatizando la apertura y cierre de posiciones y la ejecución de órdenes bajo diferentes condiciones de mercado. Además, incluye módulos para gestionar la configuración, la sesión y la interacción con la API de Capital.com.

Estructura del Proyecto
El proyecto se organiza en varios módulos que interactúan entre sí para ofrecer las funcionalidades necesarias de trading, análisis y gestión de datos:

Módulos Python: Scripts que gestionan la conexión con la API de Capital.com, operaciones de trading, análisis de mercado, y gestión de configuraciones.
Archivo JSON: Usado para almacenar las posiciones abiertas y su estado.
Módulos y Funciones
1. EthSession.py - Gestión de Sesiones de Trading
Este módulo establece y mantiene una sesión activa con la API de Capital.com para realizar solicitudes de trading. Es fundamental para la autenticación y el manejo de la sesión.

Funciones:
create_session(api_key, api_password)
Inicia una nueva sesión utilizando la clave de API y la contraseña proporcionada. La sesión es necesaria para interactuar con la API.

get_session_details()
Recupera detalles de la sesión actual, como el token de autenticación y el ID de la cuenta activa.

refresh_session()
Mantiene la sesión activa o la renueva si ha expirado, garantizando que se pueda continuar operando sin interrupciones.

2. EthConfig.py - Configuración Global
Define las configuraciones globales del proyecto, como la clave de API, la URL base de la API y otros parámetros esenciales para la conexión.

Funciones:
load_config(file_path)
Carga configuraciones desde un archivo, como la clave de API y los parámetros del servidor de Capital.com.

save_config(config_data, file_path)
Guarda la configuración personalizada del usuario, incluyendo la clave de API y otros ajustes necesarios.

validate_api_key(api_key)
Verifica que la clave de API proporcionada sea válida y tenga los permisos necesarios para operar con la API.

3. EthOperator.py - Operaciones de Trading
Este módulo se encarga de realizar las operaciones de trading: abrir, cerrar posiciones y colocar órdenes. Permite la ejecución de transacciones en los mercados de forma automatizada.

Funciones:
open_position(direction, epic, size, stop_level, profit_level)
Abre una posición de trading (compra o venta) en el mercado, con parámetros como el tamaño de la posición, el nivel de stop loss y el nivel de take profit.

close_position(deal_reference)
Cierra una posición abierta previamente utilizando el identificador de la operación.

place_order(order_type, epic, size, level)
Coloca una orden de compra o venta en el mercado, especificando si es una orden de tipo Límite o Stop.

get_order_history()
Recupera el historial completo de las órdenes realizadas, proporcionando detalles sobre las transacciones pasadas.


4. EthStrategy.py - Estrategias de Trading
Define y aplica estrategias de trading basadas en datos históricos o en tiempo real. Este módulo permite ajustar y optimizar las estrategias de inversión.

Funciones:
apply_strategy(data, strategy)
Aplica una estrategia de trading predefinida (como RSI, medias móviles, etc.) a los datos de mercado para generar señales de compra o venta.

evaluate_strategy(strategy, historical_data)
Evalúa el rendimiento de una estrategia utilizando datos históricos, analizando las decisiones pasadas y los resultados obtenidos.

optimize_strategy(strategy, data)
Optimiza los parámetros de la estrategia de trading utilizando técnicas de backtesting para encontrar la configuración que ofrezca los mejores resultados.



5. DataEth.py - Gestión de Datos de Mercado
Este módulo permite obtener y analizar datos de mercado en tiempo real, además de recuperar información histórica de precios y sentiment analysis.

Funciones:
get_real_time_data(epic)
Obtiene el precio en tiempo real de un activo específico, como acciones, criptomonedas, o commodities. El epic es el identificador del activo (por ejemplo, "SILVER", "BTCUSD").

get_historical_data(epic, from_date, to_date)
Recupera datos históricos sobre el precio de un activo, útil para análisis técnico y backtesting.

get_market_info()
Proporciona información sobre el estado actual de los mercados, como precios, tendencias y volúmenes de operaciones.


Gracias por la aclaración. A continuación, te proporciono una descripción más precisa de NeuroMarkets, basada en los detalles proporcionados:

NeuroMarkets
NeuroMarkets es un repositorio de GitHub orientado a la integración y automatización de estrategias de trading utilizando la API de Capital.com. El proyecto permite realizar operaciones de trading en tiempo real, obtener datos de mercado como precios, volúmenes y sentimiento del cliente, y gestionar posiciones y órdenes. NeuroMarkets también incluye la capacidad de almacenar y analizar datos históricos para optimizar y evaluar estrategias de inversión.

El repositorio está diseñado para facilitar la creación y personalización de bots de trading, automatizando la apertura y cierre de posiciones y la ejecución de órdenes bajo diferentes condiciones de mercado. Además, incluye módulos para gestionar la configuración, la sesión y la interacción con la API de Capital.com.

Estructura del Proyecto
El proyecto se organiza en varios módulos que interactúan entre sí para ofrecer las funcionalidades necesarias de trading, análisis y gestión de datos:

Módulos Python: Scripts que gestionan la conexión con la API de Capital.com, operaciones de trading, análisis de mercado, y gestión de configuraciones.
Archivo JSON: Usado para almacenar las posiciones abiertas y su estado.
Módulos y Funciones
1. EthSession.py - Gestión de Sesiones de Trading
Este módulo establece y mantiene una sesión activa con la API de Capital.com para realizar solicitudes de trading. Es fundamental para la autenticación y el manejo de la sesión.

Funciones:
create_session(api_key, api_password)
Inicia una nueva sesión utilizando la clave de API y la contraseña proporcionada. La sesión es necesaria para interactuar con la API.

get_session_details()
Recupera detalles de la sesión actual, como el token de autenticación y el ID de la cuenta activa.

refresh_session()
Mantiene la sesión activa o la renueva si ha expirado, garantizando que se pueda continuar operando sin interrupciones.

2. EthConfig.py - Configuración Global
Define las configuraciones globales del proyecto, como la clave de API, la URL base de la API y otros parámetros esenciales para la conexión.

Funciones:
load_config(file_path)
Carga configuraciones desde un archivo, como la clave de API y los parámetros del servidor de Capital.com.

save_config(config_data, file_path)
Guarda la configuración personalizada del usuario, incluyendo la clave de API y otros ajustes necesarios.

validate_api_key(api_key)
Verifica que la clave de API proporcionada sea válida y tenga los permisos necesarios para operar con la API.

3. EthOperator.py - Operaciones de Trading
Este módulo se encarga de realizar las operaciones de trading: abrir, cerrar posiciones y colocar órdenes. Permite la ejecución de transacciones en los mercados de forma automatizada.

Funciones:
open_position(direction, epic, size, stop_level, profit_level)
Abre una posición de trading (compra o venta) en el mercado, con parámetros como el tamaño de la posición, el nivel de stop loss y el nivel de take profit.

close_position(deal_reference)
Cierra una posición abierta previamente utilizando el identificador de la operación.

place_order(order_type, epic, size, level)
Coloca una orden de compra o venta en el mercado, especificando si es una orden de tipo Límite o Stop.

get_order_history()
Recupera el historial completo de las órdenes realizadas, proporcionando detalles sobre las transacciones pasadas.

4. EthStrategy.py - Estrategias de Trading
Define y aplica estrategias de trading basadas en datos históricos o en tiempo real. Este módulo permite ajustar y optimizar las estrategias de inversión.

Funciones:
apply_strategy(data, strategy)
Aplica una estrategia de trading predefinida (como RSI, medias móviles, etc.) a los datos de mercado para generar señales de compra o venta.

evaluate_strategy(strategy, historical_data)
Evalúa el rendimiento de una estrategia utilizando datos históricos, analizando las decisiones pasadas y los resultados obtenidos.

optimize_strategy(strategy, data)
Optimiza los parámetros de la estrategia de trading utilizando técnicas de backtesting para encontrar la configuración que ofrezca los mejores resultados.

5. DataEth.py - Gestión de Datos de Mercado
Este módulo permite obtener y analizar datos de mercado en tiempo real, además de recuperar información histórica de precios y sentiment analysis.

Funciones:
get_real_time_data(epic)
Obtiene el precio en tiempo real de un activo específico, como acciones, criptomonedas, o commodities. El epic es el identificador del activo (por ejemplo, "SILVER", "BTCUSD").

get_historical_data(epic, from_date, to_date)
Recupera datos históricos sobre el precio de un activo, útil para análisis técnico y backtesting.

get_market_info()
Proporciona información sobre el estado actual de los mercados, como precios, tendencias y volúmenes de operaciones.

6. position_tracker.json - Seguimiento de Posiciones
Archivo JSON que almacena las posiciones abiertas, incluyendo detalles sobre las órdenes activas y su estado actual.

Contenido:
dealReference: Identificador único de la operación.
direction: Dirección de la operación (compra/venta).
epic: Activo relacionado (por ejemplo, "SILVER").
size: Tamaño de la posición.
stopLevel: Nivel de stop loss.
profitLevel: Nivel de take profit.
status: Estado de la posición (abierta, cerrada, etc.).
