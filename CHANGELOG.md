# Historial de cambios

## 1.5.2 — 2026-09-07

- Permite seleccionar fechas de mantenimiento desde el 1 de enero de 1990 hasta la fecha actual,
  tanto al construir como al actualizar o recalcular Colombia.
- Limita cada intervalo colombiano a cinco años y cada ejecución a un grupo corto de etapas para
  evitar una única operación prolongada en Streamlit.
- Genera y verifica un ZIP recuperable después de cada etapa aprobada; el ZIP de avance permanece
  descargable aunque una fuente falle o queden etapas pendientes.
- Registra en el JSON el periodo solicitado, la canasta objetivo, las etapas completas, pendientes
  y fallidas, además de una bitácora de la corrida.
- Lee la canasta objetivo y la cobertura publicadas para conservar datos completos, consultar lo
  pendiente y concatenar los resultados sin duplicar claves mensuales.
- Marca el mes actual como parcial, permite incluirlo en el paquete y vuelve a consultarlo en una
  actualización posterior.
- Añade el botón **Continuar con las etapas pendientes** y recupera el último ZIP aunque se pierda
  el estado de la sesión.
- Sustituye los mensajes basados en supuestos por mensajes derivados de los archivos realmente
  encontrados; elimina la afirmación fija sobre una Demanda previamente construida.
- Amplía los registros de ejecución con etapa, fuente, variable, periodo, estado y errores.
- Reescribe la guía visible de Mantenimiento para explicar la descarga, el reemplazo conjunto de
  Parquet, Excel y JSON, el *commit* manual y la continuación de la siguiente corrida.

## 1.5.1 — 2026-09-07

- Automatiza la construcción colombiana por etapas: el usuario selecciona la canasta una sola vez.
- Conserva en disco cada etapa completa y reanuda únicamente las variables o bloques pendientes.
- Reutiliza variables completas de una base parcial publicada cuando cubren el periodo solicitado.
- Registra en el JSON la selección y la correspondencia entre opciones y series para futuras
  actualizaciones.
- Comprueba la cobertura por variable al agregar meses y repara rezagos aunque la fecha general de
  la base ya esté actualizada.
- Reduce la generación histórica a agregados mensuales durante el recorrido de bloques para limitar
  el consumo de memoria.
- Incluye la Demanda aprobada de 2000 a junio de 2026 como avance inicial; la pantalla selecciona
  automáticamente la construcción completa y continúa desde julio.
- Añade progreso global por etapa y mantiene disponible la selección personalizada como opción
  avanzada.

## 1.5.0 — 2026-08-08

- Separa en Modelación la evaluación fuera de muestra, la calibración final y el pronóstico.
- Permite seleccionar las fechas del histórico y definir la prueba por fecha o número de periodos,
  con origen móvil como alternativa avanzada.
- Recalibra el modelo definitivo con todo el histórico seleccionado y presenta por separado los
  parámetros de evaluación y los parámetros finales, incluidos los reportes Statsmodels.
- Separa errores de prueba y residuales finales en pantalla, Excel y PDF.
- Amplía el Balance con nombres y demandas editables por escenario, crecimiento común, ecuaciones
  de margen cero, fila Total, FP ponderado por CEN y disponibilidad por tecnología.
- Añade dos líneas de demanda con nombres dinámicos sobre las barras apiladas de disponibilidad.
- Incluye las figuras en los PDF y detiene la exportación si una figura no puede renderizarse.

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
