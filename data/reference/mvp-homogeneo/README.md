# Field Shift — Entrega MVP: clima histórico + suelo (datos homogéneos)

Recorte geográfico: lon −65,875 a −64,125 · lat −33,875 a −33,125 (Villa Mercedes, San Luis – sur de Córdoba).
Corte de datos: 2026‑11‑01. CRS: EPSG:4326 (lat/lon). Fecha de entrega: 2026‑11‑15.

Todo lo que está aquí sale de datos ya validados y curados. Cada fila lleva una columna `origen` que dice si el dato es
**OBSERVADO** (medido en tierra), **ESTIMADO** (reanálisis o modelo) o **REFERENCIA** (fuera de la caja o de terceros).
No se mezclan categorías: un ESTIMADO nunca se presenta como OBSERVADO.

## Qué hay en la carpeta

| Archivo | Filas | Para qué sirve | Looker Studio |
|---|---|---|---|
| `clima_mensual_grilla_1991_2026.csv` | 13.792 | Lluvia, temperatura, ETo, balance hídrico, heladas, estrés térmico y ENSO por mes y por punto (32 puntos de 0,25°) | **Principal** |
| `clima_anual_grilla_1991_2026.csv` | 1.152 | Resumen por año y punto: ventana libre de heladas, lluvia oct‑mar, ETo, grados‑día | Sí |
| `clima_zona_diario_1991_2026.csv` | 13.089 | Una serie diaria para toda la caja (temperatura ponderada por estaciones en tierra + lluvia y ETo medias) | Sí |
| `clima_diario_grilla_1991_2026.csv` / `.parquet` | 418.848 | Serie diaria completa por punto, con ETo FAO‑56, heladas, estrés, GDD | CSV 56 MB: usar Sheets/BigQuery o filtrar |
| `enso_oni_mensual.csv` | 429 | Índice ONI y fase Niño/Niña/Neutro por mes (NOAA) | Sí |
| `humedad_suelo_mensual_grilla_1991_2026.csv` | 13.792 | Nivel medio mensual de humedad de suelo del modelo de balance — **NO validada en correlación** | Sí, con la advertencia |
| `suelo_500m_grilla.csv` | 54.600 | Relieve, pendiente, susceptibilidad topográfica y humedad media agregados a ~500 m | **Principal (mapa)** |
| `suelo_1ha_grilla.parquet` | 1.352.847 | Lo mismo a 1 ha (100 m). Para el stack, no para Looker | No (48 MB parquet) |
| `suelo_gaez_cultivos_1981_2010.csv` | 5.280 | Aptitud y rendimiento alcanzable FAO GAEZ v4 por cultivo (maíz, soja, girasol, sorgo, trigo, maní, alfalfa, cebada), celdas de 1/12° | Sí |
| `suelo_sisinta_perfiles_caja.csv` | 257 | Horizontes de perfiles de suelo INTA SISINTA dentro de la caja: textura, pH, carbono, agua útil | Sí |
| `estaciones_terrestres.csv` | 19 | Catálogo de estaciones en tierra (REM, SMN, PIHC, IDECOR, Meteostat) con coordenadas y veredicto de validación | Sí (mapa) |
| `diccionario_columnas.csv` | — | Qué es cada columna, unidad y fuente | Referencia |
| `cobertura_necesidades_mvp.csv` | — | Cada variable del Excel de necesidades → tabla y columnas que la cubren, y qué queda parcial o fuera | Referencia |
| `manifest.json`, `SHA256SUMS` | — | Trazabilidad y verificación de integridad (`sha256sum -c SHA256SUMS`) | — |

Claves de unión: `punto_id` (clima, humedad), `anio_mes` (mensual ↔ ENSO), `lat`/`lon` (todo es EPSG:4326).

## Cómo usarlo en Google Looker Studio

1. **Crear la fuente de datos** → conector **Carga de archivos** (CSV). Subí primero `clima_mensual_grilla_1991_2026.csv`, `suelo_500m_grilla.csv`, `estaciones_terrestres.csv` y `enso_oni_mensual.csv`. El conector de archivos tiene un límite por archivo (del orden de 100 MB); por eso el diario completo se entrega en Parquet y el CSV diario conviene cargarlo vía Google Sheets/BigQuery o filtrarlo por punto.
2. **Tipos de campo** (Looker a veces no los infiere):
   - `lat` → *Geo → Latitud*, `lon` → *Geo → Longitud*. Para mapas con burbujas, usá ambos; para mapas de calor, `suelo_500m_grilla`.
   - `anio_mes` → *Fecha → Año Mes* (formato `YYYY-MM`). `fecha` → *Fecha*.
   - `origen`, `fase_enso`, `estado_completitud`, `etiqueta_*` → *Texto* (usarlos como filtros y leyendas).
3. **Combinar datos (blend)**: clima mensual ↔ ENSO por `anio_mes`; clima mensual ↔ humedad mensual por `punto_id` + `anio_mes`; clima ↔ suelo por `lat`/`lon` (misma grilla no: clima es 0,25°, suelo 500 m; unir por punto más cercano se hace en el stack, no en Looker).
4. **Gráficos sugeridos** para las necesidades del Excel:
   - Patrones de temperatura: serie de `tmean_c` mensual + `gdd_base10` acumulado por campaña.
   - Estrés térmico: `dias_estres_termico` por mes (filtro `mes` 11–2).
   - Precipitaciones: `precip_mm` mensual y `precip_oct_mar_mm` anual; colorear por `fase_enso`.
   - Heladas: `primera_helada_otono`, `ultima_helada_primavera`, `dias_libres_heladas_campana` (tabla anual).
   - Evapotranspiración: `eto_mm` y `balance_p_eto_mm` (negativo = déficit).
   - Suelo: mapa de `pendiente_media_pct`, `susceptibilidad_topografica_media` (leyenda: **índice no validado, no es mapa de inundación**), y `humedad_nivel_medio_m3_m3` (leyenda: **no validada en correlación**).
5. **Mostrar siempre la etiqueta de origen** en los paneles: es la diferencia entre dato medido y estimado.

## Cómo usarlo en el stack (Python · Pandas · Parquet · FastAPI · Leaflet)

```python
import pandas as pd
BASE = "<ruta>/entrega-mvp"               # p. ej. data/reference/mvp-homogeneo en el repo field-shift

clima_d = pd.read_parquet(f"{BASE}/clima_diario_grilla_1991_2026.parquet")
clima_m = pd.read_parquet(f"{BASE}/clima_mensual_grilla_1991_2026.parquet")
suelo   = pd.read_parquet(f"{BASE}/suelo_1ha_grilla.parquet")           # solo en el almacén de datos
gaez    = pd.read_csv(f"{BASE}/suelo_gaez_cultivos_1981_2010.csv")
hum_m   = pd.read_csv(f"{BASE}/humedad_suelo_mensual_grilla_1991_2026.csv")

def punto_power_mas_cercano(lat, lon):
    pts = clima_m[["punto_id", "lat", "lon"]].drop_duplicates()
    i = ((pts.lat - lat) ** 2 + (pts.lon - lon) ** 2).idxmin()
    return pts.loc[i, "punto_id"]

def clima_lote(lat, lon, desde="2015-01-01"):
    pid = punto_power_mas_cercano(lat, lon)
    s = clima_d[(clima_d.punto_id == pid) & (clima_d.fecha >= desde)]
    return s.to_dict("records")            # listo para Pydantic / JSON en FastAPI
```

- **FastAPI**: cargá los Parquet una vez al arrancar (`@app.on_event("startup")`) y serví por `punto_id` o por lat/lon; devolvé siempre `origen` en la respuesta.
- **Leaflet**: `estaciones_terrestres.csv` y `suelo_500m_grilla.csv` se convierten directo a GeoJSON de puntos (lat/lon ya en WGS84). Para polígonos dibujados con Leaflet.draw, promediá las celdas de `suelo_1ha_grilla.parquet` dentro del polígono.
- Cada dato debe mostrarse con su `origen`/`etiqueta`; no mezclar `ESTIMADO_*` con `OBSERVADO_*` en un mismo promedio sin decirlo.

## Métodos y límites (léelo antes de interpretar)

- **Clima por punto** = NASA POWER (reanálisis MERRA‑2, 0,25°). Es `ESTIMADO_POWER`. Las temperaturas en tierra (REM San Luis) están en `clima_zona_diario` ponderadas por cercanía; su validación contra POWER está cerrada (r ≈ 0,97 en temperatura diaria).
- **ETo** = FAO‑56 Penman‑Monteith diaria con T, HR, viento, radiación y presión de POWER; elevación de SRTM. 32 días (uno por punto, el último) quedan sin ETo por faltante en la fuente.
- **Heladas**: umbral agrometeorológico `tmin < 3 °C` (y `tmin ≤ 0 °C`), medido a 2 m en POWER; en el lote puede haber más heladas que en la grilla.
- **ENSO**: ONI de NOAA, trimestre centrado en el mes; `fase_enso` con umbral ±0,5 °C. Los dos últimos meses del corte no tienen ONI aún.
- **Humedad de suelo**: modelo de balance hídrico calibrado con SMAP de 3 puntos. RMSE y sesgo cumplen; la correlación diaria **no** (0,48–0,50 contra 0,60). Por eso solo se entrega el **nivel medio mensual**, etiquetado `NO_VALIDADA_CORRELACION`. SMAP de 32 puntos y GLDAS quedaron fuera del MVP.
- **Relieve**: SRTMGL1 30 m agregado a 1 ha (y a 500 m). 85 celdas con pendiente > 100 % están marcadas `pendiente_atipica` (artefactos probables), no borradas.
- **Susceptibilidad topográfica**: índice 0‑1 (TWI + depresiones) sobre el relieve suavizado 4×. **No es un mapa de inundación** ni está validado con eventos.
- **GAEZ v4**: aptitud y rendimiento alcanzable 1981‑2010 (secano, insumos altos) en celdas de 1/12°. No hay codebook local: `clase_aptitud` es el código tal cual viene (1 = mejor … 8 = peor); rendimiento en kg/ha según documentación GAEZ.
- **SISINTA**: 257 horizontes de 198 perfiles dentro de la caja. Solo 9 horizontes tienen textura completa y ensayos de capacidad de campo/PMP; el resto está marcado `SIN_DATO_COMPLETO`.
- **Córdoba** tiene menos observación en tierra que San Luis: la lluvia de Achiras (28 meses con datos) y la temperatura de Bell Ville (sin estación) son las limitaciones principales.

Decisiones y trazabilidad completa: repositorio `field-shift-context`, carpeta `reference/decisions/` (ver `manifest.json` → `decisiones`).
