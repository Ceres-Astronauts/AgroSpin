# Field Shift — estado público del MVP (borrador)

Field Shift es un asistente de decisión para comparar rotaciones de cultivo en condiciones de agua y clima cambiantes. No es un visor de satélites.

## Qué está verificado
| Componente | Estado | Evidencia |
|---|---|---|
| Precipitación y clima diario (NASA POWER, 1991–2025) | Adquirido y chequeado mecánicamente (completitud y rangos) | `e2-mechanical-checks.md` |
| Humedad de suelo (NASA SMAP L4 SPL4SMGP.008, 2015–2025, 3 puntos) | `sm_surface` y `sm_rootzone` con E1 aprobado; agregación diaria verificada | `e2-mechanical-checks.md` |
| Catálogo de cultivos | Coeficientes Kc y profundidad de raíz con cita FAO-56; ciclos y ensayos con cita; lo que falta marcado `NO_VERIFICADO` | `crop-catalog.yml` |
| Diseño del motor de comparación | Documentado, sin implementación de ranking | `p6-minimal-engine-design.md` |

## Qué está bloqueado, y por qué
- **No hay ranking ni recomendación de rotación.** La validación científica (E2) está abierta: falta comparar con datos independientes de estación o campo.
- **No hay balance hídrico por parcela.** Falta un perfil de suelo local medido; la fuente prevista (INTA SISINTA) no respondió en la adquisición.
- **Las escalas son regionales.** Los datos de NASA son de grilla y no representan una parcela.

## Cómo se evalúa cada resultado
Cada dato lleva su fuente, su nivel de evidencia (E0 a E7) y sus límites. Un valor sin validación no se presenta como resultado científico.

## Qué no incluye este repositorio
Datos crudos, credenciales y rutas locales. Los datos se obtienen de las fuentes originales citadas.
