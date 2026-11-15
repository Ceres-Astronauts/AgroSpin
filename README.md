# Field Shift — estado público del MVP

Field Shift es un asistente de decisión para comparar rotaciones de cultivo en condiciones de agua y clima cambiantes. No es un visor de satélites.

Zona del MVP: lon −65,875 a −64,125 · lat −33,875 a −33,125 (Villa Mercedes, San Luis – sur de Córdoba). Corte de datos: 2026‑11‑01.

## Datos del MVP: entrega de clima histórico + suelo (2026‑11‑15)

Conjunto homogéneo listo para ingestar en **Google Looker Studio** y en el stack (Python · Pandas · Parquet/CSV · FastAPI · Leaflet), en EPSG:4326.
Está completo en [`data/reference/mvp-homogeneo/`](data/reference/mvp-homogeneo/) (125 MB, sin almacenamiento externo):

| Tabla | Qué contiene |
|---|---|
| `clima_mensual_grilla_1991_2026` / `clima_anual_grilla_1991_2026` | Lluvia, temperatura, ETo FAO‑56, balance P−ETo, heladas (<3 °C y ≤0 °C), estrés térmico (>35 °C), grados‑día, ventana libre de heladas, fase ENSO — 32 puntos de 0,25°, 1991–2026 |
| `clima_diario_grilla_1991_2026` (CSV y Parquet) | Serie diaria completa por punto |
| `clima_zona_diario_1991_2026` | Serie única de la zona, temperatura ponderada por estaciones en tierra (REM San Luis) |
| `enso_oni_mensual` | Índice ONI (NOAA) y fase Niño/Niña/Neutro |
| `suelo_1ha_grilla` (Parquet) / `suelo_500m_grilla` (CSV) | Relieve SRTM, pendiente, susceptibilidad topográfica, humedad media |
| `suelo_gaez_cultivos_1981_2010` | Aptitud y rendimiento alcanzable FAO GAEZ v4 para 8 cultivos |
| `suelo_sisinta_perfiles_caja` | Horizontes de perfiles INTA SISINTA dentro de la zona (textura, pH, carbono, agua útil) |
| `humedad_suelo_mensual_grilla_1991_2026` | Nivel medio mensual de humedad de suelo (modelo) — **no validada en correlación** |
| `estaciones_terrestres` | 19 estaciones en tierra con coordenadas y veredicto de validación |
| `README.md`, `diccionario_columnas.csv`, `cobertura_necesidades_mvp.csv`, `cargar_mvp.py` | Instrucciones de uso (Looker y stack), unidades, qué necesidad del negocio cubre cada tabla, cargador Python |

Cada fila lleva una columna `origen`: **OBSERVADO** (medido en tierra), **ESTIMADO** (reanálisis o modelo) o **REFERENCIA** (fuera de la zona o de terceros). No se mezclan.
Integridad: `sha256sum -c SHA256SUMS` dentro de la carpeta.

## Qué está verificado
| Componente | Estado | Evidencia |
|---|---|---|
| Clima diario y mensual (NASA POWER, 32 puntos, 1991–2026) | Completo; temperatura contrastada con estaciones REM en tierra (r ≈ 0,97) | `data/reference/mvp-homogeneo/README.md`; decisiones en `field-shift-context` |
| Estaciones en tierra (REM San Luis, SMN, PIHC, IDECOR) | Validadas con veredicto por estación; lluvia de Córdoba con huecos documentados | `estaciones_terrestres.csv` |
| Relieve y pendiente (SRTMGL1 30 m → 1 ha y 500 m) | Verificado; 85 celdas con pendiente atípica marcadas, no borradas | `suelo_1ha_grilla.parquet`, `manifest.json` |
| Perfiles de suelo (INTA SISINTA) | 198 perfiles en la zona; solo 9 horizontes con textura y capacidad de campo completas | `suelo_sisinta_perfiles_caja.csv` |
| Aptitud por cultivo (FAO GAEZ v4, 1981–2010) | Recorte íntegro de la fuente; sin codebook local | `suelo_gaez_cultivos_1981_2010.csv` |
| Catálogo de cultivos | Coeficientes Kc y profundidad de raíz con cita FAO‑56; lo que falta marcado `NO_VERIFICADO` | [`docs/challenge/crop-catalog.yml`](docs/challenge/crop-catalog.yml) |

## Qué está limitado, y por qué
- **Humedad de suelo:** el modelo de balance (calibrado con SMAP de 3 puntos) cumple RMSE y sesgo pero no la correlación diaria (0,48–0,50 contra 0,60). Se entrega solo el nivel medio mensual, etiquetado `NO_VALIDADA_CORRELACION`. SMAP de 32 puntos y GLDAS quedaron fuera del MVP.
- **Susceptibilidad topográfica:** es un índice del relieve (TWI + depresiones). **No es un mapa de inundación** ni está validado con eventos.
- **Las escalas son regionales.** POWER es grilla de 0,25°; GAEZ de 1/12°. No representan una parcela. El relieve (1 ha) y los perfiles de suelo sí son locales.
- **Córdoba tiene menos observación en tierra** que San Luis (Achiras: 28 meses de lluvia; Bell Ville: sin estación de temperatura).
- **No hay ranking ni recomendación de rotación.** Falta la validación de campo (E2) y el cruce con Kc/calendario por cultivo.

## Cómo se evalúa cada resultado
Cada dato lleva su fuente, su nivel de evidencia y sus límites. Un valor sin validación no se presenta como resultado científico.

## Qué no incluye este repositorio
Datos crudos de las fuentes, credenciales y rutas locales. La trazabilidad completa (decisiones, validaciones, snapshots) está en el repositorio `field-shift-context`.

---

Documentación general del proyecto (contexto, arquitectura y decisiones): [docs/project-overview.md](docs/project-overview.md).

Notas técnicas del challenge: [docs/challenge/](docs/challenge/).
