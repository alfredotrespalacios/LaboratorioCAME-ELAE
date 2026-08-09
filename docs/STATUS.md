# Estado y bitácora

## Estado actual

- Versión 1.5.0 implementada y validada localmente el 8 de agosto de 2026.
- Navegación definitiva: introducción, 19 módulos y mantenimiento técnico no numerado.
- Base mensual de Colombia configurable, con canasta recomendada y catálogo completo para descarga.
- Modelación supervisada y temporal con periodo histórico editable, evaluación cronológica por
  fecha o periodos, recalibración final con toda la historia, diagnósticos, origen móvil,
  pronóstico y comparación exportable.
- Balance con nombres y demandas editables, fila Total, FP ponderado por CEN, ecuaciones de margen
  cero y dos líneas de demanda sobre disponibilidades apiladas.
- Portafolios Monte Carlo con posiciones contratadas entre −200 % y 200 %, sensibilidades conjuntas
  y métricas Media, desviación, VaR, CVaR y M-CVaR.
- No existen credenciales reales ni archivos de entorno dentro del repositorio.

## Decisiones técnicas

- Código analítico separado de Streamlit y conectores oficiales con salida canónica común.
- Colombia consulta y conserva únicamente las variables elegidas por el usuario. La canasta CAME
  es la selección inicial recomendada, pero ninguna serie es obligatoria.
- La asociación recurso–empresa usa la vigencia histórica publicada cuando el catálogo de XM la
  expone; si solo existe una asignación, se usa la última oficial conocida.
- El precio de oferta de gas y carbón se publica como promedio simple y ponderado por capacidad
  efectiva, nunca por generación.
- MC se descubre desde el catálogo vivo de XM y permanece separado de los precios promedio de
  contratos regulados y no regulados.
- Los paquetes Parquet, Excel y JSON se escriben por etapas y se comprimen en un ZIP recuperable.
- El despliegue exige Python 3.12 y carga las páginas únicamente cuando se abren.

## Verificaciones cerradas

- `ruff check .` sin hallazgos y compilación completa de `app.py`, `src/` y `tests/`.
- 86 pruebas locales aprobadas; 3 contratos vivos quedan separados mediante la marca `live`.
- Smoke de la introducción y arranque directo de Modelación, Portafolios, Base integrada y
  Mantenimiento sin excepciones de Streamlit.
- Balance y curva de oferta continúan contrastados con los Excel pedagógicos recibidos; el smoke
  del Balance valida cálculo, ecuaciones, figuras y descargas Excel/PDF/JSON.
- La exportación PDF renderiza las figuras con versiones fijadas de Plotly/Kaleido y no permite
  producir silenciosamente un reporte incompleto si falla una imagen.
- Empaquetado mensual, recuperación del ZIP, exclusión de periodos incompletos, reintentos y
  publicación atómica permanecen cubiertos por pruebas.

## Limitaciones documentadas

- Las consultas vivas dependen de la disponibilidad de XM, REData, OMIE, datos.gov.co y NOAA.
- Chile requiere exportaciones oficiales TSV/XLSX cuando Qlik/Cloudflare impide la descarga estable.
- La base histórica completa debe construirse en un entorno con acceso a las fuentes y luego
  publicarse en `datos_por_defecto/` mediante el ZIP generado por Mantenimiento.
