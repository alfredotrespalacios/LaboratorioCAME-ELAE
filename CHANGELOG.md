# Historial de cambios

## 1.4.1 — 2026-08-08

- Corrige la construcción de la primera base: ninguna variable es obligatoria y solo se
  consultan las variables seleccionadas por el usuario.
- Conserva y recupera el ZIP descargable después de los reinicios de Streamlit.
- Amplía el selector de fecha inicial hasta el último día del año anterior.
- Añade CEN, factor de planta, disponibilidad en GWh-día y precio de oferta a la curva rápida.
- Muestra la disponibilidad normal y de El Niño por tecnología en el balance energético.

## 1.4.0 — 2026-08-08

- Nueva canasta colombiana preseleccionada y catálogo mensual completo descargable.
- Generación prioritaria por empresa, recurso y tecnología; asociación histórica empresa–recurso
  cuando XM publica vigencias.
- MC, contratos regulados/no regulados, escasez, ofertas de combustibles, aportes, CEN, embalses,
  disponibilidad, intercambios, DNA, restricciones, TRM y ENSO integrables desde Mantenimiento.
- Modelos supervisados con transformaciones individuales, OLS clásico, árboles, KNN y Random
  Forest; prueba opcional, diagnósticos, pronóstico exógeno y comparación de métodos.
- Modelos ingenuos, ARIMA y SARIMA con MASE, origen móvil, reporte Statsmodels, residuales y rangos.
- Cálculo rápido de portafolios con sobrecontratación/posición compradora y sensibilidades de
  contratación, correlación y precio.
- Excel y PDF ampliados con tablas, gráficos y trazabilidad metodológica.

## 1.3.2

- Flujo reanudable de mantenimiento, publicación atómica y recuperación de ZIP.
- Python 3.12 obligatorio y carga diferida de páginas.
