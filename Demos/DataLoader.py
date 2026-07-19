"""
DataLoader - Sistema híbrido Parquet + JSON para carga eficiente de datos
Compatible con toda la arquitectura existente del proyecto.
"""
import os
import json
import pandas as pd
from datetime import datetime, timedelta
import pytz


class DataLoader:
    """
    Cargador de datos híbrido que soporta:
    - Parquet (rápido, eficiente)
    - JSON (legacy, fallback)
    - Live updates (últimas 100 velas)
    """

    def __init__(self, reports_dir=None):
        if reports_dir is None:
            reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Reports")
        self.reports_dir = reports_dir

        # Rutas de archivos
        self.htf_parquet = os.path.join(self.reports_dir, "ethusd_htf_immutable.parquet")
        self.ltf_parquet = os.path.join(self.reports_dir, "ethusd_ltf_7d.parquet")
        self.live_json = os.path.join(self.reports_dir, "ethusd_live.json")
        self.legacy_json = os.path.join(self.reports_dir, "ETHUSD_CapitalData.json")

    def load_historical_data(self):
        """
        Carga datos históricos (HTF) y datos de 1M (LTF).
        Prioriza Parquet, fallback a JSON legacy.

        Returns:
            tuple: (historical_data_df, data_df) - ambos con índice Datetime
        """
        ui = getattr(self, 'ui', None)
        if ui:
            ui.add_log(f"[INFO] 🔍 Buscando datos en {self.reports_dir}...", style="dim")

        # Intentar cargar desde Parquet (preferido)
        if os.path.exists(self.htf_parquet) and os.path.exists(self.ltf_parquet):
            try:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log("[INFO] 📊 Cargando desde Parquet (modo eficiente)...", style="dim")
                historical_data = pd.read_parquet(self.htf_parquet)
                ltf_base = pd.read_parquet(self.ltf_parquet)
                # Asegurar que los índices sean tz-aware (UTC)
                if historical_data.index.tz is None:
                    historical_data.index = historical_data.index.tz_localize('UTC')
                if ltf_base.index.tz is None:
                    ltf_base.index = ltf_base.index.tz_localize('UTC')

                # Merge con live data si existe
                data = self._merge_live_data(ltf_base)

                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[INFO] ✅ Parquet OK: {len(historical_data)} HTF + {len(data)} LTF", style="dim")

                # Si LTF está vacío, crear DataFrame con columnas esperadas
                if data.empty:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log("[WARNING] ⚠️ LTF vacío - se usará get_1m_candles() en tiempo real", style="dim")
                    # Crear DataFrame vacío con columnas esperadas
                    data = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume'])
                    data.index = pd.DatetimeIndex([], name='Datetime')

                return historical_data, data

            except Exception as e:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[WARNING] ⚠️ Error al leer Parquet: {e}", style="dim")
                    ui.add_log("[INFO] 🔄 Intentando fallback a JSON...", style="dim")

        # Fallback: cargar desde JSON legacy
        if os.path.exists(self.legacy_json):
            try:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log("[INFO] 📄 Cargando desde JSON (modo legacy)...", style="dim")
                with open(self.legacy_json, "r") as f:
                    json_data = json.load(f)

                if "historical_data" not in json_data or ("data" not in json_data and "ltf_data" not in json_data):
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log("[ERROR] ❌ JSON no contiene claves esperadas", style="dim")
                    return pd.DataFrame(), pd.DataFrame()

                historical_data = pd.DataFrame(json_data["historical_data"])
                # Buscar LTF data en orden de prioridad: ltf_data (nuevo) > data (legacy)
                ltf_key = "ltf_data" if "ltf_data" in json_data else "data"
                data = pd.DataFrame(json_data.get(ltf_key, []))

                # Si data está vacío, crear DataFrame con columnas esperadas
                if data.empty:
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log("[WARNING] ⚠️ LTF vacío en JSON - se usará get_1m_candles() en tiempo real", style="dim")
                    data = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume'])
                    data.index = pd.DatetimeIndex([], name='Datetime')

                # Procesar HTF - manejar diferentes formatos de timestamp
                datetime_col_htf = None
                if "timestamp" in historical_data.columns:  # NUEVO: nuestro formato
                    datetime_col_htf = "timestamp"
                elif "snapshotTime" in historical_data.columns:  # Capital.com API
                    datetime_col_htf = "snapshotTime"
                elif "Datetime" in historical_data.columns:  # Legacy export
                    datetime_col_htf = "Datetime"

                if datetime_col_htf:
                    # Si es timestamp en ms, unit="ms"; si es ISO string, auto-detecta
                    if historical_data[datetime_col_htf].dtype == 'int64':
                        historical_data["Datetime"] = pd.to_datetime(historical_data[datetime_col_htf], unit="ms", errors="coerce")
                    else:
                        historical_data["Datetime"] = pd.to_datetime(historical_data[datetime_col_htf], errors="coerce")

                    historical_data.dropna(subset=["Datetime"], inplace=True)

                    # 🔥 ELIMINAR DUPLICADOS ANTES de set_index (esto es lo que faltaba)
                    historical_data = historical_data[~historical_data["Datetime"].duplicated(keep='last')]

                    historical_data.set_index("Datetime", inplace=True)
                    historical_data.sort_index(inplace=True)

                # Reportar cantidad de registros en JSON
                n_hist = len(json_data["historical_data"]) if "historical_data" in json_data else 0
                n_ltf = len(json_data.get("ltf_data", json_data.get("data", [])))
                if ui:
                    ui.add_log(f"[DEBUG] JSON contiene: {n_hist} HTF, {n_ltf} LTF (clave: {ltf_key})", style="dim")

                # Verificación redundante eliminada (ya se hizo arriba)

                # Nota: `historical_data` y `data` ya fueron creados y procesados arriba.
                # Detectar columna de tiempo para LTF (solo si data no está vacío)
                if not data.empty:
                    datetime_col_ltf = None
                    if "timestamp" in data.columns:  # NUEVO: nuestro formato
                        datetime_col_ltf = "timestamp"
                    elif "Open_time" in data.columns:  # Binance formato
                        datetime_col_ltf = "Open_time"
                    elif "snapshotTime" in data.columns:  # Capital.com API
                        datetime_col_ltf = "snapshotTime"
                    elif "Datetime" in data.columns:  # Legacy export
                        datetime_col_ltf = "Datetime"

                    if not datetime_col_ltf:
                        msg = "[ERROR] ❌ No se encontró ninguna columna de tiempo válida en LTF ('Open_time', 'snapshotTime', 'Datetime')"
                        if ui:
                            ui.add_log(msg, style="dim")
                        # NO devolver vacío, solo alertar
                        # Crear DataFrame vacío con índice correcto
                        data = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume'])
                        data.index = pd.DatetimeIndex([], name='Datetime')

                    if not datetime_col_ltf:
                        msg = "[ERROR] ❌ No se encontró columna de tiempo válida en LTF ('timestamp', 'Open_time', 'snapshotTime', 'Datetime')"
                        if ui:
                            ui.add_log(msg, style="dim")
                        # NO devolver vacío, solo alertar
                        # Crear DataFrame vacío con índice correcto
                        data = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume'])
                        data.index = pd.DatetimeIndex([], name='Datetime')
                    else:
                        # Procesar columna de tiempo
                        if data[datetime_col_ltf].dtype == 'int64':
                            data["Datetime"] = pd.to_datetime(data[datetime_col_ltf], unit="ms", errors="coerce")
                        else:
                            data["Datetime"] = pd.to_datetime(data[datetime_col_ltf], errors="coerce")
                        data.dropna(subset=["Datetime"], inplace=True)
                        # 🔥 ELIMINAR DUPLICADOS ANTES de set_index
                        data = data[~data["Datetime"].duplicated(keep='last')]
                        data.set_index("Datetime", inplace=True)
                        data.sort_index(inplace=True)

                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[INFO] ✅ JSON OK: {len(historical_data)} HTF + {len(data)} LTF", style="dim")

                # Devolver datos procesados
                return historical_data, data

            except Exception as e:
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[ERROR] ❌ Error al leer JSON: {e}", style="dim")

        # Si llegamos aquí, no se pudo cargar ningún archivo
        return pd.DataFrame(), pd.DataFrame()

    def _merge_live_data(self, ltf_base):
        """
        Agrega datos live (últimas 100 velas) al LTF base.

        Args:
            ltf_base: DataFrame LTF desde Parquet

        Returns:
            DataFrame: LTF actualizado con datos live
        """
        try:
            if not os.path.exists(self.live_json):
                # No hay datos live, retornar base
                return ltf_base
            with open(self.live_json, "r") as f:
                live_data = json.load(f)
            if not live_data:
                return ltf_base
            # Convertir a DataFrame
            live_df = pd.DataFrame(live_data)
            if "Datetime" in live_df.columns:
                live_df["Datetime"] = pd.to_datetime(live_df["Datetime"], unit="ms", errors="coerce")
                live_df.dropna(subset=["Datetime"], inplace=True)
                # 🔥 ELIMINAR DUPLICADOS ANTES de set_index
                live_df = live_df[~live_df["Datetime"].duplicated(keep='last')]
                live_df.set_index("Datetime", inplace=True)
                if live_df.index.tz is None:
                    live_df.index = live_df.index.tz_localize('UTC')
                live_df.sort_index(inplace=True)
            # Merge: priorizar live data (drop duplicates keepin last)
            merged = pd.concat([ltf_base, live_df])
            merged = merged[~merged.index.duplicated(keep='last')]
            merged.sort_index(inplace=True)
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[INFO] 🔄 Merged {len(live_df)} velas live", style="dim")
            return merged
        except Exception as e:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[WARNING] ⚠️ Error al mergear live data: {e}", style="dim")
            return ltf_base

    def save_to_parquet(self, historical_data, data, update_mode="full"):
        """
        Guarda datos en formato Parquet.

        Args:
            historical_data: DataFrame HTF
            data: DataFrame LTF
            update_mode: "full" (regenerar todo) o "append" (solo nuevas velas)
        """
        os.makedirs(self.reports_dir, exist_ok=True)

        try:
            if update_mode == "full":
                # Regenerar archivos completos
                historical_data.to_parquet(self.htf_parquet, compression='snappy')
                data.to_parquet(self.ltf_parquet, compression='snappy')
                ui = getattr(self, 'ui', None)
                if ui:
                    ui.add_log(f"[INFO] ✅ Parquet guardado: {len(historical_data)} HTF + {len(data)} LTF", style="dim")
            elif update_mode == "append":
                # Append incremental (HTF)
                if os.path.exists(self.htf_parquet):
                    existing_htf = pd.read_parquet(self.htf_parquet)
                    if existing_htf.index.tz is None:
                        existing_htf.index = existing_htf.index.tz_localize('UTC')
                    # Solo agregar nuevas velas
                    new_htf = historical_data[~historical_data.index.isin(existing_htf.index)]
                    if not new_htf.empty:
                        updated_htf = pd.concat([existing_htf, new_htf])
                        updated_htf.sort_index(inplace=True)
                        updated_htf.to_parquet(self.htf_parquet, compression='snappy')
                        ui = getattr(self, 'ui', None)
                        if ui:
                            ui.add_log(f"[INFO] ✅ HTF actualizado: +{len(new_htf)} velas", style="dim")
                else:
                    historical_data.to_parquet(self.htf_parquet, compression='snappy')
                # LTF: mantener solo últimos 7 días
                if os.path.exists(self.ltf_parquet):
                    existing_ltf = pd.read_parquet(self.ltf_parquet)
                    if existing_ltf.index.tz is None:
                        existing_ltf.index = existing_ltf.index.tz_localize('UTC')
                    combined_ltf = pd.concat([existing_ltf, data])
                    combined_ltf = combined_ltf[~combined_ltf.index.duplicated(keep='last')]
                    combined_ltf.sort_index(inplace=True)
                    # Truncar a 3 días
                    cutoff = datetime.now(pytz.UTC) - timedelta(days=3)
                    cutoff = pd.Timestamp(cutoff)
                    combined_ltf = combined_ltf[combined_ltf.index >= cutoff]
                    combined_ltf.to_parquet(self.ltf_parquet, compression='snappy')
                    ui = getattr(self, 'ui', None)
                    if ui:
                        ui.add_log(f"[INFO] ✅ LTF actualizado: {len(combined_ltf)} velas (3 días)", style="dim")
                else:
                    data.to_parquet(self.ltf_parquet, compression='snappy')
        except Exception as e:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[ERROR] ❌ Error al guardar Parquet: {e}", style="dim")

    def update_live_cache(self, new_candles):
        """
        Actualiza el cache de velas live (últimas 100).

        Args:
            new_candles: list de dicts o DataFrame con nuevas velas
        """
        try:
            # Convertir a lista de dicts si es DataFrame
            if isinstance(new_candles, pd.DataFrame):
                new_candles = new_candles.reset_index().to_dict('records')
            # Cargar cache existente
            if os.path.exists(self.live_json):
                with open(self.live_json, "r") as f:
                    live_cache = json.load(f)
            else:
                live_cache = []
            # Agregar nuevas velas
            live_cache.extend(new_candles)
            # Mantener solo últimas 100
            if len(live_cache) > 100:
                live_cache = live_cache[-100:]
            # Guardar
            with open(self.live_json, "w") as f:
                json.dump(live_cache, f, indent=2)
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[INFO] 🔄 Live cache actualizado: {len(live_cache)} velas", style="dim")
        except Exception as e:
            ui = getattr(self, 'ui', None)
            if ui:
                ui.add_log(f"[ERROR] ❌ Error al actualizar live cache: {e}", style="dim")

    def get_stats(self):
        """
        Retorna estadísticas de los archivos de datos.
        """
        stats = {}

        # Parquet HTF
        if os.path.exists(self.htf_parquet):
            size_mb = os.path.getsize(self.htf_parquet) / 1024 / 1024
            df = pd.read_parquet(self.htf_parquet)
            stats['htf_parquet'] = {
                'exists': True,
                'size_mb': round(size_mb, 2),
                'rows': len(df),
                'oldest': str(df.index.min()),
                'newest': str(df.index.max())
            }
        else:
            stats['htf_parquet'] = {'exists': False}

        # Parquet LTF
        if os.path.exists(self.ltf_parquet):
            size_mb = os.path.getsize(self.ltf_parquet) / 1024 / 1024
            df = pd.read_parquet(self.ltf_parquet)
            stats['ltf_parquet'] = {
                'exists': True,
                'size_mb': round(size_mb, 2),
                'rows': len(df),
                'oldest': str(df.index.min()),
                'newest': str(df.index.max())
            }
        else:
            stats['ltf_parquet'] = {'exists': False}

        # Live JSON
        if os.path.exists(self.live_json):
            size_kb = os.path.getsize(self.live_json) / 1024
            with open(self.live_json, "r") as f:
                live = json.load(f)
            stats['live_json'] = {
                'exists': True,
                'size_kb': round(size_kb, 2),
                'candles': len(live)
            }
        else:
            stats['live_json'] = {'exists': False}

        # Legacy JSON
        if os.path.exists(self.legacy_json):
            size_mb = os.path.getsize(self.legacy_json) / 1024 / 1024
            stats['legacy_json'] = {
                'exists': True,
                'size_mb': round(size_mb, 2)
            }
        else:
            stats['legacy_json'] = {'exists': False}

        return stats


if __name__ == "__main__":
    # Test del loader
    loader = DataLoader()

    # No imprimir nada en consola, solo log si hay UI
    ui = getattr(loader, 'ui', None)
    if ui:
        ui.add_log("\n📊 Estadísticas de archivos:", style="dim")
        ui.add_log(json.dumps(loader.get_stats(), indent=2), style="dim")
        ui.add_log("\n🔍 Cargando datos...", style="dim")
    htf, ltf = loader.load_historical_data()
    if ui:
        ui.add_log(f"\n✅ HTF: {len(htf)} registros", style="dim")
        if not htf.empty:
            ui.add_log(str(htf.tail(3)), style="dim")
        ui.add_log(f"\n✅ LTF: {len(ltf)} registros", style="dim")
        if not ltf.empty:
            ui.add_log(str(ltf.tail(3)), style="dim")
