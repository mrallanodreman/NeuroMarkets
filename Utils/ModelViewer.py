import pickle
import json
import os

def find_model_file(directory, filename="NeoModel.pkl"):
    """
    Busca el archivo de modelo en un directorio y sus subdirectorios.
    :param directory: Directorio raíz donde buscar.
    :param filename: Nombre del archivo que se busca.
    :return: Ruta completa del archivo si se encuentra, None si no.
    """
    print(f"[INFO] Buscando '{filename}' en el directorio '{directory}'...")
    for root, dirs, files in os.walk(directory):
        if filename in files:
            file_path = os.path.join(root, filename)
            print(f"[INFO] Archivo encontrado: {file_path}")
            return file_path
    print(f"[ERROR] No se encontró '{filename}' en el directorio '{directory}'.")
    return None


def load_model(file_path):
    """
    Carga un archivo .pkl y devuelve su contenido.
    """
    if not os.path.exists(file_path):
        print(f"[ERROR] El archivo {file_path} no existe.")
        return None
    
    try:
        with open(file_path, "rb") as file:
            model_data = pickle.load(file)
        print(f"[INFO] Modelo cargado exitosamente desde {file_path}.")
        return model_data
    except Exception as e:
        print(f"[ERROR] No se pudo cargar el modelo: {e}")
        return None


def display_scaler_stats(scaler_stats):
    """
    Muestra información detallada de las estadísticas del escalador.
    """
    print("\n[INFO] Estadísticas del Escalador (scaler_stats):")
    if not scaler_stats:
        print("  - [ERROR] 'scaler_stats' está vacío o no está definido.")
        return
    
    mean = scaler_stats.get("mean")
    scale = scaler_stats.get("scale")
    
    if mean is not None and scale is not None:
        print(f"  - Media ('mean'): {mean}")
        print(f"  - Escala ('scale'): {scale}")
    else:
        print("  - [ERROR] 'scaler_stats' no contiene 'mean' o 'scale'.")


def display_model_details(model_data):
    """
    Muestra información detallada sobre el modelo cargado.
    """
    print("\n[INFO] Información del Modelo Cargado:")
    if not isinstance(model_data, dict):
        print("  - [ERROR] El modelo cargado no es un diccionario.")
        return

    # Mostrar todas las claves principales del modelo
    print(f"  - Claves disponibles: {list(model_data.keys())}")

    # Mostrar el modelo en sí
    model = model_data.get("model")
    if model:
        print("\n[INFO] Detalles del modelo:")
        print(f"  - Tipo de modelo: {type(model)}")
        print(f"  - Atributos disponibles: {dir(model)}")
    else:
        print("  - [ERROR] El modelo no está presente en los datos cargados.")

    # Mostrar características (features)
    features = model_data.get("features", [])
    print("\n[INFO] Características (features):")
    if features:
        print(f"  - Total: {len(features)}")
        print(f"  - Lista: {features}")
    else:
        print("  - [ERROR] 'features' no está definido o está vacío.")

    # Mostrar estadísticas del escalador
    scaler_stats = model_data.get("scaler_stats", {})
    display_scaler_stats(scaler_stats)


def main():
    """
    Script principal para buscar, cargar y mostrar información sobre un modelo.
    """
    print("========================================")
    print("          Model Viewer Utility          ")
    print("========================================")

    # Directorio base donde buscar el modelo
    base_directory = "/home/hobeat/MoneyMakers/Utils/Reports"  # Cambia este directorio si es necesario
    model_file_name = "NeoModel.pkl"

    # Buscar el archivo del modelo
    model_file_path = find_model_file(base_directory, model_file_name)
    if not model_file_path:
        print("[ERROR] No se pudo encontrar el modelo. Saliendo del programa.")
        return

    # Cargar modelo
    model_data = load_model(model_file_path)
    if model_data is None:
        print("[ERROR] No se pudo cargar el modelo. Saliendo del programa.")
        return

    # Mostrar información del modelo
    display_model_details(model_data)
    
    print("\n[INFO] Revisión del modelo completada.")


if __name__ == "__main__":
    main()
