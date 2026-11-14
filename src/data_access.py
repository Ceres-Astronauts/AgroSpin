"""
Conector de datos satelitales y agroclimáticos para Field Shift.
Permite lectura transparente desde Google Drive mediante streaming del CLI de gdrive
sin saturar el almacenamiento en disco local, con fallback a caché en memoria o rutas locales.
"""

import io
import json
import logging
import os
import subprocess
from typing import Any, Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)

# IDs canónicos en Google Drive (Carpeta compartida 1BaYod-l94Vl-_dPjWiGnheTrJzgtPer3)
DRIVE_FILE_IDS = {
    "nasa_power_daily": "1J3zJxJlBMj9CQu97TF3fzmWU9q4BYy5c",  # power_daily_point_19910101_20251231.json
    "smap_bundle": "1SW7bu5NgoXVVt4z6Fl4j_nXhAW_6R0Jk",       # bundle.json
    "smap_csv": "1zZdMsIdpfo9KRyCawn7I7_CGSLArb9KX",          # CSV con series SMAP
}


def descargar_en_memoria_drive(file_id: str) -> Optional[bytes]:
    """
    Descarga el contenido de un archivo de Google Drive directamente en memoria (RAM)
    a través del CLI gdrive de Antigravity sin escribirlo a disco.
    """
    try:
        # Usamos stdout de gdrive para volcar directo a memoria
        cmd = ["gdrive", "readonly", "download", file_id, "--out", "-"]
        proc = subprocess.run(cmd, capture_output=True, check=True)
        return proc.stdout
    except Exception as exc:
        logger.warning(f"No se pudo descargar en memoria el archivo {file_id} desde Drive: {exc}")
        return None


def cargar_serie_nasa_power(ruta_local: Optional[str] = None) -> tuple[Optional[pd.DataFrame], int, str]:
    """
    Carga la serie temporal de precipitación y meteorología de NASA POWER.
    Prioridad:
    1. Si se provee ruta_local válida (o env FIELD_SHIFT_POWER_JSON), lee local.
    2. Si no, intenta leer directamente desde Google Drive vía stream en memoria.
    Retorna: (DataFrame, descartados_fill, fuente_origen)
    """
    env_path = os.environ.get("FIELD_SHIFT_POWER_JSON", "").strip()
    target_local = ruta_local or env_path

    if target_local and os.path.isfile(target_local):
        try:
            with open(target_local, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _procesar_json_power(data, f"Archivo local: {os.path.basename(target_local)}")
        except Exception as exc:
            logger.error(f"Error leyendo archivo local de POWER: {exc}")

    # Fallback a Google Drive en memoria
    bytes_data = descargar_en_memoria_drive(DRIVE_FILE_IDS["nasa_power_daily"])
    if bytes_data:
        try:
            data = json.loads(bytes_data.decode("utf-8"))
            return _procesar_json_power(data, "Google Drive (en memoria vía gdrive)")
        except Exception as exc:
            logger.error(f"Error procesando JSON de POWER desde Drive: {exc}")

    return None, 0, "No disponible"


def _procesar_json_power(data: Dict[str, Any], fuente: str) -> tuple[Optional[pd.DataFrame], int, str]:
    """Procesa el diccionario de NASA POWER y retorna DataFrame limpio."""
    try:
        series = data["properties"]["parameter"]["PRECTOTCORR"]
        frame = pd.DataFrame({
            "date": pd.to_datetime(list(series.keys()), format="%Y%m%d"),
            "precip_mm": list(series.values()),
        })
        fill_mask = frame["precip_mm"].eq(-999.0)
        discarded = int(fill_mask.sum())
        clean_frame = frame.loc[~fill_mask].sort_values("date")
        return clean_frame, discarded, fuente
    except Exception as exc:
        logger.error(f"Estructura inesperada en JSON de NASA POWER: {exc}")
        return None, 0, "Error de estructura"
