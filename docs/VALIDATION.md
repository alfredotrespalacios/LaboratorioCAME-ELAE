# Informe de validación v1.5.2

Fecha: 7 de septiembre de 2026.

## Resultado

- Lint: `ruff check .` sin hallazgos.
- Pruebas locales: 95 aprobadas; los tres contratos externos permanecen excluidos del chequeo
  local.
- Contratos vivos: se mantienen separados del cierre reproducible porque dependen de servicios
  externos; ejecútelos con `make live-check` antes y después de desplegar.
- Smoke de Streamlit: página inicial cargada sin excepciones en modo local.
- Páginas críticas: Modelación, Portafolios, Base integrada y Mantenimiento arrancaron de forma
  independiente sin excepciones.
- Introducción: primera página del menú, anterior a Colombia, con propiedad, alcance y guía de uso.
- Casos de estudio: módulos 14–18 renombrados en navegación y páginas.
- Compilación: todos los módulos Python compilados.
- Secretos: no se incorpora `secrets.toml`, `.env` ni contraseña real.
- Empaquetado mensual: Parquet, Excel, JSON y ZIP aprobados con datos sintéticos trazables.
- Persistencia de descarga: el flujo completo **Construir la primera base** termina con ZIP y una
  sesión nueva vuelve a mostrar su descarga sin depender de `session_state`.
- Construcción automática: una selección de varias variables se divide en etapas sin intervención
  adicional; cada ejecución procesa como máximo tres etapas nuevas y puede continuar el grupo
  siguiente sin repetir sus consultas.
- ZIP de avance: después de cada etapa aprobada se escribe y verifica un paquete recuperable. Una
  falla posterior conserva el Parquet publicado y los datos nuevos ya aprobados, y mantiene
  habilitada la descarga del ZIP parcial.
- Base parcial: `target_options` prevalece sobre la selección incompleta de una versión anterior;
  por eso una Demanda publicada no se interpreta como si fuera toda la canasta solicitada.
- Continuación parcial: si la Demanda termina antes del último mes solicitado, la consulta comienza
  en el mes siguiente al ya guardado y conserva toda la historia anterior.
- Actualización: el JSON conserva `selected_options` y `option_series` para mantener la misma
  canasta y comprobar su cobertura al agregar meses.
- Selección de variables: una construcción con solo demanda no consulta generación, recursos,
  capacidad, TRM ni ONI; ninguna de esas series se exige para crear el paquete.
- Fechas de mantenimiento: tanto la fecha inicial como la final permiten seleccionar desde el 1 de
  enero de 1990 hasta la fecha actual. Colombia limita cada intervalo a 60 meses.
- Mes actual: puede incluirse en el paquete con marca de periodo parcial y vuelve a consultarse en
  una ejecución posterior; los meses históricos completos se reutilizan.
- Ausencia de datos: una etapa histórica consultada correctamente sin observaciones queda
  registrada por variable y periodo, y no se solicita de nuevo indefinidamente.
- Cierre visible: **0/5** y **1/5–5/5** permanecen renderizados. Con datos aprobados, un error de
  fuente produce un ZIP de avance que identifica las etapas pendientes; sin datos empaquetables,
  la pantalla explica por qué no puede construirlo.
- Compatibilidad: `app.py` detiene la ejecución antes de importar `came` cuando Python no es 3.12.
  Las páginas y exportadores se cargan de manera diferida para reducir importaciones durante una
  recarga del despliegue.
- Compatibilidad: se detecta un paquete completo guardado por la versión 1.3.0, cuando todavía
  existe en la instancia, antes de obligar a repetir la descarga histórica.
- Memoria: Parquet, Excel, JSON y ZIP se escriben por etapas en disco; la pantalla carga de forma
  predeterminada únicamente el ZIP y deja los archivos individuales bajo petición.
- Memoria de generación: cada bloque de 14 días se reduce a agregados mensuales antes de acumular la
  historia completa.
- Navegación: cada página visible se importa desde un archivo Python independiente.
- Precio y Demanda: apertura desde el Parquet mensual, con consulta XM opcional.
- Calidad diaria: un día incompleto de demanda se excluye y se informa el último día completo.
- Informe ejecutivo: la canasta permanece vacía hasta que el usuario pulsa el botón de guardado.
- Mantenimiento: un bloque temporalmente fallido se recupera dentro de tres intentos, conserva los
  puntos de avance y registra fuente, variable, periodo, estado y detalle en la interfaz y en los
  registros del despliegue.
- Mensajes de estado: se eliminó la afirmación fija de que la Demanda ya estaba construida. El
  estado mostrado se deriva del Parquet y el JSON realmente publicados.
- Recuperación de directorios: el almacén de avances y la escritura atómica del paquete recrean
  sus carpetas si fueron eliminadas antes de guardar un bloque o archivo, y repiten una vez la
  escritura si la carpeta desaparece exactamente durante la operación.
- Compatibilidad Streamlit 1.61: se sustituyó `use_container_width` por `width`, sin advertencias
  de la API durante el smoke local.
- Modelación supervisada: periodo histórico seleccionable, evaluación por fecha o periodos,
  recalibración final con 100 %, importancias de Random Forest, pronóstico recursivo, intervalos y
  dos reportes OLS de Statsmodels validados con datos sintéticos.
- Series temporales: evaluación cronológica separada de la calibración final, MASE, origen móvil,
  diagnósticos ACF/PACF y reportes Statsmodels de evaluación y finales disponibles en pantalla y
  exportaciones.
- Balance: demandas y nombres distintos por escenario, FP total ponderado por CEN, fila Total,
  ecuaciones de margen cero, dos líneas de demanda y PDF con figuras validados en Streamlit.
- PDF: la conversión real de Plotly a PNG fue probada; una falla de render impide entregar un PDF
  sin las figuras solicitadas.
- Portafolios: diez porcentajes contratados y cinco escenarios de correlación o precio producen 50
  combinaciones comparables con la misma semilla; M-CVaR está incluido.

## Contraste con los Excel entregados

### Balance energético

Los valores de capacidad y factores de planta de las filas 17–27 del Excel producen:

| Resultado | Excel | Aplicación |
|---|---:|---:|
| Disponibilidad normal (GWh-día) | 306,5114852424 | 306,5114852424 |
| Margen normal | 0,3043041925 | 0,3043041925 |
| Disponibilidad Niño (GWh-día) | 252,6086998824 | 252,6086998824 |
| Margen Niño | 0,0642877602 | 0,0642877602 |

### Curva rápida

Con los valores de las filas 26–36 del Excel:

| Resultado | Excel | Aplicación |
|---|---:|---:|
| Disponibilidad total (GWh-día) | 297,9920001126 | 297,9920001126 |
| Demanda (GWh-día) | 240,83315642 | 240,83315642 |
| Unidad marginal | Gas | Gas |
| Precio marginal discreto (COP/kWh) | 450 | 450 |

La aplicación reestima los coeficientes polinómicos y exponenciales con precisión completa a partir
de la tabla editada; no copia los coeficientes redondeados escritos en el Excel. También evita
extrapolar un precio de equilibrio cuando la oferta total es inferior a la demanda.

## Limitación externa conocida

El Coordinador de Chile publica sus exploradores sobre Qlik/Cloudflare. La descarga automatizada no
es estable sin una URL administrada. El módulo procesa exportaciones oficiales TSV/XLSX de costos,
demanda y generación; las pruebas validan los parsers y la ponderación. No afirma disponibilidad
automática inexistente.

La carga histórica completa no forma parte del chequeo local. La aplicación deja visible el avance,
guarda bloques temporales y habilita un ZIP completo o de avance cuando existe información válida
para conservar. Las llamadas reales a las fuentes deben comprobarse mediante `make live-check` en
un entorno con acceso a XM, REData y OMIE.
